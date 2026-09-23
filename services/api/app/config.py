from functools import lru_cache

from pydantic import Field, HttpUrl, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: HttpUrl
    supabase_anon_key: str = Field(min_length=1)
    supabase_jwt_audience: str = "authenticated"
    web_origin: str = "http://localhost:3000"
    environment: str = "development"

    @model_validator(mode="after")
    def validate_origin(self) -> "Settings":
        if self.environment == "production" and not self.web_origin.startswith("https://"):
            raise ValueError("WEB_ORIGIN must use HTTPS in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
