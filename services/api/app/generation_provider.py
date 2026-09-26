"""Provider-neutral result/error types and backend-only generation adapters."""

from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .generation_prompt import FORMAT_RETRY_RULE, MAX_PROVIDER_REQUEST_BYTES, PromptPack


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: str = "gemini"
    model: str = Field(pattern=r"^[A-Za-z0-9_./-]{1,100}$")
    api_key: SecretStr = Field(repr=False)
    timeout_seconds: float = Field(default=20, ge=1, le=60)
    max_output_tokens: int = Field(default=8192, ge=256, le=65536)
    temperature: float = Field(default=0.1, ge=0, le=1)


class GeminiEnvironment(BaseSettings):
    """Optional at application startup; required only when a Gemini adapter is constructed."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    ai_provider: str = "gemini"
    gemini_model: str | None = None
    gemini_api_key: SecretStr | None = Field(default=None, repr=False)
    gemini_timeout_seconds: float = 20
    gemini_max_output_tokens: int = 8192
    gemini_temperature: float = 0.1

    def adapter_config(self) -> ProviderConfig:
        if self.ai_provider != "gemini" or not self.gemini_model or not self.gemini_api_key:
            raise ProviderFailure("PROVIDER_CONFIGURATION_FAILED")
        try:
            return ProviderConfig(provider="gemini", model=self.gemini_model, api_key=self.gemini_api_key,
                                  timeout_seconds=self.gemini_timeout_seconds,
                                  max_output_tokens=self.gemini_max_output_tokens,
                                  temperature=self.gemini_temperature)
        except ValueError:
            raise ProviderFailure("PROVIDER_CONFIGURATION_FAILED") from None


class GroqEnvironment(BaseSettings):
    """Backend-only Groq settings; the key is required only for Groq generation."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    groq_api_key: SecretStr | None = Field(default=None, repr=False)
    groq_model: str = "openai/gpt-oss-20b"
    groq_timeout_seconds: float = 30
    groq_max_output_tokens: int = 8192
    groq_temperature: float = 0.1

    def adapter_config(self) -> ProviderConfig:
        if not self.groq_api_key:
            raise ProviderFailure("PROVIDER_CONFIGURATION_FAILED")
        try:
            return ProviderConfig(provider="groq", model=self.groq_model, api_key=self.groq_api_key,
                                  timeout_seconds=self.groq_timeout_seconds,
                                  max_output_tokens=self.groq_max_output_tokens,
                                  temperature=self.groq_temperature)
        except ValueError:
            raise ProviderFailure("PROVIDER_CONFIGURATION_FAILED") from None


class ProviderResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    text: str
    finish_reason: str
    model: str | None = None


class ProviderFailure(Exception):
    def __init__(self, code: str, *, retryable: bool = False, retry_after_seconds: float | None = None):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


def _bounded_retry_after(value: str | None) -> float | None:
    """Only a short numeric Retry-After can authorize one delayed 429 retry."""
    if value is None or not value.isascii() or not value.replace(".", "", 1).isdigit():
        return None
    seconds = float(value)
    return seconds if 0.5 <= seconds <= 2.0 else None


class GenerationProvider(Protocol):
    async def generate(self, prompt: PromptPack, *, format_retry: bool = False) -> ProviderResult: ...


class GeminiProvider:
    """No SDK objects escape; client is injected, never created or called on import."""

    def __init__(self, client: httpx.AsyncClient, config: ProviderConfig):
        if config.provider != "gemini":
            raise ProviderFailure("PROVIDER_CONFIGURATION_FAILED")
        self.client = client
        self.config = config

    async def generate(self, prompt: PromptPack, *, format_retry: bool = False) -> ProviderResult:
        key = self.config.api_key.get_secret_value()
        if not key:
            raise ProviderFailure("PROVIDER_CONFIGURATION_FAILED")
        payload = {
            "systemInstruction": {"parts": [{"text": prompt.system + "\n" + prompt.rules}]},
            "contents": [{"role": "user", "parts": [{"text": prompt.untrusted_data}]}],
            "generationConfig": {"responseMimeType": "application/json",
                                 "temperature": self.config.temperature,
                                 "maxOutputTokens": self.config.max_output_tokens},
        }
        if format_retry:
            payload["systemInstruction"]["parts"][0]["text"] += "\n" + FORMAT_RETRY_RULE
        try:
            response = await self.client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.config.model}:generateContent",
                headers={"x-goog-api-key": key}, json=payload, timeout=self.config.timeout_seconds)
        except httpx.TimeoutException:
            raise ProviderFailure("PROVIDER_TIMEOUT", retryable=True) from None
        except httpx.TransportError:
            raise ProviderFailure("PROVIDER_UNAVAILABLE", retryable=True) from None
        if response.status_code == 429:
            delay = _bounded_retry_after(response.headers.get("Retry-After"))
            raise ProviderFailure("PROVIDER_RATE_LIMIT", retryable=delay is not None,
                                  retry_after_seconds=delay)
        if response.status_code in (401, 403):
            raise ProviderFailure("PROVIDER_AUTH_FAILED")
        if response.status_code >= 500:
            raise ProviderFailure("PROVIDER_UNAVAILABLE", retryable=True)
        if not response.is_success:
            raise ProviderFailure("PROVIDER_REQUEST_FAILED")
        if len(response.content) > 2_000_000:
            raise ProviderFailure("PROVIDER_RESPONSE_TOO_LARGE")
        try:
            body = response.json()
            candidates = body.get("candidates", [])
            if len(candidates) != 1:
                raise ValueError("candidate count")
            candidate = candidates[0]
            finish = candidate.get("finishReason", "")
            if finish == "MAX_TOKENS":
                raise ProviderFailure("PROVIDER_TRUNCATED")
            if finish != "STOP":
                raise ProviderFailure("PROVIDER_RESPONSE_REJECTED")
            parts = candidate["content"]["parts"]
            if len(parts) != 1 or not isinstance(parts[0].get("text"), str):
                raise ValueError("content shape")
            return ProviderResult(text=parts[0]["text"], finish_reason=finish,
                                  model=body.get("modelVersion"))
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ProviderFailure("PROVIDER_INVALID_RESPONSE") from None


def groq_request_payload(prompt: PromptPack, config: ProviderConfig, *, format_retry: bool = False) -> dict:
    """Single pure request constructor, also used by offline size/contract tests."""
    system = prompt.system + "\n" + prompt.rules
    if format_retry:
        system += "\n" + FORMAT_RETRY_RULE
    return {
        "model": config.model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt.untrusted_data}],
        "response_format": {"type": "json_object"},
        "temperature": config.temperature,
        "max_completion_tokens": config.max_output_tokens,
        "stream": False,
    }


class GroqProvider:
    """OpenAI-compatible Groq chat adapter; reuses the app's pooled HTTP client."""

    def __init__(self, client: httpx.AsyncClient, config: ProviderConfig):
        if config.provider != "groq":
            raise ProviderFailure("PROVIDER_CONFIGURATION_FAILED")
        self.client = client
        self.config = config

    async def generate(self, prompt: PromptPack, *, format_retry: bool = False) -> ProviderResult:
        key = self.config.api_key.get_secret_value()
        if not key:
            raise ProviderFailure("PROVIDER_CONFIGURATION_FAILED")
        payload = groq_request_payload(prompt, self.config, format_retry=format_retry)
        # HTTPX's own JSON encoder measures the final body (including escaping and
        # retry instructions), not just concatenated prompt text. This does no I/O.
        encoded = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions",
                                json=payload).content
        if len(encoded) > MAX_PROVIDER_REQUEST_BYTES:
            raise ProviderFailure("GENERATION_PROJECTION_TOO_LARGE")
        try:
            response = await self.client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, content=encoded,
                timeout=self.config.timeout_seconds)
        except httpx.TimeoutException:
            raise ProviderFailure("PROVIDER_TIMEOUT", retryable=True) from None
        except httpx.TransportError:
            raise ProviderFailure("PROVIDER_UNAVAILABLE", retryable=True) from None
        if response.status_code == 429:
            delay = _bounded_retry_after(response.headers.get("Retry-After"))
            raise ProviderFailure("PROVIDER_RATE_LIMIT", retryable=delay is not None,
                                  retry_after_seconds=delay)
        if response.status_code in (401, 403):
            raise ProviderFailure("PROVIDER_AUTH_FAILED")
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
            finish = choice["finish_reason"]
            if finish == "length":
                raise ProviderFailure("PROVIDER_TRUNCATED")
            if finish != "stop":
                raise ProviderFailure("PROVIDER_RESPONSE_REJECTED")
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("content shape")
            return ProviderResult(text=content, finish_reason="STOP", model=body.get("model"))
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ProviderFailure("PROVIDER_INVALID_RESPONSE") from None
