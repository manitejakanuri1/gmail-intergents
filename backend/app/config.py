"""Application configuration loaded from environment / .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Google OAuth / Gmail
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    # Database
    database_url: str = ""
    supabase_url: str = ""
    supabase_service_role_key: str = ""

    # AI
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    nvidia_nim_api_key: str = ""
    nim_embed_model: str = "nvidia/nv-embedqa-e5-v5"
    nim_base_url: str = "https://integrate.api.nvidia.com/v1"

    # Infra
    redis_url: str = "redis://localhost:6379"

    # Security
    app_jwt_secret: str = "dev-secret-change-me"
    token_encryption_key: str = ""

    # CORS
    frontend_origin: str = "http://localhost:5173"

    # Gmail OAuth scopes
    @property
    def google_scopes(self) -> list[str]:
        return [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.modify",
            "openid",
            "email",
            "profile",
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
