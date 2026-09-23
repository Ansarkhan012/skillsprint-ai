from functools import lru_cache

from pydantic import Field, HttpUrl, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: HttpUrl
    supabase_anon_key: str = Field(min_length=1)
    supabase_service_role_key: str | None = None
    supabase_jwt_audience: str = "authenticated"
    web_origin: str = "http://localhost:3000"
    environment: str = "development"
    max_upload_bytes: int = Field(default=15 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    document_chunk_chars: int = Field(default=1200, ge=200, le=10000)
    document_chunk_overlap: int = Field(default=150, ge=0, le=2000)

    @model_validator(mode="after")
    def validate_origin(self) -> "Settings":
        if self.environment == "production" and not self.web_origin.startswith("https://"):
            raise ValueError("WEB_ORIGIN must use HTTPS in production")
        if self.document_chunk_overlap >= self.document_chunk_chars:
            raise ValueError("DOCUMENT_CHUNK_OVERLAP must be smaller than DOCUMENT_CHUNK_CHARS")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
