"""Tests for hardware-independent audio primitives."""

from snack_gpt.services.audio import AudioConfig, RecordingController, RecordingState, VoiceActivityDetector, VoiceLoop


def pcm16(value: int, samples: int = 10) -> bytes:
    """Build a small signed PCM16 frame."""
    return b"".join(value.to_bytes(2, "little", signed=True) for _ in range(samples))


def test_audio_config_frame_bytes() -> None:
    config = AudioConfig(sample_rate=16_000, frame_duration_ms=30)
    assert config.frame_bytes == 960


def test_vad_distinguishes_silence_and_speech() -> None:
    vad = VoiceActivityDetector(AudioConfig(speech_rms_threshold=100))
    assert not vad.is_speech(pcm16(0))
    assert vad.is_speech(pcm16(1000))


def test_recording_stops_after_sustained_silence() -> None:
    config = AudioConfig(silence_frames_to_stop=2, speech_rms_threshold=100)
    controller = RecordingController(VoiceActivityDetector(config), config)
    controller.activate()
    assert controller.state == RecordingState.RECORDING
    speech = pcm16(1000)
    silence = pcm16(0)
    controller.accept_frame(speech)
    controller.accept_frame(silence)
    assert controller.state == RecordingState.RECORDING
    controller.accept_frame(silence)
    assert controller.state == RecordingState.COMPLETE
    assert controller.finish() == speech + silence + silence
    assert controller.state == RecordingState.IDLE


def test_frames_while_idle_are_ignored() -> None:
    controller = RecordingController(VoiceActivityDetector())
    frame = pcm16(1000)
    assert controller.accept_frame(frame) == RecordingState.IDLE
    assert not controller.has_audio


class FakeInput:
    def __init__(self, frames: list[bytes]) -> None:
        self.frames = iter(frames)

    def read_frame(self) -> bytes:
        return next(self.frames)


class FakeWakeWord:
    def __init__(self) -> None:
        self.calls = 0

    def detected(self, frame: bytes) -> bool:
        self.calls += 1
        return self.calls == 2


class FakeIndicator:
    def __init__(self) -> None:
        self.states: list[bool] = []

    def set_recording(self, active: bool) -> None:
        self.states.append(active)


def test_voice_loop_waits_for_wake_and_toggles_indicator() -> None:
    config = AudioConfig(silence_frames_to_stop=1, speech_rms_threshold=100)
    speech = pcm16(1000)
    silence = pcm16(0)
    indicator = FakeIndicator()
    audio = VoiceLoop(
        FakeInput([silence, speech, silence]),
        FakeWakeWord(),
        RecordingController(VoiceActivityDetector(config), config),
        indicator,
    )
    assert audio.capture_command() == speech + silence
    assert indicator.states == [True, False]
