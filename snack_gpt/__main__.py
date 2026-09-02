import os
from pathlib import Path
import sys
from collections.abc import Sequence
from getpass import getpass
from wsgiref.simple_server import make_server

from dotenv import load_dotenv

from snack_gpt.auth import hash_password
from snack_gpt.config import ConfigurationError, Settings
from snack_gpt.http import create_application
from snack_gpt.storage import Storage


def run(arguments: Sequence[str]) -> int:
    command = tuple(arguments)
    if command not in (("check",), ("serve",), ("set-password",)):
        print("Usage: snack-gpt {check,serve,set-password}", file=sys.stderr)
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

    with Storage(settings.database_path) as storage:
        storage.initialize()
        health = storage.health()
    print(f"Snack-GPT is healthy (schema {health.schema_version})")
    return 0


def main() -> None:
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()