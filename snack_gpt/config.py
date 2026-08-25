from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class ConfigurationError(ValueError):
    """Raised when application configuration is invalid."""


@dataclass(frozen=True)
class Settings:
    database_path: Path
    host: str
    port: int

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "Settings":
        port_value = environment.get("SNACK_GPT_PORT", "8000")
        try:
            port = int(port_value)
        except ValueError as error:
            raise ConfigurationError("SNACK_GPT_PORT must be an integer") from error
        if not 1 <= port <= 65535:
            raise ConfigurationError("SNACK_GPT_PORT must be between 1 and 65535")

        return cls(
            database_path=Path(environment.get("SNACK_GPT_DATABASE", "snack-gpt.sqlite3")),
            host=environment.get("SNACK_GPT_HOST", "127.0.0.1"),
            port=port,
        )