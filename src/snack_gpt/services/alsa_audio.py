"""ALSA adapters for Raspberry Pi microphone and speaker devices."""

from subprocess import PIPE, Popen
from typing import BinaryIO, cast

from snack_gpt.services.audio import AudioConfig, AudioInput


class AlsaAudioInput(AudioInput):
    """Read PCM frames from an ALSA capture device via ``arecord``."""

    def __init__(self, device: str = "default", config: AudioConfig | None = None) -> None:
        self.config = config or AudioConfig()
        self.device = device
        self._process: Popen[bytes] | None = None

    def start(self) -> None:
        """Start the long-lived ALSA capture process."""
        if self._process is not None:
            return
        self._process = Popen(
            [
                "arecord",
                "-q",
                "-D",
                self.device,
                "-t",
                "raw",
                "-f",
                "S16_LE",
                "-r",
                str(self.config.sample_rate),
                "-c",
                str(self.config.channels),
                "-B",
                str(self.config.frame_bytes),
            ],
            stdout=PIPE,
            stderr=PIPE,
        )

    def read_frame(self) -> bytes:
        """Read one configured PCM frame."""
        if self._process is None or self._process.stdout is None:
            raise RuntimeError("Audio input is not started")
        stream = cast(BinaryIO, self._process.stdout)
        frame = stream.read(self.config.frame_bytes)
        if len(frame) != self.config.frame_bytes:
            raise RuntimeError("ALSA capture ended before a complete frame was read")
        return frame

    def close(self) -> None:
        """Stop capture and release the ALSA process."""
        if self._process is None:
            return
        self._process.terminate()
        self._process.wait()
        self._process = None

    def __enter__(self) -> "AlsaAudioInput":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class AlsaAudioOutput:
    """Play WAV audio through an ALSA playback device using ``aplay``."""

    def __init__(self, device: str = "default") -> None:
        self.device = device

    def play_wav(self, audio: bytes) -> None:
        """Play complete WAV bytes and raise if the device rejects them."""
        process = Popen(["aplay", "-q", "-D", self.device], stdin=PIPE, stderr=PIPE)
        if process.stdin is None:
            raise RuntimeError("Could not open ALSA playback input")
        process.stdin.write(audio)
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError("ALSA playback failed")
