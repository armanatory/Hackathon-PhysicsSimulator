"""Application configuration using environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Credentials come from the shared .env in the repository root. A .env inside quiet-office/
# is read after it and wins, in case this project needs its own keys.
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # quiet-office/
REPO_ROOT = PROJECT_ROOT.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(PROJECT_ROOT / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Allsolve API credentials
    qs_access_key: str = ""
    qs_secret_key: str = ""
    qs_host: str = "https://allsolve.quanscient.com"

    # Optional: OpenAI key for the plain-language explanation of a run
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Optional: OpenAI key for the plain-language explanation of a run
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Application settings
    app_name: str = "QuietOffice"
    debug: bool = False

    # Keep the Allsolve project after a run so it can be opened in the browser.
    keep_projects: bool = True

    @property
    def has_credentials(self) -> bool:
        return bool(self.qs_access_key and self.qs_secret_key)


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
