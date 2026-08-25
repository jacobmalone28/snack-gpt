"""Tests for ALSA process adapters."""

from io import BytesIO
from unittest.mock import Mock, patch

import pytest

from snack_gpt.services.alsa_audio import AlsaAudioInput, AlsaAudioOutput
from snack_gpt.services.audio import AudioConfig


def test_alsa_input_reads_configured_frame() -> None:
    config = AudioConfig(sample_rate=1000, frame_duration_ms=10)
    process = Mock()
    process.stdout = BytesIO(b"1234567890" * 2)
    with patch("snack_gpt.services.alsa_audio.Popen", return_value=process) as popen:
        audio = AlsaAudioInput("hw:2,0", config)
        audio.start()
        assert audio.read_frame() == b"1234567890" * 2
        popen.assert_called_once()
        assert "hw:2,0" in popen.call_args.args[0]
        audio.close()
        process.terminate.assert_called_once()


def test_alsa_input_requires_start() -> None:
    with pytest.raises(RuntimeError, match="not started"):
        AlsaAudioInput().read_frame()


def test_alsa_input_rejects_short_frame() -> None:
    config = AudioConfig(sample_rate=1000, frame_duration_ms=10)
    process = Mock()
    process.stdout = BytesIO(b"short")
    with patch("snack_gpt.services.alsa_audio.Popen", return_value=process):
        audio = AlsaAudioInput(config=config)
        audio.start()
        with pytest.raises(RuntimeError, match="complete frame"):
            audio.read_frame()


def test_alsa_output_writes_wav() -> None:
    process = Mock()
    process.stdin = Mock()
    process.wait.return_value = 0
    with patch("snack_gpt.services.alsa_audio.Popen", return_value=process) as popen:
        AlsaAudioOutput("hw:1,0").play_wav(b"wav")
        assert popen.call_args.args[0] == ["aplay", "-q", "-D", "hw:1,0"]
        process.stdin.write.assert_called_once_with(b"wav")
        process.stdin.close.assert_called_once()


def test_alsa_output_raises_on_failure() -> None:
    process = Mock()
    process.stdin = Mock()
    process.wait.return_value = 1
    with patch("snack_gpt.services.alsa_audio.Popen", return_value=process):
        with pytest.raises(RuntimeError, match="playback failed"):
            AlsaAudioOutput().play_wav(b"wav")
