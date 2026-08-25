from pathlib import Path
import json
import tempfile
from threading import Thread
import unittest
from urllib.request import urlopen
from wsgiref.simple_server import make_server

from snack_gpt.config import Settings
from snack_gpt.http import create_application


class HttpTests(unittest.TestCase):
    def test_browser_can_view_application_and_storage_health(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_path=Path(directory) / "snack-gpt.sqlite3",
                host="127.0.0.1",
                port=0,
            )
            application = create_application(settings)

            with make_server("127.0.0.1", 0, application) as server:
                thread = Thread(target=server.handle_request)
                thread.start()
                try:
                    with urlopen(
                        f"http://127.0.0.1:{server.server_port}/", timeout=2
                    ) as response:
                        body = response.read().decode("utf-8")
                finally:
                    thread.join(timeout=2)

            self.assertEqual(response.status, 200)
            self.assertIn("<h1>Snack-GPT</h1>", body)
            self.assertIn("Application ready", body)
            self.assertIn("Storage healthy", body)
            self.assertIn("Schema 1", body)

    def test_health_endpoint_reports_application_and_storage_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_path=Path(directory) / "snack-gpt.sqlite3",
                host="127.0.0.1",
                port=0,
            )
            application = create_application(settings)

            with make_server("127.0.0.1", 0, application) as server:
                thread = Thread(target=server.handle_request)
                thread.start()
                try:
                    with urlopen(
                        f"http://127.0.0.1:{server.server_port}/health", timeout=2
                    ) as response:
                        content_type = response.headers["Content-Type"]
                        payload = json.load(response)
                finally:
                    thread.join(timeout=2)

            self.assertEqual(response.status, 200)
            self.assertEqual(content_type, "application/json")
            self.assertEqual(
                payload,
                {
                    "application": "ready",
                    "storage": "healthy",
                    "schema_version": 1,
                },
            )


if __name__ == "__main__":
    unittest.main()