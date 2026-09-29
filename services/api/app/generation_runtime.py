"""Shared, uncached generation configuration. Resolving it never calls a provider."""
import logging

from .deepseek_provider import DeepSeekEnvironment, DeepSeekProvider
from .generation_content import CONTENT_V412
from .generation_prompt import selected_prompt_version
from .generation_provider import (GeminiEnvironment, GeminiProvider, GroqEnvironment, GroqProvider,
                                  ProviderConfig, ProviderFailure)
from .nararouter_provider import NaraRouterEnvironment, NaraRouterProvider

ENVIRONMENTS = {
    "gemini": GeminiEnvironment,
    "groq": GroqEnvironment,
    "nararouter": NaraRouterEnvironment,
    "deepseek": DeepSeekEnvironment,
}
PROVIDERS = {
    "gemini": GeminiProvider, "groq": GroqProvider,
    "nararouter": NaraRouterProvider, "deepseek": DeepSeekProvider,
}


def resolve_provider_config(provider: str | None = None) -> ProviderConfig:
    """Environment overrides working-directory .env, then class defaults; no fallback."""
    try:
        selection = GeminiEnvironment().ai_provider if provider is None else provider
        environment = ENVIRONMENTS.get(selection)
        if environment is None:
            raise ProviderFailure("PROVIDER_CONFIGURATION_FAILED")
        return environment().adapter_config()
    except ValueError:
        # Pydantic error inputs can contain secrets. Never echo their details.
        raise ProviderFailure("PROVIDER_CONFIGURATION_FAILED") from None


def validate_generation_target(config: ProviderConfig, prompt_version: str) -> None:
    """Reject mismatches BEFORE reservation, claim, telemetry writes or provider calls."""
    if ((prompt_version == CONTENT_V412 and (config.provider, config.model) != ("deepseek", "deepseek-flash"))
            or (config.provider == "deepseek" and prompt_version != CONTENT_V412)):
        raise ProviderFailure("GENERATION_CONFIGURATION_MISMATCH")


def resolve_generation_runtime() -> tuple[ProviderConfig, str]:
    config = resolve_provider_config()
    try:
        version = selected_prompt_version()
    except ValueError:
        raise ProviderFailure("PROVIDER_CONFIGURATION_FAILED") from None
    validate_generation_target(config, version)
    return config, version


def runtime_diagnostic() -> dict[str, str]:
    """Exactly four public, nonsecret fields from the same resolver as readiness/API."""
    config, version = resolve_generation_runtime()
    # Never echo an arbitrary configured model string in diagnostics.
    known_models = {"deepseek-flash", "agnes-2.5-flash", "agnes-3-flash",
                    "gemini-3.8-flash-high", "nemotron-3-ultra-free", "openai/gpt-oss-20b"}
    return {"ai_provider": config.provider,
            "ai_model": config.model if config.model in known_models else "configured",
            "generation_mode": "content-only" if version.startswith("phase4d-content-only/") else "full-plan",
            "prompt_target": version}


def log_runtime_diagnostic() -> None:
    logger = logging.getLogger("skillsprint.generation")
    try:
        data = runtime_diagnostic()
    except ProviderFailure:
        # Other API features can start without AI credentials; generation remains blocked.
        data = dict(ai_provider="unavailable", ai_model="unavailable",
                    generation_mode="unavailable", prompt_target="unavailable")
    for label, name in (("AI provider", "ai_provider"), ("AI model", "ai_model"),
                        ("Generation mode", "generation_mode"), ("Prompt target", "prompt_target")):
        logger.info("%s: %s", label, data[name])
