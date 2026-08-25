"""Tests for schema-validated command interpretation."""

import httpx
import pytest

from snack_gpt.services.command_interpreter import HostedCommandInterpreter, InterpretationError


@pytest.mark.asyncio
async def test_interpreter_validates_nested_command() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"command": {"command_type": "consume", "confidence": 0.8, "foods": [{"name": "chicken", "quantity": 200, "unit": "grams", "confidence": 0.9}]}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await HostedCommandInterpreter("https://llm.test", "key", "small-model", client).interpret("some chicken")
    await client.aclose()
    assert result.command_type == "consume"
    assert result.foods[0].name == "chicken"


@pytest.mark.asyncio
async def test_interpreter_rejects_nutrition_invented_as_unknown_field() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"command_type": "consume", "confidence": 1, "foods": [{"name": "chicken", "quantity": 200, "unit": "grams", "confidence": 1, "calories": 400}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(InterpretationError, match="validation"):
        await HostedCommandInterpreter("https://llm.test", "key", "small-model", client).interpret("chicken")
    await client.aclose()


@pytest.mark.asyncio
async def test_interpreter_rejects_invalid_command_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"command_type": "calculate", "confidence": 1, "foods": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(InterpretationError, match="validation"):
        await HostedCommandInterpreter("https://llm.test", "key", "small-model", client).interpret("what")
    await client.aclose()


@pytest.mark.asyncio
async def test_interpreter_rejects_empty_transcript() -> None:
    with pytest.raises(InterpretationError, match="empty transcript"):
        await HostedCommandInterpreter("https://llm.test", "key", "small-model").interpret(" ")
