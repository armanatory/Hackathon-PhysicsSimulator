"""Application configuration using environment variables."""

import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Allsolve API credentials
    qs_access_key: str = ""
    qs_secret_key: str = ""
    qs_host: str = "https://allsolve.quanscient.com"

    # Application settings
    app_name: str = "Beer Cooling Simulator"
    debug: bool = False

    # Simulation defaults
    default_simulation_duration_minutes: int = 30
    max_simulation_duration_minutes: int = 120

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

