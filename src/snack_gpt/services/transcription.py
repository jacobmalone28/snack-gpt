"""Hosted transcription boundary for activated voice recordings."""

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class TranscriptionResult:
    """Normalized transcription response."""

    text: str
    language: str | None = None
    duration_seconds: float | None = None


class TranscriptionError(RuntimeError):
    """Raised when hosted transcription cannot complete."""


class HostedTranscriber:
    """Call an OpenAI-compatible transcription endpoint.

    The HTTP client is injectable, allowing deterministic tests and alternate
    hosted providers without coupling the command pipeline to one SDK.
    """

    def __init__(self, endpoint: str, api_key: str, model: str = "whisper-1", client: httpx.AsyncClient | None = None) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self._client = client

    async def transcribe(self, audio: bytes, filename: str = "command.wav", content_type: str = "audio/wav") -> TranscriptionResult:
        """Transcribe activated audio and normalize the provider response."""
        if not audio:
            raise TranscriptionError("Cannot transcribe empty audio")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        data = {"model": self.model}
        files = {"file": (filename, audio, content_type)}
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30.0)
        try:
            try:
                response = await client.post(self.endpoint, headers=headers, data=data, files=files)
                response.raise_for_status()
            except httpx.HTTPError as error:
                raise TranscriptionError(f"Transcription request failed: {error}") from error
            payload: Any = response.json()
            text = payload.get("text") if isinstance(payload, dict) else None
            if not isinstance(text, str) or not text.strip():
                raise TranscriptionError("Transcription response did not contain text")
            language = payload.get("language") if isinstance(payload, dict) else None
            duration = payload.get("duration") if isinstance(payload, dict) else None
            return TranscriptionResult(text=text.strip(), language=language, duration_seconds=duration)
        finally:
            if owns_client:
                await client.aclose()
