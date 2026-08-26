# Snack-GPT

Snack-GPT is a local, single-person food logger with a server-rendered web interface backed by SQLite.

## Requirements

- Python 3.11 or newer

## Run locally

Check configuration and initialize the database:

```console
python -m snack_gpt check
```

Start the local web application:

```console
export USDA_FDC_API_KEY="your-api-key"
python -m snack_gpt serve
```

Open <http://127.0.0.1:8000/> in a browser. Machine-readable health is available at <http://127.0.0.1:8000/health>.

## Configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `SNACK_GPT_DATABASE` | `snack-gpt.sqlite3` | SQLite database path |
| `SNACK_GPT_HOST` | `127.0.0.1` | Web server bind address |
| `SNACK_GPT_PORT` | `8000` | Web server port |
| `USDA_FDC_API_KEY` | none | USDA FoodData Central API key required to create Consumption Events |

Invalid values fail before the database or server is opened. Keep the default host unless LAN access has been configured and secured.

## Raspberry Pi voice acceptance

The reproducible on-device procedure and manifest are in
[`docs/voice-probe.md`](docs/voice-probe.md). The probe runs all local inference
stages without network access and records their timings and peak memory.