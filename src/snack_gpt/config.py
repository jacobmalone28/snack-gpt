"""Configuration management for Snack GPT."""

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    # Database
    database_url: str = "sqlite:///./snack_gpt.db"
    database_echo: bool = False

    # Server
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False

    # Timezone
    default_timezone: str = "UTC"

    # API endpoints
    usda_api_key: Optional[str] = None
    open_food_facts_api_url: str = "https://world.openfoodfacts.org/api/v2"

    # Constraints
    max_queue_size: int = 1000
    request_timeout_seconds: int = 10
    max_retries: int = 3


settings = Settings()
