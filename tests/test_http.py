from pathlib import Path
import json
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID
from wsgiref.simple_server import make_server

from snack_gpt.config import Settings
from snack_gpt.http import create_application
from snack_gpt.ingestion import FoodSearchResult
from snack_gpt.storage import Storage


class ControlledUsdaSearch:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str) -> list[FoodSearchResult]:
        self.queries.append(query)
        if query != "egg":
            return []
        return [
            FoodSearchResult(
                usda_food_id="171287",
                description="Egg, whole, raw, fresh",
                nutrients_per_100_grams={
                    "calories": 143.0,
                    "protein": 12.6,
                    "carbohydrates": 0.72,
                    "fat": 9.51,
                },
                measures={"large": 50.0},
            )
        ]


class HttpTests(unittest.TestCase):
    def test_owner_can_create_repeated_consumption_events_in_one_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_path=Path(directory) / "snack-gpt.sqlite3",
                host="127.0.0.1",
                port=0,
            )
            usda_search = ControlledUsdaSearch()
            application = create_application(settings, usda_search)
            form = urlencode(
                [
                    ("food", "egg"),
                    ("food", "egg"),
                    ("quantity", "1"),
                    ("quantity", "2"),
                    ("measure", "large"),
                    ("measure", "large"),
                    ("day", "2026-08-25"),
                ]
            ).encode()

            with make_server("127.0.0.1", 0, application) as server:
                thread = Thread(target=server.handle_request)
                thread.start()
                try:
                    request = Request(
                        f"http://127.0.0.1:{server.server_port}/consumption-events",
                        data=form,
                        method="POST",
                    )
                    with urlopen(request, timeout=2) as response:
                        body = response.read().decode("utf-8")
                finally:
                    thread.join(timeout=2)

            with Storage(settings.database_path) as storage:
                events = storage.list_consumption_events()

            self.assertEqual(response.status, 201)
            self.assertIn("Created 2 Consumption Events", body)
            self.assertEqual(usda_search.queries, ["egg", "egg"])
            self.assertEqual([event.quantity_value for event in events], [1.0, 2.0])
            self.assertEqual(len({event.event_id for event in events}), 2)

    def test_consumption_report_stores_nothing_when_any_lookup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_path=Path(directory) / "snack-gpt.sqlite3",
                host="127.0.0.1",
                port=0,
            )
            usda_search = ControlledUsdaSearch()
            application = create_application(settings, usda_search)
            form = urlencode(
                [
                    ("food", "egg"),
                    ("food", "unknown"),
                    ("quantity", "1"),
                    ("quantity", "1"),
                    ("measure", "large"),
                    ("measure", "grams"),
                    ("day", "2026-08-25"),
                ]
            ).encode()

            with make_server("127.0.0.1", 0, application) as server:
                thread = Thread(target=server.handle_request)
                thread.start()
                try:
                    request = Request(
                        f"http://127.0.0.1:{server.server_port}/consumption-events",
                        data=form,
                        method="POST",
                    )
                    with self.assertRaises(HTTPError) as raised:
                        urlopen(request, timeout=2)
                finally:
                    thread.join(timeout=2)

            with Storage(settings.database_path) as storage:
                events = storage.list_consumption_events()

            self.assertEqual(raised.exception.code, 422)
            self.assertEqual(usda_search.queries, ["egg", "unknown"])
            self.assertEqual(events, [])

    def test_invalid_quantity_shows_an_error_and_creates_no_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_path=Path(directory) / "snack-gpt.sqlite3",
                host="127.0.0.1",
                port=0,
            )
            application = create_application(settings, ControlledUsdaSearch())
            form = urlencode(
                {"food": "egg", "quantity": "0", "measure": "grams", "day": "2026-08-25"}
            ).encode()

            with make_server("127.0.0.1", 0, application) as server:
                thread = Thread(target=server.handle_request)
                thread.start()
                try:
                    request = Request(
                        f"http://127.0.0.1:{server.server_port}/consumption-events",
                        data=form,
                        method="POST",
                    )
                    with self.assertRaises(HTTPError) as raised:
                        urlopen(request, timeout=2)
                    body = raised.exception.read().decode("utf-8")
                finally:
                    thread.join(timeout=2)

            with Storage(settings.database_path) as storage:
                events = storage.list_consumption_events()

            self.assertEqual(raised.exception.code, 422)
            self.assertIn("greater than zero", body)
            self.assertEqual(events, [])

    def test_owner_can_create_a_consumption_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_path=Path(directory) / "snack-gpt.sqlite3",
                host="127.0.0.1",
                port=0,
            )
            application = create_application(settings, ControlledUsdaSearch())
            form = urlencode(
                {"food": "egg", "quantity": "2", "measure": "large", "day": "2026-08-25"}
            ).encode()

            with make_server("127.0.0.1", 0, application) as server:
                thread = Thread(target=server.handle_request)
                thread.start()
                try:
                    request = Request(
                        f"http://127.0.0.1:{server.server_port}/consumption-events",
                        data=form,
                        method="POST",
                    )
                    with urlopen(request, timeout=2) as response:
                        body = response.read().decode("utf-8")
                finally:
                    thread.join(timeout=2)

            with Storage(settings.database_path) as storage:
                events = storage.list_consumption_events()

            self.assertEqual(response.status, 201)
            self.assertIn("Egg, whole, raw, fresh", body)
            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertEqual(str(UUID(event.event_id)), event.event_id)
            self.assertEqual(event.usda_food_id, "171287")
            self.assertEqual(event.food_description, "Egg, whole, raw, fresh")
            self.assertEqual(event.quantity_value, 2.0)
            self.assertEqual(event.quantity_measure, "large")
            self.assertEqual(event.day.isoformat(), "2026-08-25")
            self.assertEqual(event.revision, 1)
            self.assertEqual(event.nutrition.calories, 143.0)
            self.assertEqual(event.nutrition.protein, 12.6)
            self.assertEqual(event.nutrition.carbohydrates, 0.72)
            self.assertEqual(event.nutrition.fat, 9.51)

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
            self.assertIn("Schema 2", body)
            self.assertIn('action="/consumption-events"', body)
            self.assertIn('name="food"', body)
            self.assertIn('name="quantity"', body)
            self.assertIn('name="measure"', body)
            self.assertIn('name="day"', body)
            self.assertIn('id="add-food"', body)
            self.assertIn('id="report-item-template"', body)
            self.assertIn("Create Consumption Report", body)

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
                    "schema_version": 2,
                },
            )


if __name__ == "__main__":
    unittest.main()