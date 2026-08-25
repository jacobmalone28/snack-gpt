"""Schema-validated hosted interpretation for ambiguous commands."""

from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError


class InterpretedFood(BaseModel):
    """Food description extracted by the language model."""

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=200)
    quantity: float = Field(gt=0, le=100_000)
    unit: str = Field(min_length=1, max_length=32)
    confidence: float = Field(ge=0, le=1)


class InterpretedCommand(BaseModel):
    """Allowed model output for command interpretation."""

    model_config = {"extra": "forbid"}

    command_type: str = Field(pattern="^(consume|draft|undo|clarify)$")
    foods: list[InterpretedFood] = Field(default_factory=list, max_length=20)
    confidence: float = Field(ge=0, le=1)
    clarification_reason: str | None = Field(default=None, max_length=500)


class InterpretationError(RuntimeError):
    """Raised when interpretation fails or violates the command schema."""


class HostedCommandInterpreter:
    """Call a hosted JSON endpoint and validate its constrained response."""

    def __init__(self, endpoint: str, api_key: str, model: str, client: httpx.AsyncClient | None = None) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self._client = client

    async def interpret(self, transcript: str) -> InterpretedCommand:
        """Interpret a transcript into a validated command shape."""
        if not transcript.strip():
            raise InterpretationError("Cannot interpret an empty transcript")
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30.0)
        try:
            try:
                response = await client.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "transcript": transcript, "response_format": "json"},
                )
                response.raise_for_status()
                payload: Any = response.json()
            except httpx.HTTPError as error:
                raise InterpretationError(f"Interpreter request failed: {error}") from error
            data = payload.get("command") if isinstance(payload, dict) and "command" in payload else payload
            try:
                return InterpretedCommand.model_validate(data)
            except (ValidationError, TypeError) as error:
                raise InterpretationError("Interpreter response failed command validation") from error
        finally:
            if owns_client:
                await client.aclose()
