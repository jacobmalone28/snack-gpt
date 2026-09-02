# Raspberry Pi appliance acceptance

Run this procedure on a Raspberry Pi 3B+ with 64-bit Raspberry Pi OS, its final
microphone and speaker, and the release revision being accepted. Keep the voice
probe JSON, journal excerpts, exported history, and the completed results table
with the release evidence. Do not include credentials, transcripts, food names,
or audio in committed evidence.

## Preconditions

1. Provision the appliance as described in [installation.md](installation.md).
2. Confirm `/opt/snack-gpt/bin/voice-audio check` records understandable speech
   and plays it through the intended speaker.
3. Set `USDA_FDC_API_KEY`, initialize an owner password for LAN mode, and enable
   the three services. Confirm all services are active after a reboot.
4. Run the offline probe from [voice-probe.md](voice-probe.md) at least ten times
   with representative speakers and distances. Retain each JSON report.

Before enabling services, verify `systemctl is-enabled` reports `disabled` for
`snack-gpt-web`, `snack-gpt-piper`, and `snack-gpt-listener`. Verify the expected
model and manifest files exist, `voice.json` contains `speech_synthesis`, and the
audio check completes rather than hanging. After enabling, require all three
`systemctl is-active` checks to report `active`; inspect `systemctl status` and
the corresponding journal before continuing if any unit fails.

## Appliance run

Record pass or fail and a privacy-safe evidence pointer for every step.

| Capability | Acceptance action |
| --- | --- |
| Wake reliability | Attempt at least ten wake phrases mixed with at least ten non-wake phrases. Record true accepts, missed wakes, false accepts, microphone placement, and ambient conditions. |
| Voice creation | Submit a multi-item Consumption Report by voice. Confirm one success response and atomic creation of every Consumption Event. |
| Weekly history | Open the current and previous Calendar Week and verify weekly history and totals against known Consumption Events. |
| Correction | Correct a day, then a food or Food Quantity. Confirm the Nutrition Snapshot changes only for the USDA-backed correction. |
| Backup | Export history, remove a disposable event, import the backup, and verify restoration plus idempotent re-import. |
| Authentication | Bind to the trusted LAN, verify unauthenticated routes require login, sign in, reset the owner password locally, and verify the old session is revoked. |
| Degraded states | Disconnect the network and verify the web UI shows USDA unavailable, creation and food or Food Quantity correction are disabled, and history, totals, day correction, deletion, export, and import remain usable. Reconnect and use Retry USDA. Disconnect the microphone, restart the listener, and verify the web UI shows audio unavailable rather than a command, path, stack trace, or captured content. Reconnect it and restart the listener before continuing. |
| Restart persistence | Pause listening, reboot, and verify it remains paused. Resume, reboot again, and verify listening, history, credentials, and the latest corrections persist. |

Inspect `journalctl` for the run. Logs may contain operation IDs, stage latency,
outcomes, and sanitized failure categories, but must not contain transcripts,
credentials, food names, or sensitive command output.

## Performance evidence

For every offline probe report, record:

- peak memory in bytes;
- transcription quality as expected terms found and total expected terms;
- wake reliability counts from the live trials;
- each stage latency and total processing latency;
- whether normal successful reports complete within 15 seconds;
- whether every report terminates successfully or fails cleanly by 30 seconds.

Use this summary alongside the raw probe JSON files:

| Evidence | Result |
| --- | --- |
| Release commit and Raspberry Pi OS image | |
| Microphone and speaker | |
| Wake true accepts / attempts | |
| Missed wakes / attempts | |
| False accepts / non-wake trials | |
| Transcription expected terms / total | |
| Maximum peak memory | |
| Median and maximum stage latency | |
| Reports within 15 seconds / successful reports | |
| Reports terminated by 30 seconds / total reports | |
| Appliance capability table complete | |
| Blocking incompatibilities | |

The architecture is accepted only when there are no blocking incompatibilities,
all appliance capabilities pass, successful reports normally complete within
15 seconds, and every report terminates by 30 seconds. A desktop or simulated
run cannot substitute for this on-device result.