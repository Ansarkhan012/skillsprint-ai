"""Official DeepSeek Responses adapter. No network activity on import or configuration."""
from time import perf_counter

import httpx
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .generation_content import CONTENT_V412
from .generation_prompt import FORMAT_RETRY_RULE, MAX_PROVIDER_REQUEST_BYTES, PromptPack, provider_schema_for
from .generation_provider import (ProviderConfig, ProviderFailure, ProviderResult, ProviderUsage,
                                  _bounded_retry_after, post_with_deadline)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_ENDPOINT = DEEPSEEK_BASE_URL + "/responses"
DEEPSEEK_MODEL = "deepseek-flash"


class DeepSeekEnvironment(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    deepseek_api_key: SecretStr | None = Field(default=None, repr=False)
    deepseek_model: str = DEEPSEEK_MODEL
    deepseek_timeout_seconds: float = 120
    deepseek_max_output_tokens: int = 8192
    deepseek_temperature: float = 0.1

    def adapter_config(self) -> ProviderConfig:
        if (not self.deepseek_api_key or not self.deepseek_api_key.get_secret_value().strip()
                or self.deepseek_model != DEEPSEEK_MODEL):
            raise ProviderFailure("PROVIDER_CONFIGURATION_FAILED")
        try:
            return ProviderConfig(provider="deepseek", model=DEEPSEEK_MODEL,
                                  api_key=self.deepseek_api_key,
                                  timeout_seconds=self.deepseek_timeout_seconds,
                                  max_output_tokens=self.deepseek_max_output_tokens,
                                  temperature=self.deepseek_temperature)
        except ValueError:
            raise ProviderFailure("PROVIDER_CONFIGURATION_FAILED") from None


def deepseek_request_payload(prompt: PromptPack, config: ProviderConfig, *, format_retry: bool = False) -> dict:
    """Pure request constructor used by the adapter and the zero-provider gate."""
    return {
        "model": config.model,
        "instructions": prompt.system + "\n" + prompt.rules + ("\n" + FORMAT_RETRY_RULE if format_retry else ""),
        "input": [{"role": "user", "content": prompt.untrusted_data}],
        "text": {"format": {"type": "json_schema", "name": "onboarding_content",
                            "schema": provider_schema_for(prompt)}},
        "reasoning": {"effort": "none"},
        "temperature": config.temperature,
        "max_output_tokens": config.max_output_tokens,
        "stream": False,
    }


class DeepSeekProvider:
    def __init__(self, client: httpx.AsyncClient, config: ProviderConfig):
        if (config.provider != "deepseek" or config.model != DEEPSEEK_MODEL
                or not config.api_key.get_secret_value().strip()):
            raise ProviderFailure("PROVIDER_CONFIGURATION_FAILED")
        self.client, self.config = client, config

    async def generate(self, prompt: PromptPack, *, format_retry: bool = False) -> ProviderResult:
        if prompt.prompt_version != CONTENT_V412 or prompt.response_schema is None:
            raise ProviderFailure("PROVIDER_CONFIGURATION_FAILED")
        payload = deepseek_request_payload(prompt, self.config, format_retry=format_retry)
        encoded = httpx.Request("POST", DEEPSEEK_ENDPOINT, json=payload).content
        if not prompt.within_budget or len(encoded) > MAX_PROVIDER_REQUEST_BYTES:
            raise ProviderFailure("GENERATION_PROJECTION_TOO_LARGE")
        started = perf_counter()
        response = await post_with_deadline(
            self.client, DEEPSEEK_ENDPOINT, deadline_seconds=self.config.timeout_seconds,
            headers={"Authorization": "Bearer " + self.config.api_key.get_secret_value(),
                     "Content-Type": "application/json"}, content=encoded, follow_redirects=False)
        # Never include the response body, request, headers or provider error message in exceptions.
        status = response.status_code
        if status in (401, 403):
            raise ProviderFailure("PROVIDER_AUTH_FAILED")
        if status == 402:
            raise ProviderFailure("PROVIDER_PAYMENT_REQUIRED")
        if status == 429:
            raise ProviderFailure("PROVIDER_RATE_LIMIT", retryable=True,
                                  retry_after_seconds=_bounded_retry_after(response.headers.get("Retry-After")))
        if status == 408:
            raise ProviderFailure("PROVIDER_TIMEOUT", retryable=True)
        if status >= 500:
            raise ProviderFailure("PROVIDER_UNAVAILABLE", retryable=True)
        if status == 413:
            raise ProviderFailure("GENERATION_PROJECTION_TOO_LARGE")
        if not response.is_success:
            raise ProviderFailure("PROVIDER_REQUEST_FAILED")
        if len(response.content) > 2_000_000:
            raise ProviderFailure("PROVIDER_RESPONSE_TOO_LARGE")
        try:
            body = response.json()
            state = body["status"]
            if state == "incomplete":
                details = body.get("incomplete_details") or {}
                if details.get("reason") == "max_output_tokens":
                    raise ProviderFailure("PROVIDER_TRUNCATED")
                raise ProviderFailure("PROVIDER_RESPONSE_REJECTED")
            if state == "failed":
                raise ProviderFailure("PROVIDER_RESPONSE_REJECTED")
            if state != "completed":
                raise ProviderFailure("PROVIDER_INVALID_RESPONSE")
            output = body["output"]
            if not isinstance(output, list):
                raise ValueError("invalid output")
            messages = [item for item in output if isinstance(item, dict)
                        and item.get("type") == "message" and item.get("role") == "assistant"]
            if len(messages) != 1 or messages[0].get("status") != "completed":
                raise ValueError("invalid assistant message")
            parts = messages[0]["content"]
            if (not isinstance(parts, list) or not parts
                    or any(not isinstance(p, dict) or p.get("type") != "output_text"
                           or not isinstance(p.get("text"), str) for p in parts)):
                raise ValueError("invalid final text")
            text = "".join(p["text"] for p in parts)
            if not text.strip():
                raise ValueError("empty final text")
            # Only bounded integer counters survive; untrusted usage strings/metadata are discarded.
            raw_usage = body.get("usage")
            usage = {}
            if isinstance(raw_usage, dict):
                for source, target in (("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens"),
                                       ("total_tokens", "total_tokens")):
                    value = raw_usage.get(source)
                    if type(value) is int and 0 <= value <= 1_000_000_000:
                        usage[target] = value
            return ProviderResult(text=text, finish_reason="STOP", model=self.config.model,
                                  usage=ProviderUsage(**usage) if usage else None,
                                  latency_ms=int((perf_counter() - started) * 1000))
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ProviderFailure("PROVIDER_INVALID_RESPONSE") from None
