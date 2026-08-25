"""Tests for text-to-speech service."""

import pytest

from snack_gpt.services.tts import TTSConfig, TextToSpeechService


class TestTTSConfig:
    """Test TTS configuration."""

    def test_default_config(self) -> None:
        """Test default TTS configuration."""
        config = TTSConfig()
        assert config.model_name == "en_US-lessac-medium"
        assert config.sample_rate == 22050
        assert config.speaker_id == 0
        assert config.length_scale == 1.0

    def test_custom_config(self) -> None:
        """Test custom TTS configuration."""
        config = TTSConfig(
            model_name="en_US-glow_tts-medium",
            sample_rate=44100,
            length_scale=0.9,
        )
        assert config.model_name == "en_US-glow_tts-medium"
        assert config.sample_rate == 44100
        assert config.length_scale == 0.9


class TestTextToSpeechService:
    """Test text-to-speech service."""

    def test_init_default(self) -> None:
        """Test service initialization with defaults."""
        service = TextToSpeechService()
        assert service.config.model_name == "en_US-lessac-medium"

    def test_init_custom_config(self) -> None:
        """Test service initialization with custom config."""
        config = TTSConfig(model_name="test_model")
        service = TextToSpeechService(config)
        assert service.config.model_name == "test_model"

    def test_synthesize_returns_bytes(self) -> None:
        """Test that synthesize returns bytes."""
        service = TextToSpeechService()
        result = service.synthesize("Hello world")
        assert isinstance(result, bytes)

    def test_synthesize_pregenerated_confirmed(self) -> None:
        """Test using pregenerated response for confirmed."""
        service = TextToSpeechService()
        result = service.synthesize("any text", pregenerated_key="confirmed")
        assert isinstance(result, bytes)
        assert result == TextToSpeechService.PREGENERATED_RESPONSES["confirmed"]

    def test_synthesize_pregenerated_pending(self) -> None:
        """Test using pregenerated response for pending."""
        service = TextToSpeechService()
        result = service.synthesize("any text", pregenerated_key="pending")
        assert result == TextToSpeechService.PREGENERATED_RESPONSES["pending"]

    def test_synthesize_confirmation(self) -> None:
        """Test synthesizing confirmation message."""
        service = TextToSpeechService()
        result = service.synthesize_confirmation(["chicken", "rice"], 350)
        assert isinstance(result, bytes)

    def test_synthesize_pending(self) -> None:
        """Test synthesizing pending message."""
        service = TextToSpeechService()
        result = service.synthesize_pending(["chicken quantity", "rice unit"])
        assert isinstance(result, bytes)

    def test_synthesize_clarification_request(self) -> None:
        """Test synthesizing clarification request."""
        service = TextToSpeechService()
        result = service.synthesize_clarification_request("chicken", ["baked chicken", "fried chicken"])
        assert isinstance(result, bytes)

    def test_synthesize_error(self) -> None:
        """Test synthesizing error message."""
        service = TextToSpeechService()
        result = service.synthesize_error("Could not find food")
        assert isinstance(result, bytes)

    def test_synthesize_undo_success(self) -> None:
        """Test synthesizing undo confirmation."""
        service = TextToSpeechService()
        result = service.synthesize_undo_success()
        assert isinstance(result, bytes)
        assert result == TextToSpeechService.PREGENERATED_RESPONSES["undo_success"]


class TestPregenerated:
    """Test pregenerated responses."""

    def test_pregenerated_keys(self) -> None:
        """Test that pregenerated keys are all bytes."""
        for key, value in TextToSpeechService.PREGENERATED_RESPONSES.items():
            assert isinstance(key, str)
            assert isinstance(value, bytes)

    def test_pregenerated_consistency(self) -> None:
        """Test that pregenerated responses are consistent."""
        service = TextToSpeechService()
        result1 = service.synthesize("ignored text", pregenerated_key="confirmed")
        result2 = service.synthesize("different text", pregenerated_key="confirmed")
        assert result1 == result2
