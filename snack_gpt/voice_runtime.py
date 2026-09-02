from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import subprocess
import tempfile
import time
from typing import cast

from snack_gpt.storage import ConsumptionEvent
from snack_gpt.voice import CapturedSpeech, VoiceProcessingError, VoiceProcessingTimeout


CAPTURE_TIMEOUT_SECONDS = 15.0
CAPTURE_SILENCE_SECONDS = 1.0
FEEDBACK_TIMEOUT_SECONDS = 10.0
REQUIRED_COMMANDS = {
    "wake_capture",
    "wake_detection",
    "speech_capture",
    "transcription",
    "extraction",
    "success_sound",
    "error_sound",
    "speech_synthesis",
    "play_speech",
}
RunCommand = Callable[[Sequence[str], float | None], None]


class VoiceRuntimeError(VoiceProcessingError):
    pass


@dataclass(frozen=True)
class VoiceManifest:
    commands: Mapping[str, Sequence[str]]
    memory_directory: Path


def load_voice_manifest(path: Path) -> VoiceManifest:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VoiceRuntimeError(f"Cannot load voice manifest: {error}") from error
    if not isinstance(value, dict):
        raise VoiceRuntimeError("Voice manifest must contain a JSON object.")
    manifest = cast(dict[object, object], value)
    memory_directory_value = manifest.get("memory_directory")
    if not isinstance(memory_directory_value, str) or not memory_directory_value:
        raise VoiceRuntimeError("Voice manifest must contain memory_directory.")
    memory_directory = Path(memory_directory_value)
    if not memory_directory.is_dir():
        raise VoiceRuntimeError("Voice manifest memory_directory must be an existing directory.")
    commands_value = manifest.get("commands")
    if not isinstance(commands_value, dict):
        raise VoiceRuntimeError("Voice manifest must contain a commands object.")
    raw_commands = cast(dict[object, object], commands_value)
    commands: dict[str, tuple[str, ...]] = {}
    for name, command_value in raw_commands.items():
        if not isinstance(name, str) or not isinstance(command_value, list):
            raise VoiceRuntimeError("Voice commands must be named lists of strings.")
        command_parts = cast(list[object], command_value)
        if not command_parts or not all(isinstance(part, str) for part in command_parts):
            raise VoiceRuntimeError(f"Voice command {name} must be a non-empty list of strings.")
        commands[name] = tuple(cast(list[str], command_parts))
    missing = REQUIRED_COMMANDS - commands.keys()
    if missing:
        raise VoiceRuntimeError(f"Voice manifest is missing commands: {', '.join(sorted(missing))}.")
    return VoiceManifest(commands, memory_directory)


class CommandVoiceRuntime:
    def __init__(
        self,
        commands: Mapping[str, Sequence[str]],
        memory_directory: Path,
        *,
        run_command: RunCommand | None = None,
        today: Callable[[], date] = date.today,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._commands = commands
        self._memory_directory = memory_directory
        self._run_command = run_command or _run_command
        self._today = today
        self._monotonic = monotonic
        self._artifacts: tempfile.TemporaryDirectory[str] | None = None
        self._extraction: object | None = None

    def wait_for_wake_and_capture(self) -> CapturedSpeech:
        self._cleanup()
        while True:
            with tempfile.TemporaryDirectory(
                prefix="snack-gpt-wake-",
                dir=self._memory_directory,
            ) as directory:
                root = Path(directory)
                wake_audio = root / "wake.wav"
                wake_result = root / "wake.json"
                self._run("wake_capture", {"audio": str(wake_audio)})
                self._run(
                    "wake_detection",
                    {"audio": str(wake_audio), "output": str(wake_result)},
                )
                try:
                    result: object = json.loads(wake_result.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as error:
                    raise VoiceRuntimeError("Wake detection produced invalid output.") from error
                if not isinstance(result, dict) or cast(dict[object, object], result).get("detected") is not True:
                    continue
                break

        self._artifacts = tempfile.TemporaryDirectory(
            prefix="snack-gpt-report-",
            dir=self._memory_directory,
        )
        audio_path = Path(self._artifacts.name) / "report.wav"
        started_on = self._today()
        self._run(
            "speech_capture",
            {
                "audio": str(audio_path),
                "silence_seconds": str(CAPTURE_SILENCE_SECONDS),
            },
            timeout=CAPTURE_TIMEOUT_SECONDS,
        )
        try:
            audio = audio_path.read_bytes()
        except OSError as error:
            self._cleanup()
            raise VoiceRuntimeError("Speech capture failed.") from error
        if not audio:
            self._cleanup()
            raise VoiceRuntimeError("Speech capture produced no audio.")
        return CapturedSpeech(audio, started_on)

    def transcribe(self, audio: bytes, deadline: float) -> str:
        root = self._artifact_root()
        audio_path = root / "report.wav"
        transcript_path = root / "transcript.txt"
        try:
            audio_path.write_bytes(audio)
        except OSError as error:
            raise VoiceRuntimeError("Transcription failed.") from error
        self._run(
            "transcription",
            {"audio": str(audio_path), "output": str(transcript_path)},
            deadline=deadline,
        )
        try:
            transcript = transcript_path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise VoiceRuntimeError("Transcription failed.") from error
        if not transcript:
            raise VoiceRuntimeError("I could not understand the speech.")
        return transcript

    def extract(self, transcript: str, deadline: float) -> object:
        root = self._artifact_root()
        transcript_path = root / "transcript.txt"
        extraction_path = root / "extraction.json"
        try:
            transcript_path.write_text(transcript, encoding="utf-8")
        except OSError as error:
            raise VoiceRuntimeError("Food extraction failed.") from error
        self._run(
            "extraction",
            {"transcript": str(transcript_path), "output": str(extraction_path)},
            deadline=deadline,
        )
        try:
            self._extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise VoiceRuntimeError("Food extraction failed.") from error
        return self._extraction

    def report_success(self, events: Sequence[ConsumptionEvent], deadline: float) -> None:
        descriptions = [
            f"{event.quantity_value:g} {event.quantity_measure} {event.food_description}"
            for event in events
        ]
        text = f"Recorded {', '.join(descriptions)}."
        self._report("success_sound", text, deadline)

    def report_failure(self, reason: str, deadline: float) -> None:
        self._report("error_sound", reason, deadline)

    def _report(self, sound_command: str, text: str, deadline: float) -> None:
        try:
            feedback_deadline = min(
                deadline,
                self._monotonic() + FEEDBACK_TIMEOUT_SECONDS,
            )
            root = self._artifact_root()
            speech_path = root / "speech.wav"
            self._run(sound_command, {}, deadline=feedback_deadline)
            self._run(
                "speech_synthesis",
                {"text": text, "output": str(speech_path)},
                deadline=feedback_deadline,
            )
            self._run("play_speech", {"audio": str(speech_path)}, deadline=feedback_deadline)
        finally:
            self._cleanup()

    def _run(
        self,
        name: str,
        replacements: Mapping[str, str],
        *,
        deadline: float | None = None,
        timeout: float | None = None,
    ) -> None:
        try:
            command = [part.format_map(replacements) for part in self._commands[name]]
        except (KeyError, ValueError) as error:
            raise VoiceRuntimeError(f"Voice command {name} is invalid.") from error
        if deadline is not None:
            timeout = deadline - self._monotonic()
            if timeout <= 0:
                raise VoiceProcessingTimeout
        try:
            self._run_command(command, timeout)
        except VoiceProcessingTimeout:
            raise
        except VoiceRuntimeError as error:
            raise VoiceRuntimeError(f"Voice command {name} failed.") from error

    def _artifact_root(self) -> Path:
        if self._artifacts is None:
            self._artifacts = tempfile.TemporaryDirectory(
                prefix="snack-gpt-report-",
                dir=self._memory_directory,
            )
        return Path(self._artifacts.name)

    def _cleanup(self) -> None:
        self._extraction = None
        if self._artifacts is not None:
            self._artifacts.cleanup()
            self._artifacts = None


def _run_command(command: Sequence[str], timeout: float | None) -> None:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise VoiceProcessingTimeout from error
    except OSError as error:
        raise VoiceRuntimeError("Voice command could not start.") from error
    if result.returncode != 0:
        raise VoiceRuntimeError("Voice command failed.")