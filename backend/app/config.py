"""App configuration. All secrets come from environment / .env — never hardcode."""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    suma_api_key: str = "change-me-local-dev-key"
    anthropic_api_key: str = ""
    database_url: str = "sqlite:///./suma.db"
    upload_dir: str = "./uploads"
    tax_set_aside_pct: float = 0.25
    # Extractions at or above this confidence auto-post; below, they wait for review.
    confidence_gate: float = 0.85


settings = Settings()
Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
