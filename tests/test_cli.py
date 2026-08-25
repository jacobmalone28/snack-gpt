import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import URLError
from urllib.request import urlopen


class CliTests(unittest.TestCase):
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
            self.assertEqual(first_result.stdout, "Snack-GPT is healthy (schema 1)\n")
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
            deadline = time.monotonic() + 3

            try:
                while True:
                    if process.poll() is not None:
                        self.fail(f"Server exited early: {process.stderr.read()}")
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