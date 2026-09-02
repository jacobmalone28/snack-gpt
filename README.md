# Snack-GPT

Snack-GPT is a local, single-person food logger with a server-rendered web interface backed by SQLite.

## Requirements

- Python 3.11 or newer

## Run locally

Install the project and create local configuration:

```console
python3 -m pip install -e .
cp .env.example .env
```

Set `USDA_FDC_API_KEY` in `.env`, then check configuration and initialize the database:

```console
python3 -m snack_gpt check
```

Start the local web application:

```console
python3 -m snack_gpt serve
```

Open <http://127.0.0.1:8000/> in a browser. Machine-readable health is available at <http://127.0.0.1:8000/health>.

## Optional LAN access

Snack-GPT listens only on `127.0.0.1` by default. To make it available on a
trusted local network, first initialize the single owner password locally:

```console
python3 -m snack_gpt set-password
```

Then set `SNACK_GPT_HOST=0.0.0.0` (or a specific LAN address) and run the
server. Every web route, including health and history export, requires login in
LAN mode. Passwords are stored as scrypt hashes. Browser sessions use random,
revocable `HttpOnly`, `SameSite=Strict` cookies; HTTPS requests also receive the
`Secure` flag. Running `set-password` again changes the password and signs out
all existing sessions.

## Back up history

The local web interface can download all Consumption Events as a versioned JSON
file and import that file without USDA access. Re-importing unchanged events
skips them. If a stable event ID already exists with different data, the import
reports the conflict and preserves the local Consumption Event.

## Configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `SNACK_GPT_DATABASE` | `snack-gpt.sqlite3` | SQLite database path |
| `SNACK_GPT_HOST` | `127.0.0.1` | Web server bind address; non-loopback values enable required authentication |
| `SNACK_GPT_PORT` | `8000` | Web server port |
| `USDA_FDC_API_KEY` | none | USDA FoodData Central API key required to create Consumption Events |

Invalid values fail before the database or server is opened. Keep the default host unless LAN access has been configured and secured.
Values exported in the shell take precedence over values in `.env`. The `.env` file is ignored by Git; use `.env.example` as the checked-in template.

## Raspberry Pi voice acceptance

The reproducible on-device procedure and manifest are in
[`docs/voice-probe.md`](docs/voice-probe.md). The probe runs all local inference
stages without network access and records their timings and peak memory.