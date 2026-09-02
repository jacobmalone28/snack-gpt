from collections.abc import Callable, Iterable
from http.cookies import CookieError, SimpleCookie
from datetime import date, timedelta
from html import escape
import json
from math import ceil
from threading import Lock
import time
from typing import BinaryIO, TypeAlias, cast
from urllib.parse import parse_qs

from snack_gpt.auth import new_session_token, session_token_hash, verify_password
from snack_gpt.config import ConfigurationError, Settings
from snack_gpt.history_transfer import HistoryImportError, export_history, import_history
from snack_gpt.ingestion import (
    ConsumptionEventConflict,
    ConsumptionReportItem,
    IngestionError,
    UsdaSearch,
    correct_consumption_event,
    create_consumption_report,
)
from snack_gpt.storage import ConsumptionEvent, Storage
from snack_gpt.usda import FoodDataCentralSearch


StartResponse: TypeAlias = Callable[[str, list[tuple[str, str]]], object]
Application: TypeAlias = Callable[[dict[str, object], StartResponse], Iterable[bytes]]
_SESSION_COOKIE = "snack_gpt_session"
_SESSION_DURATION_SECONDS = 12 * 60 * 60
_MAX_LOGIN_BACKOFF_SECONDS = 60
_LOGIN_ATTEMPT_WINDOW_SECONDS = 5 * 60


class _LoginThrottle:
    def __init__(self) -> None:
        self._failures: dict[str, tuple[int, float, float]] = {}
        self._lock = Lock()

    def retry_after(self, client: str, now: float) -> int:
        with self._lock:
            attempt = self._failures.get(client)
            if attempt is None:
                return 0
            _, blocked_until, _ = attempt
            return max(0, ceil(blocked_until - now))

    def record_failure(self, client: str, now: float) -> None:
        with self._lock:
            failure_count, _, last_failure = self._failures.get(client, (0, 0, 0))
            if now - last_failure > _LOGIN_ATTEMPT_WINDOW_SECONDS:
                failure_count = 0
            backoff = min(2**failure_count, _MAX_LOGIN_BACKOFF_SECONDS)
            self._failures[client] = (failure_count + 1, now + backoff, now)

    def record_success(self, client: str) -> None:
        with self._lock:
            self._failures.pop(client, None)


def create_application(settings: Settings, usda_search: UsdaSearch | None = None) -> Application:
    login_throttle = _LoginThrottle()
    configured_usda_search = usda_search
    if configured_usda_search is None and settings.usda_api_key:
        configured_usda_search = FoodDataCentralSearch(settings.usda_api_key)

    with Storage(settings.database_path) as storage:
        storage.initialize()
        if settings.authentication_required and storage.owner_password_hash() is None:
            raise ConfigurationError(
                "LAN access requires an owner password; run snack-gpt set-password first"
            )

    def application(
        environment: dict[str, object], start_response: StartResponse
    ) -> Iterable[bytes]:
        path = str(environment.get("PATH_INFO", "/"))
        method = str(environment.get("REQUEST_METHOD", "GET"))
        if settings.authentication_required:
            start_response = _no_store(start_response)
            if path == "/login" and method == "GET":
                return _login_response(start_response, "200 OK")
            if path == "/login" and method == "POST":
                client = str(environment.get("REMOTE_ADDR", "unknown"))
                now = time.monotonic()
                retry_after = login_throttle.retry_after(client, now)
                if retry_after:
                    return _login_response(
                        start_response,
                        "429 Too Many Requests",
                        "Login temporarily unavailable.",
                        retry_after,
                    )
                form = parse_qs(
                    _request_body(environment).decode("utf-8"),
                    keep_blank_values=True,
                )
                with Storage(settings.database_path) as storage:
                    password_hash = storage.owner_password_hash()
                    if password_hash is None or not verify_password(
                        _form_value(form, "password"), password_hash
                    ):
                        login_throttle.record_failure(client, now)
                        return _login_response(
                            start_response, "401 Unauthorized", "Login failed."
                        )
                    token = new_session_token()
                    session_created = storage.create_owner_session(
                        session_token_hash(token),
                        int(time.time()) + _SESSION_DURATION_SECONDS,
                        password_hash,
                    )
                    if not session_created:
                        return _login_response(
                            start_response, "401 Unauthorized", "Login failed."
                        )
                login_throttle.record_success(client)
                return _redirect_response(
                    start_response,
                    "/",
                    _session_cookie(token, environment),
                )

            token = _session_token(environment)
            with Storage(settings.database_path) as storage:
                authenticated = token is not None and storage.owner_session_is_valid(
                    session_token_hash(token), int(time.time())
                )
            if not authenticated:
                return _login_response(start_response, "401 Unauthorized")
            if path == "/logout" and method == "POST":
                assert token is not None
                with Storage(settings.database_path) as storage:
                    storage.delete_owner_session(session_token_hash(token))
                return _redirect_response(
                    start_response,
                    "/login",
                    f"{_SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0",
                )

        if path == "/consumption-events/export" and method == "GET":
            with Storage(settings.database_path) as storage:
                document = export_history(storage)
            start_response(
                "200 OK",
                [
                    ("Content-Type", "application/json; charset=utf-8"),
                    ("Content-Length", str(len(document))),
                    (
                        "Content-Disposition",
                        'attachment; filename="snack-gpt-history.json"',
                    ),
                ],
            )
            return [document]

        if path == "/consumption-events/import" and method == "POST":
            content_type = str(environment.get("CONTENT_TYPE", "")).partition(";")[0]
            if content_type != "application/json":
                return _plain_response(
                    start_response,
                    "415 Unsupported Media Type",
                    "History import must be JSON.\n",
                )
            try:
                with Storage(settings.database_path) as storage:
                    result = import_history(storage, _request_body(environment))
            except HistoryImportError as error:
                return _plain_response(
                    start_response, "422 Unprocessable Entity", f"{error}\n"
                )
            return _json_response(
                start_response,
                {
                    "imported": result.imported_count,
                    "skipped": result.skipped_count,
                    "conflicts": list(result.conflict_ids),
                },
            )

        if path in {"/consumption-events/correct", "/consumption-events/delete"} and method == "POST":
            form = parse_qs(
                _request_body(environment).decode("utf-8"), keep_blank_values=True
            )
            event_id = _form_value(form, "event_id")
            corrected_description: str | None = None
            try:
                expected_revision = _form_revision(form)
                with Storage(settings.database_path) as storage:
                    if path == "/consumption-events/correct":
                        event = correct_consumption_event(
                            storage,
                            configured_usda_search,
                            event_id=event_id,
                            expected_revision=expected_revision,
                            food=_form_value(form, "food"),
                            quantity=_form_value(form, "quantity"),
                            measure=_form_value(form, "measure"),
                            day=_form_value(form, "day"),
                        )
                        corrected_description = event.food_description
                    else:
                        if _form_value(form, "confirmed") != "yes":
                            raise IngestionError("Confirm deletion before removing the event.")
                        if not storage.delete_consumption_event(
                            event_id, expected_revision
                        ):
                            raise ConsumptionEventConflict(
                                "Consumption Event changed; refresh and try again."
                            )
            except ConsumptionEventConflict as error:
                return _plain_response(start_response, "409 Conflict", f"{error}\n")
            except IngestionError as error:
                return _plain_response(
                    start_response, "422 Unprocessable Entity", f"{error}\n"
                )
            if path == "/consumption-events/correct":
                assert corrected_description is not None
                return _plain_response(
                    start_response,
                    "200 OK",
                    f"Corrected Consumption Event for {corrected_description}.\n",
                )
            return _plain_response(
                start_response, "200 OK", "Removed Consumption Event.\n"
            )

        if path == "/consumption-events" and method == "POST":
            if configured_usda_search is None:
                return _plain_response(
                    start_response,
                    "503 Service Unavailable",
                    "USDA food search is not configured.\n",
                )
            request_body = _request_body(environment)
            form = parse_qs(request_body.decode("utf-8"), keep_blank_values=True)
            try:
                items = _report_items(form)
                with Storage(settings.database_path) as storage:
                    events = create_consumption_report(
                        storage,
                        configured_usda_search,
                        items=items,
                        day=_form_value(form, "day"),
                    )
            except IngestionError as error:
                return _plain_response(start_response, "422 Unprocessable Entity", f"{error}\n")
            if len(events) == 1:
                message = f"Created Consumption Event for {events[0].food_description}.\n"
            else:
                message = f"Created {len(events)} Consumption Events.\n"
            return _plain_response(
                start_response,
                "201 Created",
                message,
            )

        if path not in {"/", "/health"}:
            body = b"Not found\n"
            start_response(
                "404 Not Found",
                [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(body)))],
            )
            return [body]

        with Storage(settings.database_path) as storage:
            health = storage.health()
            current_week = _calendar_week_start(date.today())
            requested_week = _query_value(environment, "week")
            selected_week = _calendar_week_start(_parse_date(requested_week, date.today()))
            selected_week = min(selected_week, current_week)
            events = [
                event
                for event in storage.list_consumption_events()
                if selected_week <= event.day <= selected_week + timedelta(days=6)
            ]

        storage_status = "Storage healthy" if health.writable else "Storage read-only"
        if path == "/health":
            body = json.dumps(
                {
                    "application": "ready",
                    "storage": "healthy" if health.writable else "read-only",
                    "schema_version": health.schema_version,
                },
                separators=(",", ":"),
            ).encode()
            start_response(
                "200 OK",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(body))),
                ],
            )
            return [body]

        totals = _nutrition_totals(events)
        previous_week = selected_week - timedelta(days=7)
        next_week = selected_week + timedelta(days=7)
        previous_link = f'<a href="/?week={previous_week.isoformat()}">Previous week</a>'
        next_link = (
            f'<a href="/?week={next_week.isoformat()}">Next week</a>'
            if next_week <= current_week
            else ""
        )
        current_link = (
            '<a href="/">Current week</a>'
            if selected_week < current_week
            else ""
        )
        days = "".join(
            _render_day(selected_week + timedelta(days=offset), events)
            for offset in range(7)
        )
        logout_form = (
            '<form action="/logout" method="post"><button type="submit">Log out</button></form>'
            if settings.authentication_required
            else ""
        )
        home_page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Snack-GPT status</title>
  <style>
    :root {{ color-scheme: light; font-family: Georgia, serif; background: #f3f0e8; color: #18211b; }}
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; }}
    main {{ width: min(34rem, calc(100% - 2rem)); border-top: 5px solid #d54b2a; padding: 2rem 0; }}
    h1 {{ font-size: clamp(2.5rem, 10vw, 5rem); margin: 0 0 2rem; letter-spacing: 0; }}
    dl {{ display: grid; grid-template-columns: 1fr auto; gap: 0.75rem 2rem; border-block: 1px solid #a8a396; padding: 1.25rem 0; }}
    dt {{ font-weight: 700; }} dd {{ margin: 0; }}
    .ready {{ color: #17653a; }}
    form {{ display: grid; gap: 1rem; margin-top: 2rem; }}
    fieldset {{ border: 0; margin: 0; padding: 0; }}
    legend {{ font-size: 1.25rem; font-weight: 700; margin-bottom: 1rem; }}
    .report-item {{ display: grid; grid-template-columns: 2fr 1fr 1fr auto; gap: 1rem; margin-bottom: 1rem; align-items: end; }}
    .event {{ margin-bottom: 1.5rem; }}
    .event-edit {{ display: grid; grid-template-columns: 2fr 1fr 1fr 1.3fr auto; gap: 0.5rem; margin-top: 0.5rem; align-items: end; }}
    .event-delete {{ display: block; margin-top: 0.5rem; }}
    .event-edit button, .event-delete button {{ padding: 0.7rem; }}
    label {{ display: grid; gap: 0.4rem; font-weight: 700; }}
    input {{ box-sizing: border-box; width: 100%; padding: 0.7rem; border: 1px solid #767268; background: #fff; font: inherit; }}
    button {{ padding: 0.8rem; border: 0; background: #18211b; color: #fff; font: inherit; font-weight: 700; cursor: pointer; }}
    .secondary {{ justify-self: start; background: transparent; color: #18211b; border: 1px solid #767268; }}
    nav {{ display: flex; justify-content: space-between; gap: 1rem; margin-top: 2rem; }}
    nav a {{ color: #a33a22; font-weight: 700; }}
    section {{ margin-top: 2rem; border-block: 1px solid #a8a396; padding: 1.25rem 0; }}
    section div {{ display: flex; align-items: end; gap: 1rem; flex-wrap: wrap; }}
    section a {{ color: #a33a22; font-weight: 700; }}
    section h2 {{ margin-bottom: 0.5rem; }}
    ul {{ padding-left: 1.25rem; }}
    @media (max-width: 32rem) {{ .report-item, .event-edit {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <h1>Snack-GPT</h1>
        {logout_form}
    <dl>
      <dt>Application</dt><dd class="ready">Application ready</dd>
      <dt>Storage</dt><dd>{escape(storage_status)}</dd>
      <dt>Database</dt><dd>Schema {health.schema_version}</dd>
    </dl>
        <section>
            <h2>Calendar Week: {_date_label(selected_week)} - {_date_label(selected_week + timedelta(days=6))}</h2>
            <nav>{previous_link}{current_link}{next_link}</nav>
            {days}
            <h2>Weekly Nutrition Totals</h2>
            <dl>
                <dt>Calories</dt><dd>{totals[0]:.0f}</dd>
                <dt>Protein</dt><dd>{totals[1]:.1f} g</dd>
                <dt>Carbohydrates</dt><dd>{totals[2]:.1f} g</dd>
                <dt>Fat</dt><dd>{totals[3]:.1f} g</dd>
            </dl>
        </section>
        <section>
            <h2>History backup</h2>
            <div>
                <a href="/consumption-events/export" download>Export history</a>
                <label>Import history <input id="history-import-file" type="file" accept="application/json,.json"></label>
                <button id="import-history" type="button">Import</button>
            </div>
            <p id="history-import-status" role="status"></p>
        </section>
        <form action="/consumption-events" method="post">
            <fieldset>
                <legend>Consumption Report</legend>
                <div id="report-items">
                    <div class="report-item">
                        <label>Food <input name="food" type="search" required></label>
                        <label>Quantity <input name="quantity" type="number" min="0.01" step="any" required></label>
                        <label>Measure <input name="measure" value="grams" required></label>
                    </div>
                </div>
                <button class="secondary" id="add-food" type="button">Add food</button>
            </fieldset>
            <label>Day <input name="day" type="date" value="{date.today().isoformat()}" max="{date.today().isoformat()}" required></label>
            <button type="submit">Create Consumption Report</button>
        </form>
        <template id="report-item-template">
            <div class="report-item">
                <label>Food <input name="food" type="search" required></label>
                <label>Quantity <input name="quantity" type="number" min="0.01" step="any" required></label>
                <label>Measure <input name="measure" value="grams" required></label>
                <button class="secondary remove-food" type="button">Remove</button>
            </div>
        </template>
        <script>
            const reportItems = document.querySelector("#report-items");
            const itemTemplate = document.querySelector("#report-item-template");
            document.querySelector("#add-food").addEventListener("click", () => {{
                reportItems.append(itemTemplate.content.cloneNode(true));
            }});
            reportItems.addEventListener("click", (event) => {{
                if (event.target instanceof Element && event.target.matches(".remove-food")) {{
                    event.target.closest(".report-item").remove();
                }}
            }});
            document.querySelector("#import-history").addEventListener("click", async () => {{
                const file = document.querySelector("#history-import-file").files[0];
                const status = document.querySelector("#history-import-status");
                if (!file) {{
                    status.textContent = "Choose a history JSON file.";
                    return;
                }}
                const response = await fetch("/consumption-events/import", {{
                    method: "POST",
                    headers: {{"Content-Type": "application/json"}},
                    body: await file.text(),
                }});
                if (!response.ok) {{
                    status.textContent = await response.text();
                    return;
                }}
                const result = await response.json();
                const conflicts = result.conflicts.length
                    ? ` Conflicts: ${{result.conflicts.join(", ")}}.`
                    : "";
                status.textContent = `Imported ${{result.imported}}; skipped ${{result.skipped}}.${{conflicts}}`;
            }});
        </script>
  </main>
</body>
</html>
""".encode()
        start_response(
            "200 OK",
            [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", str(len(home_page))),
            ],
        )
        return [home_page]

    return application


def _login_response(
    start_response: StartResponse,
    status: str,
    error: str = "",
    retry_after: int | None = None,
) -> Iterable[bytes]:
    error_markup = f'<p role="alert">{escape(error)}</p>' if error else ""
    body = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Snack-GPT login</title></head>
<body><main><h1>Snack-GPT</h1>{error_markup}<form action="/login" method="post"><label>Owner password <input name="password" type="password" required autocomplete="current-password"></label><button type="submit">Log in</button></form></main></body>
</html>
""".encode()
    headers = [
        ("Content-Type", "text/html; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
    ]
    if retry_after is not None:
        headers.append(("Retry-After", str(retry_after)))
    start_response(status, headers)
    return [body]


def _no_store(start_response: StartResponse) -> StartResponse:
    def no_store_response(status: str, headers: list[tuple[str, str]]) -> object:
        uncached_headers = [
            header for header in headers if header[0].lower() != "cache-control"
        ]
        uncached_headers.append(("Cache-Control", "no-store"))
        return start_response(status, uncached_headers)

    return no_store_response


def _redirect_response(
    start_response: StartResponse, location: str, cookie: str
) -> Iterable[bytes]:
    start_response(
        "303 See Other",
        [
            ("Location", location),
            ("Set-Cookie", cookie),
            ("Content-Length", "0"),
            ("Cache-Control", "no-store"),
        ],
    )
    return [b""]


def _session_token(environment: dict[str, object]) -> str | None:
    cookies = SimpleCookie()
    try:
        cookies.load(str(environment.get("HTTP_COOKIE", "")))
    except CookieError:
        return None
    session = cookies.get(_SESSION_COOKIE)
    return session.value if session is not None else None


def _session_cookie(token: str, environment: dict[str, object]) -> str:
    attributes = [
        f"{_SESSION_COOKIE}={token}",
        "Path=/",
        "HttpOnly",
        "SameSite=Strict",
        f"Max-Age={_SESSION_DURATION_SECONDS}",
    ]
    if environment.get("wsgi.url_scheme") == "https":
        attributes.append("Secure")
    return "; ".join(attributes)


def _plain_response(
    start_response: StartResponse, status: str, text: str
) -> Iterable[bytes]:
    body = text.encode()
    start_response(
        status,
        [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(body)))],
    )
    return [body]


def _json_response(
    start_response: StartResponse, payload: dict[str, object]
) -> Iterable[bytes]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    start_response(
        "200 OK",
        [("Content-Type", "application/json"), ("Content-Length", str(len(body)))],
    )
    return [body]


def _request_body(environment: dict[str, object]) -> bytes:
    content_length = int(str(environment.get("CONTENT_LENGTH", "0") or "0"))
    request_stream = cast(BinaryIO, environment["wsgi.input"])
    return request_stream.read(content_length)


def _form_value(form: dict[str, list[str]], name: str) -> str:
    return form.get(name, [""])[0]


def _form_revision(form: dict[str, list[str]]) -> int:
    try:
        revision = int(_form_value(form, "revision"))
    except ValueError as error:
        raise IngestionError("Consumption Event revision is invalid.") from error
    if revision < 1:
        raise IngestionError("Consumption Event revision is invalid.")
    return revision


def _report_items(form: dict[str, list[str]]) -> list[ConsumptionReportItem]:
    foods = form.get("food", [])
    quantities = form.get("quantity", [])
    measures = form.get("measure", [])
    if not foods or len(foods) != len(quantities) or len(foods) != len(measures):
        raise IngestionError("Each food needs one quantity and measure.")
    return [
        ConsumptionReportItem(food, quantity, measure)
        for food, quantity, measure in zip(foods, quantities, measures, strict=True)
    ]


def _query_value(environment: dict[str, object], name: str) -> str:
    query_string = str(environment.get("QUERY_STRING", ""))
    return parse_qs(query_string, keep_blank_values=True).get(name, [""])[0]


def _parse_date(value: str, fallback: date) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return fallback


def _calendar_week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _nutrition_totals(events: list[ConsumptionEvent]) -> tuple[float, float, float, float]:
    calories = protein = carbohydrates = fat = 0.0
    for event in events:
        nutrition = event.nutrition
        calories += nutrition.calories
        protein += nutrition.protein
        carbohydrates += nutrition.carbohydrates
        fat += nutrition.fat
    return calories, protein, carbohydrates, fat


def _render_day(day: date, events: list[ConsumptionEvent]) -> str:
    day_events = [event for event in events if event.day == day]
    event_markup = "".join(
        f'<li class="event"><strong>{escape(event.food_description)}</strong>: '
        f"{event.quantity_value:g} {escape(event.quantity_measure)}"
        f'<form class="event-edit" action="/consumption-events/correct" method="post">'
        f'<input name="event_id" type="hidden" value="{escape(event.event_id)}">'
        f'<input name="revision" type="hidden" value="{event.revision}">'
        f'<label>Food <input name="food" type="search" value="{escape(event.food_description)}" required></label>'
        f'<label>Quantity <input name="quantity" type="number" min="0.01" step="any" value="{event.quantity_value:g}" required></label>'
        f'<label>Measure <input name="measure" value="{escape(event.quantity_measure)}" required></label>'
        f'<label>Day <input name="day" type="date" value="{event.day.isoformat()}" max="{date.today().isoformat()}" required></label>'
        f'<button type="submit">Save</button></form>'
        f'<form class="event-delete" action="/consumption-events/delete" method="post" '
        f'onsubmit="return confirm(\'Remove this Consumption Event?\')">'
        f'<input name="event_id" type="hidden" value="{escape(event.event_id)}">'
        f'<input name="revision" type="hidden" value="{event.revision}">'
        f'<input name="confirmed" type="hidden" value="yes">'
        f'<button type="submit">Delete</button></form></li>'
        for event in day_events
    )
    return (
        f"<h3>{_date_label(day)}</h3>"
        f"<ul>{event_markup or '<li>No Consumption Events</li>'}</ul>"
    )


def _date_label(day: date) -> str:
    return day.strftime("%A, %b %d, %Y").replace(" 0", " ")
