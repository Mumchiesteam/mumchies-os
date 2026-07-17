from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Mumchies OS API"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://mumchies:change-me@localhost:5432/mumchies_os"

    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")


settings = Settings()
