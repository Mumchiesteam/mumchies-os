from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    app_name: str = "Mumchies OS API"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://mumchies:change-me@localhost:5432/mumchies_os"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    data_dir: Path = BACKEND_DIR / "data"
    auth_enabled: bool = True
    auth_admin_username: str | None = None
    auth_admin_password_hash: str | None = None
    auth_session_secret: str | None = None
    auth_session_minutes: int = 480
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"
    auth_cookie_name: str = "mumchies_session"
    shopify_store: str | None = None
    shopify_client_id: str | None = None
    shopify_client_secret: str | None = None
    shopify_api_version: str | None = None
    shopify_notify_customer_on_fulfillment: bool = True
    shiprocket_email: str | None = None
    shiprocket_password: str | None = None
    shiprocket_pickup: str | None = None
    delhivery_token: str | None = None
    delhivery_pickup: str | None = None
    shadowfax_token: str | None = None

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        """Accept provider-style PostgreSQL URLs while using the installed psycopg driver."""
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]
        return value

    # Load both the backend-local file and the repo-root file explicitly so
    # the server behaves the same regardless of its working directory.
    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"), extra="ignore")


settings = Settings()
