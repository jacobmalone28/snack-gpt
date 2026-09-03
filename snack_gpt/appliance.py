from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys

from dotenv import dotenv_values


SERVICES = (
    "snack-gpt-web.service",
    "snack-gpt-piper.service",
    "snack-gpt-listener.service",
)


@dataclass(frozen=True)
class AppliancePaths:
    environment: Path = Path("/etc/snack-gpt/environment")
    audio_command: Path = Path("/opt/snack-gpt/bin/voice-audio")


def _load_environment(path: Path) -> dict[str, str]:
    try:
        values: Mapping[str, str | None] = dotenv_values(path)
    except OSError as error:
        raise ValueError(f"cannot read {path}") from error
    environment = os.environ.copy()
    environment.update({key: value for key, value in values.items() if value is not None})
    return environment


def _audio_environment(environment: Mapping[str, str]) -> dict[str, str]:
    audio_environment = os.environ.copy()
    for variable in ("SNACK_GPT_MICROPHONE", "SNACK_GPT_SPEAKER"):
        if variable in environment:
            audio_environment[variable] = environment[variable]
    return audio_environment


def start(
    *,
    paths: AppliancePaths = AppliancePaths(),
    elevated_command: Sequence[str] | None = None,
) -> int:
    if not paths.environment.is_file() or not paths.audio_command.is_file():
        print(
            "Appliance is not provisioned; run scripts/provision-voice-probe.sh first.",
            file=sys.stderr,
        )
        return 2
    try:
        environment = _load_environment(paths.environment)
    except ValueError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    if not environment.get("USDA_FDC_API_KEY", "").strip():
        print(
            f"Configuration error: set USDA_FDC_API_KEY in {paths.environment}",
            file=sys.stderr,
        )
        return 2

    print("Checking the configured microphone and speaker...")
    try:
        subprocess.run(
            [str(paths.audio_command), "check"],
            check=True,
            env=_audio_environment(environment),
        )
    except (OSError, subprocess.CalledProcessError):
        print("Audio check failed; services were not enabled.", file=sys.stderr)
        return 1

    elevation = tuple(elevated_command) if elevated_command is not None else (
        () if os.geteuid() == 0 else ("sudo",)
    )
    try:
        subprocess.run(
            [*elevation, "systemctl", "enable", "--now", *SERVICES],
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        print("Could not enable and start Snack-GPT services.", file=sys.stderr)
        return 1
    print("Snack-GPT is started. Open http://127.0.0.1:8000/.")
    return 0