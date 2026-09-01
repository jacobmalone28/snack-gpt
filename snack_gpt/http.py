from collections.abc import Callable, Iterable
from datetime import date, timedelta
from html import escape
import json
from typing import BinaryIO, TypeAlias, cast
from urllib.parse import parse_qs

from snack_gpt.config import Settings
from snack_gpt.history_transfer import HistoryImportError, export_history, import_history
from snack_gpt.ingestion import IngestionError, UsdaSearch, create_consumption_event
from snack_gpt.storage import ConsumptionEvent, Storage
from snack_gpt.usda import FoodDataCentralSearch


StartResponse: TypeAlias = Callable[[str, list[tuple[str, str]]], object]
Application: TypeAlias = Callable[[dict[str, object], StartResponse], Iterable[bytes]]


def create_application(settings: Settings, usda_search: UsdaSearch | None = None) -> Application:
    configured_usda_search = usda_search
    if configured_usda_search is None and settings.usda_api_key:
        configured_usda_search = FoodDataCentralSearch(settings.usda_api_key)

    with Storage(settings.database_path) as storage:
        storage.initialize()

    def application(
        environment: dict[str, object], start_response: StartResponse
    ) -> Iterable[bytes]:
        path = str(environment.get("PATH_INFO", "/"))
        method = str(environment.get("REQUEST_METHOD", "GET"))
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
                with Storage(settings.database_path) as storage:
                    event = create_consumption_event(
                        storage,
                        configured_usda_search,
                        food=_form_value(form, "food"),
                        quantity=_form_value(form, "quantity"),
                        measure=_form_value(form, "measure"),
                        day=_form_value(form, "day"),
                    )
            except IngestionError as error:
                return _plain_response(start_response, "422 Unprocessable Entity", f"{error}\n")
            return _plain_response(
                start_response,
                "201 Created",
                f"Created Consumption Event for {event.food_description}.\n",
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
    form {{ display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 1rem; margin-top: 2rem; }}
    label {{ display: grid; gap: 0.4rem; font-weight: 700; }}
    label:first-child, label:last-of-type, button {{ grid-column: 1 / -1; }}
    input {{ box-sizing: border-box; width: 100%; padding: 0.7rem; border: 1px solid #767268; background: #fff; font: inherit; }}
    button {{ padding: 0.8rem; border: 0; background: #18211b; color: #fff; font: inherit; font-weight: 700; cursor: pointer; }}
    nav {{ display: flex; justify-content: space-between; gap: 1rem; margin-top: 2rem; }}
    nav a {{ color: #a33a22; font-weight: 700; }}
    section {{ margin-top: 2rem; border-block: 1px solid #a8a396; padding: 1.25rem 0; }}
    section div {{ display: flex; align-items: end; gap: 1rem; flex-wrap: wrap; }}
    section a {{ color: #a33a22; font-weight: 700; }}
    section h2 {{ margin-bottom: 0.5rem; }}
    ul {{ padding-left: 1.25rem; }}
    @media (max-width: 32rem) {{ form {{ grid-template-columns: 1fr; }} label, label:first-child, label:last-of-type, button {{ grid-column: 1; }} }}
  </style>
</head>
<body>
  <main>
    <h1>Snack-GPT</h1>
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
            <label>Food <input name="food" type="search" required></label>
            <label>Quantity <input name="quantity" type="number" min="0.01" step="any" required></label>
            <label>Measure <input name="measure" value="grams" required></label>
            <label>Day <input name="day" type="date" value="{date.today().isoformat()}" max="{date.today().isoformat()}" required></label>
            <button type="submit">Create Consumption Event</button>
        </form>
        <script>
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
        f"<li>{escape(event.food_description)}: {event.quantity_value:g} "
        f"{escape(event.quantity_measure)}</li>"
        for event in day_events
    )
    return (
        f"<h3>{_date_label(day)}</h3>"
        f"<ul>{event_markup or '<li>No Consumption Events</li>'}</ul>"
    )


def _date_label(day: date) -> str:
    return day.strftime("%A, %b %d, %Y").replace(" 0", " ")