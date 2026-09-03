from __future__ import annotations

import argparse
from collections.abc import Sequence
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def _audio_environment(variable: str | None) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("USDA_FDC_API_KEY", None)
    device = os.environ.get(variable, "").strip() if variable is not None else ""
    if device:
        environment["AUDIODRIVER"] = "alsa"
        environment["AUDIODEV"] = device
    return environment


def _run(command: Sequence[str], *, device_variable: str | None = None) -> int:
    try:
        subprocess.run(
            command,
            check=True,
            env=_audio_environment(device_variable),
        )
    except FileNotFoundError:
        print(f"Audio command is unavailable: {command[0]}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError:
        print("Audio device command failed.", file=sys.stderr)
        return 1
    return 0


def _capture(mode: str, output: Path, silence_seconds: float) -> int:
    with tempfile.NamedTemporaryFile(
        prefix="snack-gpt-native-",
        suffix=".wav",
        dir=output.parent,
        delete=False,
    ) as temporary:
        native_audio = Path(temporary.name)
    try:
        capture_command = ["rec", "--no-show-progress", str(native_audio)]
        if mode == "wake":
            capture_command.extend(["trim", "0", "1.5"])
        else:
            capture_command.extend(
                ["silence", "1", "0.1", "1%", "1", str(silence_seconds), "1%"]
            )
        if _run(capture_command, device_variable="SNACK_GPT_MICROPHONE") != 0:
            return 1
        return _run(
            [
                "sox",
                "--no-show-progress",
                str(native_audio),
                "--channels",
                "1",
                "--rate",
                "16000",
                "--bits",
                "16",
                str(output),
            ]
        )
    finally:
        native_audio.unlink(missing_ok=True)


def _play(audio: Path) -> int:
    return _run(
        ["play", "--no-show-progress", str(audio)],
        device_variable="SNACK_GPT_SPEAKER",
    )


def _tone(kind: str) -> int:
    frequencies = {"wake": "660", "success": "880", "error": "220"}
    durations = {"wake": "0.35", "success": "0.25", "error": "0.25"}
    return _run(
        [
            "play",
            "--no-show-progress",
            "--null",
            "synth",
            durations[kind],
            "sine",
            frequencies[kind],
        ],
        device_variable="SNACK_GPT_SPEAKER",
    )


def _check() -> int:
    with tempfile.TemporaryDirectory(prefix="snack-gpt-audio-") as directory:
        recording = Path(directory) / "check.wav"
        print("Recording 1.5 seconds from the configured microphone...")
        if _capture("wake", recording, 1.0) != 0:
            return 1
        print("Playing the recording through the configured speaker...")
        return _play(recording)


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture and play Snack-GPT audio")
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture")
    capture.add_argument("--mode", choices=("wake", "speech"), required=True)
    capture.add_argument("--silence-seconds", type=float, default=1.0)
    capture.add_argument("--output", type=Path, required=True)

    play = subparsers.add_parser("play")
    play.add_argument("audio", type=Path)

    tone = subparsers.add_parser("tone")
    tone.add_argument("kind", choices=("wake", "success", "error"))

    subparsers.add_parser("check")
    parsed = parser.parse_args(arguments)
    if parsed.command == "capture":
        return _capture(parsed.mode, parsed.output, parsed.silence_seconds)
    if parsed.command == "play":
        return _play(parsed.audio)
    if parsed.command == "tone":
        return _tone(parsed.kind)
    return _check()


if __name__ == "__main__":
    raise SystemExit(main())