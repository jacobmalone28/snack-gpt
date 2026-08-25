"""Hardware-independent audio capture primitives for the voice loop."""

from dataclasses import dataclass
from enum import Enum
from math import sqrt
from typing import Protocol


@dataclass(frozen=True)
class AudioConfig:
    """Audio format and recording thresholds."""

    sample_rate: int = 16_000
    channels: int = 1
    sample_width_bytes: int = 2
    frame_duration_ms: int = 30
    silence_frames_to_stop: int = 20
    speech_rms_threshold: float = 500.0

    @property
    def frame_bytes(self) -> int:
        """Return bytes in one mono PCM frame."""
        return self.sample_rate * self.frame_duration_ms // 1000 * self.sample_width_bytes * self.channels


class RecordingState(str, Enum):
    """State of a wake-activated recording."""

    IDLE = "idle"
    RECORDING = "recording"
    COMPLETE = "complete"


class AudioInput(Protocol):
    """Minimal input boundary implemented by a Pi microphone adapter."""

    def read_frame(self) -> bytes:
        """Read one PCM frame."""


class WakeWordDetector(Protocol):
    """Boundary for local wake-word implementations."""

    def detected(self, frame: bytes) -> bool:
        """Return whether the wake phrase was detected in a frame."""


class RecordingIndicator(Protocol):
    """Boundary for an LED or other local recording indicator."""

    def set_recording(self, active: bool) -> None:
        """Show or hide the recording state."""


class VoiceActivityDetector:
    """Small dependency-free VAD based on PCM frame energy.

    Raspberry Pi deployments can replace this with a WebRTC-backed adapter while
    preserving the same ``is_speech`` contract.
    """

    def __init__(self, config: AudioConfig | None = None) -> None:
        self.config = config or AudioConfig()

    def is_speech(self, frame: bytes) -> bool:
        """Classify signed little-endian PCM16 audio using RMS energy."""
        if len(frame) < 2:
            return False
        samples = [int.from_bytes(frame[index:index + 2], "little", signed=True) for index in range(0, len(frame) - 1, 2)]
        rms = sqrt(sum(sample * sample for sample in samples) / len(samples))
        return rms >= self.config.speech_rms_threshold


class RecordingController:
    """Collect audio after wake activation until sustained silence."""

    def __init__(self, vad: VoiceActivityDetector, config: AudioConfig | None = None) -> None:
        self.config = config or vad.config
        self.vad = vad
        self.state = RecordingState.IDLE
        self._silence_frames = 0
        self._frames: list[bytes] = []

    def activate(self) -> None:
        """Start a fresh recording after a wake-word event."""
        self.state = RecordingState.RECORDING
        self._silence_frames = 0
        self._frames = []

    def accept_frame(self, frame: bytes) -> RecordingState:
        """Consume one frame and return the current recording state."""
        if self.state != RecordingState.RECORDING:
            return self.state
        self._frames.append(frame)
        if self.vad.is_speech(frame):
            self._silence_frames = 0
        else:
            self._silence_frames += 1
            if self._silence_frames >= self.config.silence_frames_to_stop:
                self.state = RecordingState.COMPLETE
        return self.state

    def finish(self) -> bytes:
        """Return captured PCM and reset the controller to idle."""
        audio = b"".join(self._frames)
        self.state = RecordingState.IDLE
        self._silence_frames = 0
        self._frames = []
        return audio

    @property
    def has_audio(self) -> bool:
        """Whether at least one frame has been captured."""
        return bool(self._frames)


class VoiceLoop:
    """Connect wake detection, recording, and the next pipeline stage."""

    def __init__(
        self,
        audio_input: AudioInput,
        wake_detector: WakeWordDetector,
        recorder: RecordingController,
        indicator: RecordingIndicator,
    ) -> None:
        self.audio_input = audio_input
        self.wake_detector = wake_detector
        self.recorder = recorder
        self.indicator = indicator

    def capture_command(self) -> bytes | None:
        """Block until one wake-activated recording is complete.

        Returns ``None`` when the input ends before a wake phrase is detected.
        """
        while True:
            frame = self.audio_input.read_frame()
            if self.recorder.state == RecordingState.IDLE:
                if not self.wake_detector.detected(frame):
                    continue
                self.recorder.activate()
                self.indicator.set_recording(True)

            state = self.recorder.accept_frame(frame)
            if state == RecordingState.COMPLETE:
                self.indicator.set_recording(False)
                return self.recorder.finish()
