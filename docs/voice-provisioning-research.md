# Voice provisioning sources

Checked against upstream primary sources on 2026-08-25 for 64-bit Raspberry Pi
OS on a Raspberry Pi 3B+.

## OpenWakeWord

[`openwakeword==0.6.0`](https://pypi.org/project/openwakeword/0.6.0/) supports
ONNX inference and its upstream documentation states that one Raspberry Pi 3
core can run multiple models in real time. The provisioner uses the official
[`download_models`](https://github.com/dscripka/openWakeWord/blob/main/openwakeword/utils.py)
API and the documented `predict_clip` API with 16-bit, 16 kHz mono PCM input.

The package declares `tflite-runtime` on Linux, but the probe exclusively uses
ONNX. The provisioner therefore installs the package without dependencies and
installs its ONNX dependency set explicitly. OpenWakeWord code is Apache-2.0;
its included pretrained models, including Hey Jarvis, are CC BY-NC-SA 4.0 and
therefore non-commercial.

The explicit inference set uses `numpy==2.2.6`, `scipy==1.15.3`,
`scikit-learn==1.6.1`, and `onnxruntime==1.22.1`. Each release publishes a
CPython 3.13 AArch64 Linux wheel, so Raspberry Pi OS Trixie does not need to
compile these packages or install a second Python interpreter. The provisioner
also derives the virtual environment's package directory with `sysconfig`
rather than assuming a Python minor version.

## whisper.cpp

[`whisper.cpp v1.8.0`](https://github.com/ggml-org/whisper.cpp/tree/v1.8.0) is
pinned to commit `41fc9dea6a4fe056424be86f61164413903fcff4`. Upstream documents
Raspberry Pi support, the CMake build, `whisper-cli`, and the `tiny.en` download.
The official model table publishes SHA-1
`c78c86eb1a8faa21b369bcd33207cc90d64ae9df`, which the script verifies.

## Needle

[`cactus-needle==2.0.10`](https://pypi.org/project/cactus-needle/2.0.10/) exposes
structured extraction through `needle.extract`. Its
[`offline device documentation`](https://github.com/cactus-compute/needle/blob/main/doc/apis.md#offline-devices)
defines `needle fetch --platform-tag manylinux2014_aarch64`, `NEEDLE_LIB_PATH`,
and `HF_HUB_OFFLINE=1`. The base 14 MB model is baked into the engine, so no
fictional GGUF or separately loaded `.cact` file is used. Needle is Apache-2.0.

The package declares JAX training dependencies that its ctypes inference path
does not import. The provisioner omits those dependencies to keep the install
appropriate for a 1 GB Pi.

## Piper

[`piper-tts==1.7.0`](https://pypi.org/project/piper-tts/1.7.0/) publishes an
ARM64 wheel and is GPL-3.0-or-later. The official
[`Piper CLI documentation`](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/CLI.md)
defines model download and WAV output. The pinned `en_US-lessac-medium` voice
comes from the immutable `v1.0.0` revision of
[`rhasspy/piper-voices`](https://huggingface.co/rhasspy/piper-voices/tree/v1.0.0/en/en_US/lessac/medium).
Its model, JSON configuration, and MODEL_CARD are all retained locally.