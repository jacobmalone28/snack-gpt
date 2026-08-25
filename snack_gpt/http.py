from collections.abc import Callable, Iterable
from html import escape
import json
from typing import TypeAlias

from snack_gpt.config import Settings
from snack_gpt.storage import Storage


StartResponse: TypeAlias = Callable[[str, list[tuple[str, str]]], object]
Application: TypeAlias = Callable[[dict[str, object], StartResponse], Iterable[bytes]]


def create_application(settings: Settings) -> Application:
    with Storage(settings.database_path) as storage:
        storage.initialize()

    def application(
        environment: dict[str, object], start_response: StartResponse
    ) -> Iterable[bytes]:
        path = str(environment.get("PATH_INFO", "/"))
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