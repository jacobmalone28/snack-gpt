from collections.abc import Callable, Iterable
from datetime import date
from html import escape
import json
from typing import BinaryIO, TypeAlias, cast
from urllib.parse import parse_qs

from snack_gpt.config import Settings
from snack_gpt.ingestion import (
    ConsumptionReportItem,
    IngestionError,
    UsdaSearch,
    create_consumption_report,
)
from snack_gpt.storage import Storage
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
        if path == "/consumption-events" and method == "POST":
            if configured_usda_search is None:
                return _plain_response(
                    start_response,
                    "503 Service Unavailable",
                    "USDA food search is not configured.\n",
                )
            content_length = int(str(environment.get("CONTENT_LENGTH", "0") or "0"))
            request_stream = cast(BinaryIO, environment["wsgi.input"])
            request_body = request_stream.read(content_length)
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
    label {{ display: grid; gap: 0.4rem; font-weight: 700; }}
    input {{ box-sizing: border-box; width: 100%; padding: 0.7rem; border: 1px solid #767268; background: #fff; font: inherit; }}
    button {{ padding: 0.8rem; border: 0; background: #18211b; color: #fff; font: inherit; font-weight: 700; cursor: pointer; }}
    .secondary {{ justify-self: start; background: transparent; color: #18211b; border: 1px solid #767268; }}
    @media (max-width: 32rem) {{ .report-item {{ grid-template-columns: 1fr; }} }}
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


def _form_value(form: dict[str, list[str]], name: str) -> str:
    return form.get(name, [""])[0]


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