# Raspberry Pi voice runtime probe

The voice probe exercises provisioned OpenWakeWord, whisper.cpp with Whisper
`tiny.en`, Needle, and Piper on a Raspberry Pi 3B+. It executes every stage in a
network namespace, records stage timing and peak resident memory, and writes a
JSON acceptance report.

## Provision

On a Raspberry Pi 3B+ running 64-bit Raspberry Pi OS Lite, check out this
repository and run:

```console
sudo scripts/provision-voice-probe.sh --accept-model-licenses
```

The script installs system packages, creates `/opt/snack-gpt`, installs pinned
Python runtimes, builds pinned whisper.cpp source, downloads all models, installs
the adapters, and records a 16 kHz mono WAV fixture. At the recording prompt,
say "Hey Jarvis, I ate two eggs."

When one hardware capture device is present, the script selects it instead of
using ALSA's potentially playback-only `default` mapping. To choose from
multiple devices, list them with `arecord --list-devices` and pass the card and
device numbers explicitly:

```console
sudo scripts/provision-voice-probe.sh --accept-model-licenses \
  --capture-device plughw:1,0
```

To use an existing 16-bit, 16 kHz mono PCM WAV instead:

```console
sudo scripts/provision-voice-probe.sh --accept-model-licenses \
  --fixture /path/to/report.wav
```

If provisioning already completed the installs but failed while opening the
default microphone, record the fixture directly instead of rebuilding:

```console
arecord --list-devices
sudo arecord --device=plughw:1,0 --duration=7 --format=S16_LE \
  --rate=16000 --channels=1 --file-type=wav /opt/snack-gpt/probe/report.wav
sudo chmod a+r /opt/snack-gpt/probe/report.wav
```

Replace `1,0` with the listed capture card and device numbers.

Provisioning requires a network connection. The acceptance probe itself runs
every inference stage without one. Review
[`voice-provisioning-research.md`](voice-provisioning-research.md) before
accepting the OpenWakeWord and Piper model licenses.

Each installed runtime adapter uses the command line shown in
[`voice-probe.pi.json`](voice-probe.pi.json) and writes these artifacts:

| Stage | Artifact contract |
| --- | --- |
| OpenWakeWord | JSON containing `{"detected": true}` |
| whisper.cpp | UTF-8 transcript text |
| Needle | JSON containing the configured expected extraction |
| Piper | Non-empty WAV audio |

The adapters only normalize native runtime input and output. The manifest lists
each adapter, native binary, model, and fixture in `evidence_files`; the result
records a SHA-256 digest for each one so separate runs can be compared exactly.

## Run

Copy the example manifest outside the checkout if paths need local changes, then
run:

```console
python3 -m snack_gpt.voice_probe docs/voice-probe.pi.json \
  --output voice-probe-results.json
```

Run the command as the same unprivileged account that will run Snack-GPT.
Bubblewrap's `--unshare-net` gives every inference process a network namespace
with no network interfaces. A system that disables unprivileged user namespaces
will fail the probe and record that incompatibility.

The report distinguishes wake detection from processing latency. Processing is
transcription, extraction, and speech synthesis: at most 15 seconds produces
`expected_latency_achievable`, 15 to 30 seconds produces `hard_timeout_only`,
and exceeding 30 seconds kills the active process group and fails the probe.
Failures always produce a report with `blocking_incompatibilities`.