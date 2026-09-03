# Installation and model provisioning

Snack-GPT is a Python application that launches through `python -m snack_gpt` or
the `snack-gpt` console script. The web application works on every supported
platform. Voice operation additionally needs platform-native OpenWakeWord,
whisper.cpp, Needle, Piper, audio capture, and audio playback commands described
by `SNACK_GPT_VOICE_MANIFEST`.

## Supported platforms

| Target | Application launch | Model and native runtime provisioning | Memory-backed voice files |
| --- | --- | --- | --- |
| Linux ARM64 | Create a Python 3.11+ virtual environment, run `pip install .`, then `snack-gpt serve` and `snack-gpt listen`. | On Raspberry Pi OS 64-bit, use the provisioner below. Other ARM64 systems use the same pinned sources in `scripts/provision-voice-probe.sh`, selecting the Needle `manylinux2014_aarch64` engine. | `/dev/shm` |
| Linux x86-64 | Create a Python 3.11+ virtual environment, run `pip install .`, then `snack-gpt serve` and `snack-gpt listen`. | Build pinned whisper.cpp, install the pinned Python packages listed by the Pi provisioner, and fetch Needle's `manylinux2014_x86_64` engine. Download the same OpenWakeWord and Piper models. | `/dev/shm` |
| macOS ARM64 | Create a Python 3.11+ virtual environment, run `pip install .`, then launch both commands from Terminal or `launchd`. | Install CMake and SoX with Homebrew, build pinned whisper.cpp, install the pinned Python packages, and fetch Needle's macOS ARM64 engine. Download the same OpenWakeWord and Piper models. | An owner-created and mounted RAM disk |
| macOS x86-64 | Use the macOS ARM64 launch path with an x86-64 Python interpreter. | Build each pinned native runtime for x86-64 and fetch Needle's macOS x86-64 engine. Rosetta mixing is unsupported; Python and every native library must use the same architecture. | An owner-created and mounted RAM disk |
| Windows x86-64 | Create a Python 3.11+ virtual environment, run `pip install .`, then launch `snack-gpt serve` and `snack-gpt listen` from PowerShell or Task Scheduler. | Install CMake and SoX, build pinned whisper.cpp with Visual Studio Build Tools, install the pinned Python packages, and fetch Needle's Windows x86-64 engine. Download the same OpenWakeWord and Piper models. Use Windows paths in the manifest command arrays. | An owner-created and mounted RAM disk |

The exact tested model versions, source revisions, checksums, and upstream links
are recorded in [voice-provisioning-research.md](voice-provisioning-research.md).
For desktop voice installs, copy the manifest shape from the example in the
README and replace every executable, model, library, and memory-directory path
with the local native path. Commands are arrays and do not run through a shell.

## Raspberry Pi OS 64-bit

On a Raspberry Pi 3B+, check out the intended release and run:

```console
sudo scripts/provision-voice-probe.sh --accept-model-licenses
```

The provisioner installs the application, pinned voice runtimes and models,
`/etc/snack-gpt/voice.json`, `/etc/snack-gpt/environment`, and native systemd
units. All units are installed disabled. Edit the environment file and set
`USDA_FDC_API_KEY` before starting the listener.

SoX uses the system-default microphone and speaker when no override is set. To
select different devices, set `SNACK_GPT_MICROPHONE` and
`SNACK_GPT_SPEAKER` in `/etc/snack-gpt/environment` to device names accepted by
SoX on that host. Verify recording and playback as the service account:

```console
set -a
. /etc/snack-gpt/environment
set +a
/opt/snack-gpt/bin/voice-audio check
```

Set the owner password if LAN access is configured, then run the one-command
audio check and appliance startup:

```console
snackgpt start
```

The command records and plays a short audio sample. It enables and starts all
three systemd services only when audio succeeds and the USDA key is configured.

Follow [raspberry-pi-acceptance.md](raspberry-pi-acceptance.md) before treating
the installation as accepted.

## Licensing constraints

The initial deployment is personal and non-commercial. OpenWakeWord code is
Apache-2.0, but its included `hey_jarvis_v0.1` model is CC BY-NC-SA 4.0; do not
use or redistribute that model commercially. Piper is GPL-3.0-or-later. The
selected `en_US-lessac-low` voice's downloaded `MODEL_CARD` is retained beside
the model and must be reviewed before use or redistribution. Passing
`--accept-model-licenses` records an operator decision to proceed; it does not
change or supersede those licenses.