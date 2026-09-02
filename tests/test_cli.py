import os
from io import StringIO
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import urlopen

from snack_gpt.config import Settings
from snack_gpt.__main__ import run
from snack_gpt.auth import verify_password
from snack_gpt.storage import Storage
from snack_gpt.voice import VoiceProcessingError
from snack_gpt.voice_runtime import VoiceManifest


class CliTests(unittest.TestCase):
    def test_listen_resumes_after_feedback_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "voice.json"
            environment = {
                "SNACK_GPT_DATABASE": str(Path(directory) / "snack-gpt.sqlite3"),
                "SNACK_GPT_VOICE_MANIFEST": str(manifest_path),
                "USDA_FDC_API_KEY": "test-key",
            }
            stderr = StringIO()
            with patch.dict(os.environ, environment, clear=True), patch(
                "snack_gpt.__main__.load_dotenv"
            ), patch(
                "snack_gpt.__main__.load_voice_manifest",
                return_value=VoiceManifest({}, Path(directory)),
            ), patch(
                "snack_gpt.__main__.CommandVoiceRuntime", return_value=object()
            ), patch(
                "snack_gpt.__main__.create_consumption_report_from_voice",
                side_effect=[VoiceProcessingError("private runtime detail"), KeyboardInterrupt],
            ) as create_from_voice, patch("sys.stderr", stderr):
                result = run(["listen"])

        self.assertEqual(result, 0)
        self.assertEqual(create_from_voice.call_count, 2)
        self.assertEqual(stderr.getvalue(), "Voice feedback failed; resuming listening.\n")

    def test_listen_runs_voice_reports_until_interrupted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "snack-gpt.sqlite3"
            manifest_path = Path(directory) / "voice.json"
            environment = {
                "SNACK_GPT_DATABASE": str(database_path),
                "SNACK_GPT_VOICE_MANIFEST": str(manifest_path),
                "USDA_FDC_API_KEY": "test-key",
            }
            runtime = object()
            with patch.dict(os.environ, environment, clear=True), patch(
                "snack_gpt.__main__.load_dotenv"
            ), patch(
                "snack_gpt.__main__.load_voice_manifest",
                return_value=VoiceManifest({}, Path(directory)),
            ) as load_commands, patch(
                "snack_gpt.__main__.CommandVoiceRuntime", return_value=runtime
            ), patch(
                "snack_gpt.__main__.create_consumption_report_from_voice",
                side_effect=KeyboardInterrupt,
            ) as create_from_voice:
                result = run(["listen"])

            with Storage(database_path) as storage:
                health = storage.health()

        self.assertEqual(result, 0)
        self.assertEqual(health.schema_version, 5)
        load_commands.assert_called_once_with(manifest_path)
        self.assertEqual(create_from_voice.call_count, 1)
        self.assertIs(create_from_voice.call_args.args[2], runtime)

    def test_set_password_initializes_and_resets_owner_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "snack-gpt.sqlite3"
            environment = {"SNACK_GPT_DATABASE": str(database_path)}
            with patch.dict(os.environ, environment, clear=True), patch(
                "snack_gpt.__main__.load_dotenv"
            ), patch(
                "snack_gpt.__main__.getpass",
                side_effect=["first password", "first password"],
            ):
                first_result = run(["set-password"])
            with patch.dict(os.environ, environment, clear=True), patch(
                "snack_gpt.__main__.load_dotenv"
            ), patch(
                "snack_gpt.__main__.getpass",
                side_effect=["replacement password", "replacement password"],
            ):
                second_result = run(["set-password"])

            with Storage(database_path) as storage:
                stored_hash = storage.owner_password_hash()

        self.assertEqual(first_result, 0)
        self.assertEqual(second_result, 0)
        self.assertIsNotNone(stored_hash)
        assert stored_hash is not None
        self.assertTrue(verify_password("replacement password", stored_hash))
        self.assertFalse(verify_password("first password", stored_hash))

    def test_lan_serve_without_password_reports_configuration_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = {
                "SNACK_GPT_DATABASE": str(Path(directory) / "snack-gpt.sqlite3"),
                "SNACK_GPT_HOST": "0.0.0.0",
            }
            stderr = StringIO()
            with patch.dict(os.environ, environment, clear=True), patch(
                "snack_gpt.__main__.load_dotenv"
            ), patch("sys.stderr", stderr):
                result = run(["serve"])

        self.assertEqual(result, 2)
        self.assertEqual(
            stderr.getvalue(),
            "Configuration error: LAN access requires an owner password; run snack-gpt set-password first\n",
        )

    def test_only_loopback_bindings_bypass_authentication(self) -> None:
        for host in ("127.0.0.1", "127.12.34.56", "::1"):
            with self.subTest(host=host):
                settings = Settings(Path("unused.sqlite3"), host, 8000)
                self.assertFalse(settings.authentication_required)

        for host in ("0.0.0.0", "::", "192.168.1.10", "snack-gpt.local"):
            with self.subTest(host=host):
                settings = Settings(Path("unused.sqlite3"), host, 8000)
                self.assertTrue(settings.authentication_required)

    def test_check_loads_dotenv_without_overriding_exported_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            working_directory = Path(directory)
            database_path = working_directory / "from-dotenv.sqlite3"
            (working_directory / ".env").write_text(
                f"SNACK_GPT_DATABASE={database_path}\nSNACK_GPT_PORT=not-a-port\n"
            )
            environment = os.environ | {
                "PYTHONPATH": str(Path(__file__).parents[1]),
                "SNACK_GPT_PORT": "8000",
            }
            environment.pop("SNACK_GPT_DATABASE", None)

            result = subprocess.run(
                [sys.executable, "-m", "snack_gpt", "check"],
                capture_output=True,
                check=False,
                cwd=working_directory,
                env=environment,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(database_path.is_file())

    def test_check_reports_invalid_port_without_creating_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "snack-gpt.sqlite3"
            environment = os.environ | {
                "SNACK_GPT_DATABASE": str(database_path),
                "SNACK_GPT_PORT": "not-a-port",
            }

            result = subprocess.run(
                [sys.executable, "-m", "snack_gpt", "check"],
                capture_output=True,
                check=False,
                env=environment,
                text=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stderr, "Configuration error: SNACK_GPT_PORT must be an integer\n")
            self.assertFalse(database_path.exists())

    def test_check_initializes_storage_and_reports_health(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "snack-gpt.sqlite3"
            environment = os.environ | {"SNACK_GPT_DATABASE": str(database_path)}

            first_result = subprocess.run(
                [sys.executable, "-m", "snack_gpt", "check"],
                capture_output=True,
                check=False,
                env=environment,
                text=True,
            )
            second_result = subprocess.run(
                [sys.executable, "-m", "snack_gpt", "check"],
                capture_output=True,
                check=False,
                env=environment,
                text=True,
            )

            self.assertEqual(first_result.returncode, 0)
            self.assertEqual(first_result.stdout, "Snack-GPT is healthy (schema 5)\n")
            self.assertEqual(second_result.returncode, 0)
            self.assertEqual(second_result.stdout, first_result.stdout)
            self.assertTrue(database_path.is_file())

    def test_serve_starts_the_browser_application(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "snack-gpt.sqlite3"
            with socket.socket() as available_socket:
                available_socket.bind(("127.0.0.1", 0))
                port = available_socket.getsockname()[1]

            environment = os.environ | {
                "SNACK_GPT_DATABASE": str(database_path),
                "SNACK_GPT_HOST": "127.0.0.1",
                "SNACK_GPT_PORT": str(port),
            }
            process = subprocess.Popen(
                [sys.executable, "-m", "snack_gpt", "serve"],
                env=environment,
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
            )
            stderr = process.stderr
            if stderr is None:
                self.fail("Server process has no stderr pipe")
            deadline = time.monotonic() + 3

            try:
                while True:
                    if process.poll() is not None:
                        self.fail(f"Server exited early: {stderr.read()}")
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/health", timeout=0.1) as response:
                            break
                    except URLError:
                        if time.monotonic() >= deadline:
                            self.fail("Server did not become ready within 3 seconds")
            finally:
                process.terminate()
                process.wait(timeout=2)
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()

            self.assertEqual(response.status, 200)
            self.assertTrue(database_path.is_file())


if __name__ == "__main__":
    unittest.main()