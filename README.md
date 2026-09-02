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

## Listen for voice reports

Set `SNACK_GPT_VOICE_MANIFEST` to a JSON manifest containing local command
arrays and a `memory_directory`. The directory must be backed only by memory,
not persistent storage, because native voice tools exchange audio and transcript
data there. Use a tmpfs such as `/dev/shm` on Linux or a provisioned RAM-disk
mount on macOS and Windows. Snack-GPT rejects a missing directory but cannot
verify how the operating system mounted it.

Commands are executed directly without a shell and must obey these contracts:

| Command | Contract |
| --- | --- |
| `wake_capture` | Write a non-empty audio clip to `{audio}`. |
| `wake_detection` | Read `{audio}` and write JSON containing `{"detected": true/false}` to `{output}`. |
| `speech_capture` | Write non-empty report audio to `{audio}`, ending after approximately `{silence_seconds}` of silence; Snack-GPT terminates it after 15 seconds. |
| `transcription` | Read `{audio}` and write a non-blank UTF-8 transcript to `{output}`. |
| `extraction` | Read `{transcript}` and write `{"foods":[{"food":"egg","quantity":1,"measure":"large"}],"confidence":0.95}` to `{output}`. Preserve repeated foods and include confidence from zero to one. |
| `success_sound` / `error_sound` | Play the corresponding sound and exit when playback finishes. |
| `speech_synthesis` | Synthesize `{text}` and write non-empty audio to `{output}`. |
| `play_speech` | Play `{audio}` and exit when playback finishes. |

For example:

```json
{
	"memory_directory": "/dev/shm",
	"commands": {
		"wake_capture": ["voice-capture", "--wake", "--output", "{audio}"],
		"wake_detection": ["openwakeword-probe", "--model", "/opt/snack-gpt/models/hey_jarvis_v0.1.onnx", "--audio", "{audio}", "--output", "{output}"],
		"speech_capture": ["voice-capture", "--until-silence", "{silence_seconds}", "--output", "{audio}"],
		"transcription": ["whisper-probe", "--binary", "/opt/snack-gpt/bin/whisper-cli", "--model", "/opt/snack-gpt/models/ggml-tiny.en.bin", "--audio", "{audio}", "--output", "{output}"],
		"extraction": ["needle-probe", "--library", "/opt/snack-gpt/lib/libneedle.so", "--transcript", "{transcript}", "--output", "{output}"],
		"success_sound": ["voice-play", "success.wav"],
		"error_sound": ["voice-play", "error.wav"],
		"speech_synthesis": ["piper-probe", "--socket", "/run/snack-gpt/piper.sock", "--text", "{text}", "--output", "{output}"],
		"play_speech": ["voice-play", "{audio}"]
	}
}
```

Start the continuous listener with:

```console
python3 -m snack_gpt listen
```

Run `serve` and `listen` with the same `SNACK_GPT_DATABASE`. The web interface
shows listening, paused, processing, USDA unavailable, audio unavailable, or
configuration error without exposing voice content or runtime details. Its
pause and resume control is shared with the listener and remains effective
across browser refreshes and process restarts. During a USDA outage, creation
and food or Food Quantity corrections are disabled; history, totals, date-only
correction, deletion, export, and import remain available.

Wake detection pauses while each report is transcribed, extracted, sent to
USDA, stored, and acknowledged. Speech capture is stopped after 15 seconds and
processing shares a 30-second deadline. Audio, transcripts, extractions, and
synthesized feedback remain in the memory-backed directory and are removed
after every report.

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
`Secure` flag. Failed logins receive per-client progressive backoff. Running
`set-password` again changes the password and signs out all existing sessions.

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
| `SNACK_GPT_VOICE_MANIFEST` | none | JSON command manifest used by `snack-gpt listen` |

Invalid values fail before the database or server is opened. Keep the default host unless LAN access has been configured and secured.
Values exported in the shell take precedence over values in `.env`. The `.env` file is ignored by Git; use `.env.example` as the checked-in template.

## Raspberry Pi voice acceptance

The reproducible on-device procedure and manifest are in
[`docs/voice-probe.md`](docs/voice-probe.md). The probe runs all local inference
stages without network access and records their timings and peak memory.