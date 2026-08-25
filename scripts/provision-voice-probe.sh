#!/usr/bin/env bash
set -euo pipefail

PREFIX=/opt/snack-gpt
OPENWAKEWORD_VERSION=0.6.0
NEEDLE_VERSION=2.0.10
PIPER_VERSION=1.7.0
WHISPER_TAG=v1.8.0
WHISPER_COMMIT=41fc9dea6a4fe056424be86f61164413903fcff4
WHISPER_MODEL_SHA1=c78c86eb1a8faa21b369bcd33207cc90d64ae9df
FIXTURE_SOURCE=
CAPTURE_DEVICE=
ACCEPT_LICENSES=false

usage() {
    cat <<'EOF'
Usage: sudo scripts/provision-voice-probe.sh --accept-model-licenses [--fixture FILE] [--capture-device DEVICE]

Installs the local voice acceptance stack under /opt/snack-gpt. Without
--fixture, the script records a seven-second 16 kHz mono WAV from the default
ALSA capture device. When exactly one hardware capture device exists, the
script selects it automatically.

--capture-device uses an explicit ALSA device such as plughw:1,0.

--accept-model-licenses acknowledges OpenWakeWord's CC BY-NC-SA 4.0 model
license and the Piper voice MODEL_CARD fetched during provisioning.
EOF
}

while (($#)); do
    case "$1" in
        --accept-model-licenses)
            ACCEPT_LICENSES=true
            shift
            ;;
        --fixture)
            [[ $# -ge 2 ]] || { echo "--fixture requires a file" >&2; exit 2; }
            FIXTURE_SOURCE=$2
            shift 2
            ;;
        --capture-device)
            [[ $# -ge 2 ]] || { echo "--capture-device requires a device" >&2; exit 2; }
            CAPTURE_DEVICE=$2
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

[[ $EUID -eq 0 ]] || { echo "Run this script with sudo." >&2; exit 1; }
[[ $ACCEPT_LICENSES == true ]] || { echo "Pass --accept-model-licenses after reviewing docs/voice-provisioning-research.md." >&2; exit 1; }
[[ $(getconf LONG_BIT) == 64 ]] || { echo "A 64-bit operating system is required." >&2; exit 1; }
[[ -r /proc/device-tree/model ]] || { echo "Cannot identify Raspberry Pi model." >&2; exit 1; }
MODEL_NAME=$(tr -d '\0' </proc/device-tree/model)
[[ $MODEL_NAME == *"Raspberry Pi 3 Model B Plus"* ]] || { echo "A Raspberry Pi 3B+ is required; found: $MODEL_NAME" >&2; exit 1; }
if [[ -n $FIXTURE_SOURCE ]]; then
    [[ -f $FIXTURE_SOURCE ]] || { echo "Fixture does not exist: $FIXTURE_SOURCE" >&2; exit 1; }
    FIXTURE_SOURCE=$(realpath "$FIXTURE_SOURCE")
fi

SCRIPT_DIRECTORY=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPOSITORY_ROOT=$(cd -- "$SCRIPT_DIRECTORY/.." && pwd)
VENV=$PREFIX/venv
BIN=$PREFIX/bin
MODELS=$PREFIX/models
LIB=$PREFIX/lib
PROBE=$PREFIX/probe
SOURCE=$PREFIX/src

echo "Installing system packages..."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    alsa-utils bubblewrap build-essential ca-certificates cmake curl git \
    libopenblas-dev python3 python3-pip python3-venv
if [[ -z $FIXTURE_SOURCE && -z $CAPTURE_DEVICE ]]; then
    mapfile -t CAPTURE_DEVICES < <(
        LC_ALL=C arecord --list-devices 2>/dev/null |
            sed -nE 's/^card ([0-9]+):.*device ([0-9]+):.*/plughw:\1,\2/p'
    )
    if (( ${#CAPTURE_DEVICES[@]} == 1 )); then
        CAPTURE_DEVICE=${CAPTURE_DEVICES[0]}
    else
        echo "Expected one ALSA hardware capture device; found ${#CAPTURE_DEVICES[@]}." >&2
        arecord --list-devices >&2 || true
        echo "Rerun with --capture-device DEVICE (for example, plughw:1,0)." >&2
        exit 1
    fi
fi
python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' || {
    echo "Python 3.11 or newer is required." >&2
    exit 1
}

install -d -m 0755 "$BIN" "$MODELS" "$LIB" "$PROBE"
rm -rf "$VENV" "$SOURCE/whisper.cpp"
install -d -m 0755 "$SOURCE"
python3 -m venv "$VENV"
PYTHON=$VENV/bin/python
PIP=("$PYTHON" -m pip)

echo "Installing pinned Python runtimes..."
"${PIP[@]}" install --upgrade pip
"${PIP[@]}" install \
    "numpy==2.2.6" \
    "onnxruntime==1.22.1" \
    "requests==2.32.5" \
    "scikit-learn==1.6.1" \
    "scipy==1.15.3" \
    "tqdm==4.67.1" \
    "huggingface-hub==0.31.4" \
    "piper-tts==$PIPER_VERSION"
# OpenWakeWord's Linux metadata requires tflite-runtime, but this probe uses
# ONNX exclusively. Needle's training dependencies are also unnecessary for
# its ctypes inference API and are too large for a 1 GB Pi.
"${PIP[@]}" install --no-deps \
    "openwakeword==$OPENWAKEWORD_VERSION" \
    "cactus-needle==$NEEDLE_VERSION"
"${PIP[@]}" install --no-deps "$REPOSITORY_ROOT"

echo "Downloading OpenWakeWord models..."
"$PYTHON" - "$MODELS" <<'PY'
from pathlib import Path
import sys
from openwakeword.utils import download_models

target = Path(sys.argv[1])
download_models(["hey_jarvis_v0.1"], target_directory=str(target))
required = ["hey_jarvis_v0.1.onnx", "melspectrogram.onnx", "embedding_model.onnx"]
missing = [name for name in required if not (target / name).is_file()]
if missing:
    raise SystemExit("OpenWakeWord did not provide: " + ", ".join(missing))
PY

echo "Downloading Needle ARM64 engine..."
"$VENV/bin/needle" fetch --out "$LIB" --platform-tag manylinux2014_aarch64
[[ -s $LIB/libneedle.so ]] || { echo "Needle ARM64 engine was not downloaded." >&2; exit 1; }

echo "Building whisper.cpp $WHISPER_TAG..."
git clone --branch "$WHISPER_TAG" --depth 1 https://github.com/ggml-org/whisper.cpp.git "$SOURCE/whisper.cpp"
[[ $(git -C "$SOURCE/whisper.cpp" rev-parse HEAD) == "$WHISPER_COMMIT" ]] || { echo "Unexpected whisper.cpp commit." >&2; exit 1; }
cmake -S "$SOURCE/whisper.cpp" -B "$SOURCE/whisper.cpp/build" \
    -DCMAKE_BUILD_TYPE=Release -DGGML_BLAS=ON
cmake --build "$SOURCE/whisper.cpp/build" --config Release --parallel 2 --target whisper-cli
install -m 0755 "$SOURCE/whisper.cpp/build/bin/whisper-cli" "$BIN/whisper-cli"
"$SOURCE/whisper.cpp/models/download-ggml-model.sh" tiny.en "$MODELS"
echo "$WHISPER_MODEL_SHA1  $MODELS/ggml-tiny.en.bin" | sha1sum --check --status || {
    echo "Whisper tiny.en checksum mismatch." >&2
    exit 1
}

echo "Downloading Piper voice..."
PIPER_BASE=https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/low
curl --fail --location --retry 3 --output "$MODELS/en_US-lessac-low.onnx" \
    "$PIPER_BASE/en_US-lessac-low.onnx"
curl --fail --location --retry 3 --output "$MODELS/en_US-lessac-low.onnx.json" \
    "$PIPER_BASE/en_US-lessac-low.onnx.json"
curl --fail --location --retry 3 --output "$MODELS/en_US-lessac-low.MODEL_CARD" \
    "$PIPER_BASE/MODEL_CARD"

write_adapter() {
    local path=$1
    local command=$2
    cat >"$path" <<EOF
#!/bin/sh
exec "$PYTHON" -m snack_gpt.voice_adapters "$command" "\$@"
EOF
    chmod 0755 "$path"
}

write_adapter "$BIN/openwakeword-probe" wake
write_adapter "$BIN/whisper-probe" transcribe
write_adapter "$BIN/needle-probe" extract
write_adapter "$BIN/piper-probe" synthesize
write_adapter "$BIN/piper-worker" piper-worker
cat >"$BIN/piper" <<EOF
#!/bin/sh
exec "$PYTHON" -m piper "\$@"
EOF
chmod 0755 "$BIN/piper"
"${PIP[@]}" freeze --all | LC_ALL=C sort >"$PROBE/python-packages.txt"
PURELIB=$($PYTHON -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
[[ -s $PURELIB/snack_gpt/voice_adapters.py ]] || {
    echo "Installed voice adapter module was not found." >&2
    exit 1
}

if [[ -n $FIXTURE_SOURCE ]]; then
    install -m 0644 "$FIXTURE_SOURCE" "$PROBE/report.wav"
else
    echo
    DEVICE="$CAPTURE_DEVICE"
    echo "Recording the acceptance fixture from ALSA device $DEVICE."
    echo "After pressing Enter, say: Hey Jarvis, I ate two eggs."
    read -r
    arecord --device="$DEVICE" --duration=7 --format=S16_LE --rate=16000 --channels=1 \
        --file-type=wav "$PROBE/report.wav"
fi

"$PYTHON" - "$PROBE/report.wav" <<'PY'
import sys
import wave

with wave.open(sys.argv[1], "rb") as audio:
    details = (audio.getnchannels(), audio.getsampwidth(), audio.getframerate())
if details != (1, 2, 16000):
    raise SystemExit(f"fixture must be mono 16-bit 16 kHz PCM WAV; found {details}")
PY

chmod -R a+rX "$PREFIX"
echo
echo "Provisioning complete. Run the acceptance probe as an unprivileged user:"
echo "  cd $REPOSITORY_ROOT"
echo "  $PYTHON -m snack_gpt.voice_probe docs/voice-probe.pi.json --output voice-probe-results.json"