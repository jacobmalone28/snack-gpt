from __future__ import annotations

import argparse
from collections.abc import Sequence
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def _audio_environment(variable: str) -> dict[str, str]:
    environment = os.environ.copy()
    device = os.environ.get(variable, "").strip()
    if device:
        environment["AUDIODEV"] = device
    return environment


def _run(command: Sequence[str], *, device_variable: str) -> int:
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
    command = [
        "rec",
        "--no-show-progress",
        "--channels",
        "1",
        "--rate",
        "16000",
        "--bits",
        "16",
        str(output),
    ]
    if mode == "wake":
        command.extend(["trim", "0", "1.5"])
    else:
        command.extend(["silence", "1", "0.1", "1%", "1", str(silence_seconds), "1%"])
    return _run(command, device_variable="SNACK_GPT_MICROPHONE")


def _play(audio: Path) -> int:
    return _run(
        ["play", "--no-show-progress", str(audio)],
        device_variable="SNACK_GPT_SPEAKER",
    )


def _tone(kind: str) -> int:
    frequency = "880" if kind == "success" else "220"
    return _run(
        [
            "play",
            "--no-show-progress",
            "--null",
            "synth",
            "0.08",
            "sine",
            frequency,
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
    tone.add_argument("kind", choices=("success", "error"))

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