import os
from pathlib import Path
import sys
from collections.abc import Sequence
from getpass import getpass
import logging
import time
from wsgiref.simple_server import make_server

from dotenv import load_dotenv

from snack_gpt.auth import hash_password
from snack_gpt.config import ConfigurationError, Settings
from snack_gpt.http import create_application
from snack_gpt.storage import Storage, VoiceStatus
from snack_gpt.usda import FoodDataCentralSearch
from snack_gpt.voice import (
    VoiceListeningPaused,
    VoiceProcessingError,
    create_consumption_report_from_voice,
)
from snack_gpt.voice_runtime import CommandVoiceRuntime, VoiceRuntimeError, load_voice_manifest


def run(arguments: Sequence[str]) -> int:
    command = tuple(arguments)
    if command not in (("check",), ("listen",), ("serve",), ("set-password",)):
        print("Usage: snack-gpt {check,listen,serve,set-password}", file=sys.stderr)
        return 2

    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)

    try:
        settings = Settings.from_environment(os.environ)
    except ConfigurationError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2

    if command == ("set-password",):
        password = getpass("Owner password: ")
        confirmation = getpass("Confirm owner password: ")
        if not password:
            print("Password cannot be blank.", file=sys.stderr)
            return 2
        if password != confirmation:
            print("Passwords do not match.", file=sys.stderr)
            return 2
        with Storage(settings.database_path) as storage:
            storage.initialize()
            storage.set_owner_password_hash(hash_password(password))
        print("Owner password updated; existing sessions were signed out.")
        return 0

    if command == ("serve",):
        try:
            application = create_application(settings)
        except ConfigurationError as error:
            print(f"Configuration error: {error}", file=sys.stderr)
            return 2
        with make_server(settings.host, settings.port, application) as server:
            print(f"Snack-GPT listening on http://{settings.host}:{settings.port}")
            server.serve_forever()
        return 0

    if command == ("listen",):
        logging.basicConfig(level=logging.INFO)
        with Storage(settings.database_path) as storage:
            storage.initialize()
            if settings.usda_api_key is None:
                storage.set_voice_status(
                    VoiceStatus.CONFIGURATION_ERROR, usda_available=False
                )
                print("Configuration error: USDA_FDC_API_KEY is required for voice reports", file=sys.stderr)
                return 2
            if settings.voice_manifest_path is None:
                storage.set_voice_status(VoiceStatus.CONFIGURATION_ERROR)
                print("Configuration error: SNACK_GPT_VOICE_MANIFEST is required for listening", file=sys.stderr)
                return 2
            try:
                manifest = load_voice_manifest(settings.voice_manifest_path)
                runtime = CommandVoiceRuntime(
                    manifest.commands,
                    manifest.memory_directory,
                    listening_allowed=lambda: not storage.voice_state().paused,
                )
            except VoiceRuntimeError as error:
                storage.set_voice_status(VoiceStatus.CONFIGURATION_ERROR)
                print(f"Configuration error: {error}", file=sys.stderr)
                return 2
            usda_search = FoodDataCentralSearch(settings.usda_api_key)
            storage.set_voice_status(VoiceStatus.LISTENING)

            def state_changed(
                status: VoiceStatus, usda_available: bool | None
            ) -> None:
                storage.set_voice_status(status, usda_available=usda_available)

            try:
                while True:
                    if storage.voice_state().paused:
                        time.sleep(0.1)
                        continue
                    try:
                        create_consumption_report_from_voice(
                            storage,
                            usda_search,
                            runtime,
                            state_changed=state_changed,
                        )
                    except VoiceListeningPaused:
                        continue
                    except VoiceProcessingError:
                        storage.set_voice_status(VoiceStatus.AUDIO_UNAVAILABLE)
                        print("Voice feedback failed; resuming listening.", file=sys.stderr)
            except KeyboardInterrupt:
                return 0

    with Storage(settings.database_path) as storage:
        storage.initialize()
        health = storage.health()
    print(f"Snack-GPT is healthy (schema {health.schema_version})")
    return 0


def main() -> None:
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()