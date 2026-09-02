from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
import json
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID
from wsgiref.simple_server import make_server

from snack_gpt.auth import hash_password
from snack_gpt.config import ConfigurationError, Settings
from snack_gpt.http import Application, create_application
from snack_gpt.ingestion import FoodSearchResult
from snack_gpt.storage import ConsumptionEvent, NutritionSnapshot, Storage


class ControlledUsdaSearch:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(
        self,
        query: str,
        *,
        timeout_seconds: float | None = None,
    ) -> list[FoodSearchResult]:
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


def post_form(
    application: Application, path: str, values: dict[str, str]
) -> tuple[str, str]:
    body = urlencode(values).encode()
    statuses: list[str] = []

    def start_response(status: str, headers: list[tuple[str, str]]) -> object:
        statuses.append(status)
        return None

    response = b"".join(
        application(
            {
                "PATH_INFO": path,
                "REQUEST_METHOD": "POST",
                "CONTENT_LENGTH": str(len(body)),
                "wsgi.input": BytesIO(body),
            },
            start_response,
        )
    ).decode()
    return statuses[0], response


def request_application(
    application: Application,
    method: str,
    path: str,
    values: dict[str, str] | None = None,
    cookie: str | None = None,
    remote_address: str = "127.0.0.1",
) -> tuple[str, list[tuple[str, str]], str]:
    body = urlencode(values or {}).encode()
    responses: list[tuple[str, list[tuple[str, str]]]] = []

    def start_response(status: str, headers: list[tuple[str, str]]) -> object:
        responses.append((status, headers))
        return None

    environment: dict[str, object] = {
        "PATH_INFO": path,
        "REQUEST_METHOD": method,
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "REMOTE_ADDR": remote_address,
        "wsgi.input": BytesIO(body),
    }
    if cookie is not None:
        environment["HTTP_COOKIE"] = cookie
    response_body = b"".join(application(environment, start_response)).decode()
    status, headers = responses[0]
    return status, headers, response_body


class HttpTests(unittest.TestCase):
    def test_lan_application_requires_configured_owner_password(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_path=Path(directory) / "snack-gpt.sqlite3",
                host="0.0.0.0",
                port=8000,
            )

            with self.assertRaisesRegex(
                ConfigurationError, "run snack-gpt set-password first"
            ):
                create_application(settings)

    def test_lan_login_protects_requests_and_logout_revokes_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_path=Path(directory) / "snack-gpt.sqlite3",
                host="0.0.0.0",
                port=8000,
            )
            with Storage(settings.database_path) as storage:
                storage.initialize()
                storage.set_owner_password_hash(hash_password("owner password"))
            application = create_application(settings)

            denied_status, _, denied_body = request_application(
                application, "GET", "/health"
            )
            malformed_cookie_status, _, _ = request_application(
                application,
                "GET",
                "/health",
                cookie='snack_gpt_session="unterminated',
            )
            failed_status, failed_headers, failed_body = request_application(
                application,
                "POST",
                "/login",
                {"password": "incorrect"},
                remote_address="192.0.2.10",
            )
            login_status, login_headers, _ = request_application(
                application, "POST", "/login", {"password": "owner password"}
            )
            set_cookie = dict(login_headers)["Set-Cookie"]
            cookie = set_cookie.partition(";")[0]
            health_status, health_headers, health_body = request_application(
                application, "GET", "/health", cookie=cookie
            )
            home_status, home_headers, _ = request_application(
                application, "GET", "/", cookie=cookie
            )
            export_status, export_headers, _ = request_application(
                application, "GET", "/consumption-events/export", cookie=cookie
            )
            logout_status, logout_headers, _ = request_application(
                application, "POST", "/logout", cookie=cookie
            )
            revoked_status, _, _ = request_application(
                application, "GET", "/health", cookie=cookie
            )

        self.assertEqual(denied_status, "401 Unauthorized")
        self.assertNotIn("schema_version", denied_body)
        self.assertEqual(malformed_cookie_status, "401 Unauthorized")
        self.assertEqual(failed_status, "401 Unauthorized")
        self.assertEqual(dict(failed_headers)["Cache-Control"], "no-store")
        self.assertIn("Login failed.", failed_body)
        self.assertNotIn("owner password", failed_body)
        self.assertEqual(login_status, "303 See Other")
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Strict", set_cookie)
        self.assertEqual(health_status, "200 OK")
        self.assertIn('"storage":"healthy"', health_body)
        self.assertEqual(dict(health_headers)["Cache-Control"], "no-store")
        self.assertEqual(home_status, "200 OK")
        self.assertEqual(dict(home_headers)["Cache-Control"], "no-store")
        self.assertEqual(export_status, "200 OK")
        self.assertEqual(dict(export_headers)["Cache-Control"], "no-store")
        self.assertEqual(logout_status, "303 See Other")
        self.assertIn("Max-Age=0", dict(logout_headers)["Set-Cookie"])
        self.assertEqual(revoked_status, "401 Unauthorized")

    def test_lan_login_throttles_failures_before_repeating_scrypt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_path=Path(directory) / "snack-gpt.sqlite3",
                host="0.0.0.0",
                port=8000,
            )
            with Storage(settings.database_path) as storage:
                storage.initialize()
                storage.set_owner_password_hash(hash_password("owner password"))
            application = create_application(settings)

            with patch("snack_gpt.http.time.monotonic", return_value=100), patch(
                "snack_gpt.http.verify_password", return_value=False
            ) as verify:
                first_status, _, _ = request_application(
                    application, "POST", "/login", {"password": "incorrect"}
                )
                blocked_status, blocked_headers, blocked_body = request_application(
                    application, "POST", "/login", {"password": "incorrect"}
                )

        self.assertEqual(first_status, "401 Unauthorized")
        self.assertEqual(blocked_status, "429 Too Many Requests")
        self.assertEqual(dict(blocked_headers)["Retry-After"], "1")
        self.assertIn("temporarily unavailable", blocked_body)
        verify.assert_called_once()

    def test_owner_can_correct_a_consumption_event(self) -> None:
        original = ConsumptionEvent(
            event_id="event-id",
            revision=1,
            day=date(2026, 8, 25),
            usda_food_id="171287",
            food_description="Egg, whole, raw, fresh",
            quantity_value=1,
            quantity_measure="large",
            nutrition=NutritionSnapshot(71.5, 6.3, 0.36, 4.755),
        )
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_path=Path(directory) / "snack-gpt.sqlite3",
                host="127.0.0.1",
                port=0,
            )
            with Storage(settings.database_path) as storage:
                storage.initialize()
                storage.create_consumption_event(original)
            application = create_application(settings)

            status, body = post_form(
                application,
                "/consumption-events/correct",
                {
                    "event_id": "event-id",
                    "revision": "1",
                    "food": original.food_description,
                    "quantity": "1",
                    "measure": "large",
                    "day": "2026-08-26",
                },
            )

            with Storage(settings.database_path) as storage:
                corrected = storage.get_consumption_event("event-id")

        self.assertEqual(status, "200 OK")
        self.assertIn("Corrected Consumption Event", body)
        self.assertIsNotNone(corrected)
        assert corrected is not None
        self.assertEqual(corrected.day, date(2026, 8, 26))
        self.assertEqual(corrected.revision, 2)
        self.assertEqual(corrected.nutrition, original.nutrition)

    def test_failed_and_stale_corrections_preserve_the_current_event(self) -> None:
        original = ConsumptionEvent(
            event_id="event-id",
            revision=2,
            day=date(2026, 8, 25),
            usda_food_id="171287",
            food_description="Egg, whole, raw, fresh",
            quantity_value=1,
            quantity_measure="large",
            nutrition=NutritionSnapshot(71.5, 6.3, 0.36, 4.755),
        )
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_path=Path(directory) / "snack-gpt.sqlite3",
                host="127.0.0.1",
                port=0,
            )
            with Storage(settings.database_path) as storage:
                storage.initialize()
                storage.create_consumption_event(original)
            application = create_application(settings, ControlledUsdaSearch())
            values = {
                "event_id": "event-id",
                "revision": "2",
                "food": "unknown",
                "quantity": "1",
                "measure": "large",
                "day": "2026-08-25",
            }

            failed_status, _ = post_form(
                application, "/consumption-events/correct", values
            )
            values["revision"] = "1"
            stale_status, _ = post_form(
                application, "/consumption-events/correct", values
            )

            with Storage(settings.database_path) as storage:
                current = storage.get_consumption_event("event-id")

        self.assertEqual(failed_status, "422 Unprocessable Entity")
        self.assertEqual(stale_status, "409 Conflict")
        self.assertEqual(current, original)

    def test_deletion_requires_confirmation_and_current_revision(self) -> None:
        event = ConsumptionEvent(
            event_id="event-id",
            revision=1,
            day=date(2026, 8, 25),
            usda_food_id="171287",
            food_description="Egg, whole, raw, fresh",
            quantity_value=1,
            quantity_measure="large",
            nutrition=NutritionSnapshot(71.5, 6.3, 0.36, 4.755),
        )
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_path=Path(directory) / "snack-gpt.sqlite3",
                host="127.0.0.1",
                port=0,
            )
            with Storage(settings.database_path) as storage:
                storage.initialize()
                storage.create_consumption_event(event)
            application = create_application(settings)
            path = "/consumption-events/delete"

            unconfirmed_status, _ = post_form(
                application, path, {"event_id": "event-id", "revision": "1"}
            )
            stale_status, _ = post_form(
                application,
                path,
                {"event_id": "event-id", "revision": "2", "confirmed": "yes"},
            )
            deleted_status, _ = post_form(
                application,
                path,
                {"event_id": "event-id", "revision": "1", "confirmed": "yes"},
            )

            with Storage(settings.database_path) as storage:
                events = storage.list_consumption_events()

        self.assertEqual(unconfirmed_status, "422 Unprocessable Entity")
        self.assertEqual(stale_status, "409 Conflict")
        self.assertEqual(deleted_status, "200 OK")
        self.assertEqual(events, [])

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

    def test_owner_can_export_and_import_history_without_usda(self) -> None:
        event = ConsumptionEvent(
            event_id="stable-event-id",
            revision=2,
            day=date(2026, 8, 25),
            usda_food_id="171287",
            food_description="Egg, whole, raw, fresh",
            quantity_value=2.0,
            quantity_measure="large",
            nutrition=NutritionSnapshot(143.0, 12.6, 0.72, 9.51),
        )
        with tempfile.TemporaryDirectory() as directory:
            source_settings = Settings(
                database_path=Path(directory) / "source.sqlite3",
                host="127.0.0.1",
                port=0,
            )
            with Storage(source_settings.database_path) as storage:
                storage.initialize()
                storage.create_consumption_event(event)
            source_application = create_application(source_settings)

            with make_server("127.0.0.1", 0, source_application) as server:
                thread = Thread(target=server.handle_request)
                thread.start()
                try:
                    with urlopen(
                        f"http://127.0.0.1:{server.server_port}/consumption-events/export",
                        timeout=2,
                    ) as response:
                        document = response.read()
                        content_disposition = response.headers["Content-Disposition"]
                finally:
                    thread.join(timeout=2)

            destination_settings = Settings(
                database_path=Path(directory) / "destination.sqlite3",
                host="127.0.0.1",
                port=0,
            )
            destination_application = create_application(destination_settings)
            with make_server("127.0.0.1", 0, destination_application) as server:
                thread = Thread(target=server.handle_request)
                thread.start()
                try:
                    request = Request(
                        f"http://127.0.0.1:{server.server_port}/consumption-events/import",
                        data=document,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urlopen(request, timeout=2) as import_response:
                        result = json.load(import_response)
                finally:
                    thread.join(timeout=2)

            with Storage(destination_settings.database_path) as storage:
                imported_events = storage.list_consumption_events()

        self.assertEqual(response.status, 200)
        self.assertEqual(content_disposition, 'attachment; filename="snack-gpt-history.json"')
        self.assertEqual(import_response.status, 200)
        self.assertEqual(result, {"imported": 1, "skipped": 0, "conflicts": []})
        self.assertEqual(imported_events, [event])

    def test_history_shows_calendar_week_events_and_totals_without_usda(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_path=Path(directory) / "snack-gpt.sqlite3",
                host="127.0.0.1",
                port=0,
            )
            today = date.today()
            monday = today - timedelta(days=today.weekday())
            events = [
                ConsumptionEvent(
                    event_id="monday-event",
                    revision=1,
                    day=monday,
                    usda_food_id="1",
                    food_description="Monday snack",
                    quantity_value=1,
                    quantity_measure="serving",
                    nutrition=NutritionSnapshot(120.4, 3.25, 7.26, 1.24),
                ),
                ConsumptionEvent(
                    event_id="sunday-event",
                    revision=1,
                    day=monday + timedelta(days=6),
                    usda_food_id="2",
                    food_description="Sunday snack",
                    quantity_value=2,
                    quantity_measure="eggs",
                    nutrition=NutritionSnapshot(79.6, 2.24, 1.25, 3.26),
                ),
                ConsumptionEvent(
                    event_id="previous-event",
                    revision=1,
                    day=monday - timedelta(days=1),
                    usda_food_id="3",
                    food_description="Previous snack",
                    quantity_value=1,
                    quantity_measure="cup",
                    nutrition=NutritionSnapshot(999, 99, 99, 99),
                ),
            ]
            with Storage(settings.database_path) as storage:
                storage.initialize()
                for event in events:
                    storage.create_consumption_event(event)

            application = create_application(settings)
            with make_server("127.0.0.1", 0, application) as server:
                thread = Thread(target=server.handle_request)
                thread.start()
                try:
                    with urlopen(
                        f"http://127.0.0.1:{server.server_port}/?week={monday.isoformat()}",
                        timeout=2,
                    ) as response:
                        body = response.read().decode("utf-8")
                finally:
                    thread.join(timeout=2)

            self.assertEqual(response.status, 200)
            self.assertIn("Monday snack", body)
            self.assertIn("Sunday snack", body)
            self.assertNotIn("Previous snack", body)
            self.assertIn('action="/consumption-events/correct"', body)
            self.assertIn('name="revision" type="hidden" value="1"', body)
            self.assertIn('action="/consumption-events/delete"', body)
            self.assertIn("Remove this Consumption Event?", body)
            self.assertIn("Calories</dt><dd>200</dd>", body)
            self.assertIn("Protein</dt><dd>5.5 g</dd>", body)
            self.assertIn("Carbohydrates</dt><dd>8.5 g</dd>", body)
            self.assertIn("Fat</dt><dd>4.5 g</dd>", body)
            self.assertIn(f"week={monday - timedelta(days=7):%Y-%m-%d}", body)
            self.assertNotIn(f"week={monday + timedelta(days=7):%Y-%m-%d}", body)

            future_body = b"".join(
                application(
                    {
                        "PATH_INFO": "/",
                        "REQUEST_METHOD": "GET",
                        "QUERY_STRING": f"week={monday + timedelta(days=7):%Y-%m-%d}",
                    },
                    lambda status, headers: None,
                )
            ).decode("utf-8")
            self.assertIn("Monday snack", future_body)
            self.assertNotIn("Previous snack", future_body)

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
            self.assertIn("Schema 3", body)
            self.assertIn('action="/consumption-events"', body)
            self.assertIn('name="food"', body)
            self.assertIn('name="quantity"', body)
            self.assertIn('name="measure"', body)
            self.assertIn('name="day"', body)
            self.assertIn('id="add-food"', body)
            self.assertIn('id="report-item-template"', body)
            self.assertIn("Create Consumption Report", body)
            self.assertIn('href="/consumption-events/export"', body)
            self.assertIn('id="history-import-file"', body)
            self.assertIn('id="import-history"', body)

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
                    "schema_version": 3,
                },
            )


if __name__ == "__main__":
    unittest.main()