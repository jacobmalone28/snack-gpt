from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys

from dotenv import dotenv_values

from snack_gpt.config import ConfigurationError, Settings


SERVICES = (
    "snack-gpt-web.service",
    "snack-gpt-wake.service",
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
    return {key: value for key, value in values.items() if value is not None}


def _audio_environment(environment: Mapping[str, str]) -> dict[str, str]:
    audio_environment = os.environ.copy()
    audio_environment.pop("USDA_FDC_API_KEY", None)
    for variable in ("SNACK_GPT_MICROPHONE", "SNACK_GPT_SPEAKER"):
        if variable in environment:
            audio_environment[variable] = environment[variable]
    return audio_environment


def _default_elevation() -> tuple[str, ...]:
    get_effective_user_id = getattr(os, "geteuid", None)
    if not callable(get_effective_user_id):
        raise ConfigurationError("start is available only on a systemd appliance")
    return () if get_effective_user_id() == 0 else ("sudo",)


def _web_url(settings: Settings) -> str:
    host = f"[{settings.host}]" if ":" in settings.host else settings.host
    return f"http://{host}:{settings.port}/"


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
    try:
        settings = Settings.from_environment(environment)
        elevation = (
            tuple(elevated_command)
            if elevated_command is not None
            else _default_elevation()
        )
    except ConfigurationError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
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

    try:
        subprocess.run(
            [*elevation, "systemctl", "enable", "--now", *SERVICES],
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        print("Could not enable and start Snack-GPT services.", file=sys.stderr)
        return 1
    print(f"Snack-GPT is started. Open {_web_url(settings)}.")
    return 0