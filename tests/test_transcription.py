"""Tests for hosted transcription integration."""

import httpx
import pytest

from snack_gpt.services.transcription import HostedTranscriber, TranscriptionError


@pytest.mark.asyncio
async def test_transcribe_normalizes_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"text": "I ate chicken", "language": "en", "duration": 1.2})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await HostedTranscriber("https://stt.test/transcribe", "test-key", client=client).transcribe(b"wav")
    await client.aclose()
    assert result.text == "I ate chicken"
    assert result.language == "en"
    assert result.duration_seconds == 1.2


@pytest.mark.asyncio
async def test_empty_audio_is_rejected() -> None:
    with pytest.raises(TranscriptionError, match="empty audio"):
        await HostedTranscriber("https://stt.test/transcribe", "test-key").transcribe(b"")


@pytest.mark.asyncio
async def test_http_failure_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(TranscriptionError, match="request failed"):
        await HostedTranscriber("https://stt.test/transcribe", "test-key", client=client).transcribe(b"wav")
    await client.aclose()


@pytest.mark.asyncio
async def test_missing_text_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": " "})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(TranscriptionError, match="did not contain text"):
        await HostedTranscriber("https://stt.test/transcribe", "test-key", client=client).transcribe(b"wav")
    await client.aclose()
