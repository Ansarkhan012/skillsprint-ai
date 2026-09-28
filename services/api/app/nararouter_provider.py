"""Backend-only OpenAI-compatible transport. No retrieval or decision logic."""

import logging
import re
from typing import Literal
from time import perf_counter

import httpx
from pydantic import ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .generation_prompt import FORMAT_RETRY_RULE, MAX_PROVIDER_REQUEST_BYTES, PromptPack, current_provider_schema
from .generation_provider import (ProviderConfig, ProviderFailure, json_schema_response_format,
                                  ProviderResult, ProviderUsage, _bounded_retry_after, post_with_deadline)


MODEL_IDENTIFIER = re.compile(r"[A-Za-z0-9_./-]{1,100}", re.ASCII)
_LOG = logging.getLogger(__name__)
_SAFE_UPSTREAM_CODES = frozenset({
    "bad_request", "forbidden", "invalid_api_key", "invalid_request", "invalid_request_error",
    "insufficient_balance", "insufficient_quota", "model_not_found", "model_not_supported",
    "not_found", "payment_required", "rate_limit_exceeded", "unsupported_parameter", "unsupported_response_format",
    "validation_error", "context_length_exceeded",
})
_SAFE_ERROR_HINTS = (
    ("response_format", "response_format"), ("json_object", "json_object"),
    ("max_completion_tokens", "max_completion_tokens"), ("max_tokens", "max_tokens"),
    ("temperature", "temperature"), ("model", "model"),
    ("quota", "quota"), ("balance", "balance"),
)
OUTPUT_INSTRUCTIONS = (
    "Return exactly one JSON object, with no markdown, code fences, commentary, or reasoning text. "
    "Use concise strings and include every required onboarding-plan/1.0.0 field. "
    "Keep all applicable requirements and their source references traceable."
)


class NaraRouterConfig(ProviderConfig):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    base_url: str = Field(repr=False)
    # OpenAI-compatible reasoning control; None omits the parameter entirely.
    reasoning_effort: Literal["none", "low", "medium", "high"] | None = None

    @field_validator("base_url")
    @classmethod
    def safe_base_url(cls, value: str) -> str:
        try:
            url = httpx.URL(value)
        except httpx.InvalidURL:
            raise ValueError("INVALID_PROVIDER_BASE_URL") from None
        if (value != value.strip() or any(ord(c) < 33 or ord(c) > 126 for c in value)
                or url.scheme != "https" or not url.host or url.userinfo
                or url.query or url.fragment or "?" in value or "#" in value):
            raise ValueError("INVALID_PROVIDER_BASE_URL")
        return str(url).rstrip("/")

    @field_validator("model")
    @classmethod
    def bounded_model(cls, value: str) -> str:
        if MODEL_IDENTIFIER.fullmatch(value) is None:
            raise ValueError("INVALID_PROVIDER_MODEL")
        return value

    @field_validator("api_key")
    @classmethod
    def nonempty_key(cls, value: SecretStr) -> SecretStr:
        key = value.get_secret_value()
        if not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise ValueError("INVALID_PROVIDER_KEY")
        return value


class NaraRouterEnvironment(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    nararouter_api_key: SecretStr | None = Field(default=None, repr=False)
    nararouter_base_url: str | None = Field(default=None, repr=False)
    nararouter_model: str | None = None
    nararouter_timeout_seconds: float = 30
    nararouter_max_output_tokens: int = 8192
    nararouter_temperature: float = 0.1
    # Opt-in. Live tests: "none" made free models fast but return plans with no modules.
    nararouter_reasoning_effort: str | None = None

    def adapter_config(self) -> NaraRouterConfig:
        if not self.nararouter_api_key or not self.nararouter_base_url or not self.nararouter_model:
            raise ProviderFailure("PROVIDER_CONFIGURATION_FAILED")
        try:
            return NaraRouterConfig(provider="nararouter", model=self.nararouter_model,
                api_key=self.nararouter_api_key, base_url=self.nararouter_base_url,
                timeout_seconds=self.nararouter_timeout_seconds,
                max_output_tokens=self.nararouter_max_output_tokens,
                temperature=self.nararouter_temperature,
                reasoning_effort=self.nararouter_reasoning_effort or None)
        except ValueError:
            raise ProviderFailure("PROVIDER_CONFIGURATION_FAILED") from None


def nararouter_request_payload(prompt: PromptPack, config: NaraRouterConfig,
                              *, format_retry: bool = False) -> dict:
    """Chat-completions envelope; model entitlement must be discovered separately."""
    system = prompt.system + "\n" + prompt.rules + "\n" + OUTPUT_INSTRUCTIONS
    if format_retry:
        system += "\n" + FORMAT_RETRY_RULE
    return {"model": config.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt.untrusted_data}],
            "response_format": {"type": "json_object"}, "stream": False,
            "temperature": config.temperature, "max_tokens": config.max_output_tokens,
            **({"reasoning_effort": config.reasoning_effort} if config.reasoning_effort else {})}


def _usage(value: object) -> ProviderUsage | None:
    if not isinstance(value, dict):
        return None
    accepted = {name: value[name] for name in ProviderUsage.model_fields
                if type(value.get(name)) is int and 0 <= value[name] <= 1_000_000_000}
    return ProviderUsage(**accepted) if accepted else None


def _safe_error_metadata(response: httpx.Response) -> tuple[str, str]:
    """Allowlisted diagnostics only; never return or log provider-supplied prose."""
    if len(response.content) > 4096:
        return "unknown", "none"
    try:
        body = response.json()
    except ValueError:
        return "unknown", "none"
    if not isinstance(body, dict) or not isinstance(body.get("error"), dict):
        return "unknown", "none"
    error = body["error"]
    code = next((value for value in (error.get("code"), error.get("type"))
                 if isinstance(value, str) and value in _SAFE_UPSTREAM_CODES), "unknown")
    message = error.get("message")
    hint = next((label for marker, label in _SAFE_ERROR_HINTS
                 if isinstance(message, str) and marker in message.lower()), "none")
    return code, hint


class NaraRouterProvider:
    def __init__(self, client: httpx.AsyncClient, config: NaraRouterConfig):
        if config.provider != "nararouter":
            raise ProviderFailure("PROVIDER_CONFIGURATION_FAILED")
        self.client = client
        self.config = config

    async def generate(self, prompt: PromptPack, *, format_retry: bool = False) -> ProviderResult:
        payload = nararouter_request_payload(prompt, self.config, format_retry=format_retry)
        url = self.config.base_url + "/chat/completions"
        encoded = httpx.Request("POST", url, json=payload).content
        if not prompt.within_budget or len(encoded) > MAX_PROVIDER_REQUEST_BYTES:
            raise ProviderFailure("GENERATION_PROJECTION_TOO_LARGE")
        encoded = httpx.Request("POST", url, json={
            **payload, "response_format": json_schema_response_format(current_provider_schema())}).content
        started = perf_counter()
        response = await post_with_deadline(self.client, url, deadline_seconds=self.config.timeout_seconds,
            content=encoded, follow_redirects=False,
            headers={"Authorization": "Bearer " + self.config.api_key.get_secret_value(),
                     "Content-Type": "application/json"})
        latency = max(0, int((perf_counter() - started) * 1000))
        if not response.is_success:
            safe_code, safe_hint = _safe_error_metadata(response)
            _LOG.warning("nararouter_http_rejected provider=nararouter model=%s upstream_status=%d "
                         "upstream_code=%s upstream_hint=%s",
                         self.config.model, response.status_code, safe_code, safe_hint)
        if response.status_code == 401:
            raise ProviderFailure("PROVIDER_AUTH_FAILED")
        if response.status_code == 402:
            raise ProviderFailure("PROVIDER_PAYMENT_REQUIRED")
        if response.status_code == 403:
            raise ProviderFailure("PROVIDER_ACCESS_DENIED")
        if response.status_code == 408:
            raise ProviderFailure("PROVIDER_TIMEOUT", retryable=True)
        if response.status_code == 413:
            raise ProviderFailure("GENERATION_PROJECTION_TOO_LARGE")
        if response.status_code == 429:
            delay = _bounded_retry_after(response.headers.get("Retry-After"))
            raise ProviderFailure("PROVIDER_RATE_LIMIT", retryable=True, retry_after_seconds=delay)
        if response.status_code >= 500:
            raise ProviderFailure("PROVIDER_UNAVAILABLE", retryable=True)
        if not response.is_success:
            raise ProviderFailure("PROVIDER_REQUEST_FAILED")
        if len(response.content) > 2_000_000:
            raise ProviderFailure("PROVIDER_RESPONSE_TOO_LARGE")
        try:
            body = response.json()
            choices = body["choices"]
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError("choice count")
            choice = choices[0]
            if choice["finish_reason"] == "length":
                raise ProviderFailure("PROVIDER_TRUNCATED")
            if choice["finish_reason"] != "stop":
                raise ProviderFailure("PROVIDER_RESPONSE_REJECTED")
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty or invalid content")
            model = body.get("model")
            if (not isinstance(model, str) or MODEL_IDENTIFIER.fullmatch(model) is None
                    or self.config.api_key.get_secret_value() in model):
                model = None
            return ProviderResult(text=content, finish_reason="STOP", model=model,
                                  usage=_usage(body.get("usage")), latency_ms=latency)
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ProviderFailure("PROVIDER_INVALID_RESPONSE") from None
