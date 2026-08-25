# Raspberry Pi voice runtime probe

The voice probe exercises provisioned OpenWakeWord, whisper.cpp with Whisper
`tiny.en`, Needle, and Piper on a Raspberry Pi 3B+. It executes every stage in a
network namespace, records stage timing and peak resident memory, and writes a
JSON acceptance report.

## Provisioned inputs

Use 64-bit Raspberry Pi OS Lite and provision Bubblewrap, the four runtimes,
their local models, and a 16 kHz mono WAV fixture containing "Hey Jarvis, I ate
two eggs." The probe does not download or install dependencies.

Each runtime adapter is an executable with the command line shown in
[`voice-probe.pi.json`](voice-probe.pi.json). Adapters must return nonzero on a
runtime error and write these artifacts:

| Stage | Artifact contract |
| --- | --- |
| OpenWakeWord | JSON containing `{"detected": true}` |
| whisper.cpp | UTF-8 transcript text |
| Needle | JSON containing the configured expected extraction |
| Piper | Non-empty WAV audio |

The adapters only normalize native runtime input and output. List every adapter,
native binary, model, and fixture in `evidence_files`; the result records a
SHA-256 digest for each one so separate runs can be compared exactly.

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