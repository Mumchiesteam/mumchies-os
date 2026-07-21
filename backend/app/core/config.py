from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    app_name: str = "Mumchies OS API"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://mumchies:change-me@localhost:5432/mumchies_os"
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

    # Load both the backend-local file and the repo-root file explicitly so
    # the server behaves the same regardless of its working directory.
    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"), extra="ignore")


settings = Settings()
