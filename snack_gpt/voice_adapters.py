from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
import importlib
import json
from numbers import Real
import os
from pathlib import Path
import socket
import subprocess
import sys
from typing import Protocol, cast
import wave

from snack_gpt.voice import parse_consumption_report


class AdapterError(Exception):
    pass


class WakeRuntime(Protocol):
    def predict_clip(self, path: str) -> object: ...


class WakeFactory(Protocol):
    def __call__(self, **kwargs: object) -> WakeRuntime: ...


def _run(command: Sequence[str], stage: str) -> None:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as error:
        raise AdapterError(f"cannot start {stage} runtime: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip()
        message = f"{stage} runtime exited with status {result.returncode}"
        if detail:
            message = f"{message}: {detail}"
        raise AdapterError(message)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _wake(model_path: Path, audio_path: Path, output_path: Path) -> None:
    model_module = importlib.import_module("openwakeword.model")
    model_factory = cast(WakeFactory, getattr(model_module, "Model"))
    model = model_factory(
        wakeword_models=[str(model_path)],
        inference_framework="onnx",
        melspec_model_path=str(model_path.with_name("melspectrogram.onnx")),
        embedding_model_path=str(model_path.with_name("embedding_model.onnx")),
    )
    raw_predictions = model.predict_clip(str(audio_path))
    if not isinstance(raw_predictions, list):
        raise AdapterError("OpenWakeWord returned an unexpected result")
    predictions = cast(list[object], raw_predictions)
    scores: list[float] = []
    for prediction in predictions:
        if not isinstance(prediction, Mapping):
            raise AdapterError("OpenWakeWord returned an unexpected frame result")
        for score in cast(Mapping[object, object], prediction).values():
            if isinstance(score, Real):
                scores.append(float(score))
    if not scores:
        raise AdapterError("OpenWakeWord returned no prediction scores")
    peak_score = max(scores)
    _write_json(output_path, {"detected": peak_score >= 0.5, "peak_score": peak_score})


def _transcribe(
    binary: Path,
    binary_arguments: Sequence[str],
    model_path: Path,
    audio_path: Path,
    output_path: Path,
) -> None:
    output_prefix = output_path.with_suffix("")
    _run(
        [
            str(binary),
            *binary_arguments,
            "-m",
            str(model_path),
            "-f",
            str(audio_path),
            "-l",
            "en",
            "-otxt",
            "-of",
            str(output_prefix),
            "-nt",
            "-np",
        ],
        "whisper.cpp",
    )
    generated_path = output_prefix.with_suffix(".txt")
    if not generated_path.is_file():
        raise AdapterError("whisper.cpp did not create its transcript")
    transcript = generated_path.read_text(encoding="utf-8").strip()
    if not transcript:
        raise AdapterError("whisper.cpp produced an empty transcript")
    output_path.write_text(transcript, encoding="utf-8")


def _extract(model_path: Path | None, library_path: Path | None, transcript_path: Path, output_path: Path) -> None:
    if library_path is not None:
        os.environ["NEEDLE_LIB_PATH"] = str(library_path)
    os.environ["HF_HUB_OFFLINE"] = "1"
    needle_module = importlib.import_module("needle")
    extractor = cast(Callable[..., object], getattr(needle_module, "extract"))
    schema = {
        "name": "log_food_intake",
        "description": "Extract one food and its explicit Food Quantity from the owner's words.",
        "parameters": {
            "type": "object",
            "properties": {
                "foods": {
                    "type": "array",
                    "description": "The food the owner consumed.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "food": {
                                "type": "string",
                                "description": (
                                    "USDA search term preserving spoken preparation, form, and other "
                                    "food qualifiers; never a USDA identifier or claimed canonical description."
                                ),
                            },
                            "quantity": {
                                "type": "number",
                                "description": "Finite numeric quantity explicitly spoken by the owner.",
                                "exclusiveMinimum": 0,
                            },
                            "measure": {
                                "type": "string",
                                "description": (
                                    "Spoken unit or food measure only; never a gram weight or conversion factor."
                                ),
                            },
                        },
                        "required": ["food", "quantity", "measure"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                    "maxItems": 1,
                }
            },
            "required": ["foods"],
            "additionalProperties": False,
        },
    }
    extraction_arguments: dict[str, object] = {}
    if model_path is not None:
        extraction_arguments["weights"] = str(model_path)
    result = extractor(transcript_path.read_text(encoding="utf-8"), schema, **extraction_arguments)
    report = parse_consumption_report(result)
    _write_json(
        output_path,
        {
            "foods": [
                {
                    "food": report.item.food,
                    "quantity": report.item.quantity,
                    "measure": report.item.measure,
                }
            ]
        },
    )


def _speech_text(extraction_path: Path) -> str:
    value: object = json.loads(extraction_path.read_text(encoding="utf-8"))
    report = parse_consumption_report(value)
    item = report.item
    return f"Recorded {item.quantity:g} {item.measure} {item.food}."


def _synthesize(
    binary: Path,
    binary_arguments: Sequence[str],
    model_path: Path,
    text: str,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            str(binary),
            *binary_arguments,
            "-m",
            str(model_path),
            "-f",
            str(output_path),
            "--",
            text,
        ],
        "Piper",
    )
    if not output_path.is_file() or output_path.stat().st_size <= 4:
        raise AdapterError("Piper did not create a non-empty WAV file")


def _piper_worker(model_path: Path, socket_path: Path) -> None:
    piper_module = importlib.import_module("piper")
    voice_type = getattr(piper_module, "PiperVoice")
    voice = voice_type.load(str(model_path))
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.unlink(missing_ok=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(socket_path))
        server.listen()
        while True:
            connection, _ = server.accept()
            with connection:
                try:
                    request = json.loads(connection.recv(65536).decode("utf-8"))
                    if not isinstance(request, dict):
                        raise ValueError("request must be an object")
                    request_mapping = cast(dict[object, object], request)
                    text = request_mapping.get("text")
                    output_value = request_mapping.get("output")
                    if not isinstance(text, str) or not isinstance(output_value, str):
                        raise ValueError("request must contain text and output strings")
                    output_path = Path(output_value)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with wave.open(str(output_path), "wb") as output:
                        voice.synthesize_wav(text, output)
                    response = {"ok": True}
                except (OSError, ValueError, json.JSONDecodeError) as error:
                    response = {"ok": False, "error": str(error)}
                connection.sendall(json.dumps(response).encode("utf-8"))


def _synthesize_warm(socket_path: Path, text: str, output_path: Path) -> None:
    request = json.dumps({"text": text, "output": str(output_path)})
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(socket_path))
        client.sendall(request.encode("utf-8"))
        client.shutdown(socket.SHUT_WR)
        response_value: object = json.loads(client.recv(65536).decode("utf-8"))
    if not isinstance(response_value, dict):
        raise AdapterError("Piper worker returned an invalid response")
    response = cast(dict[object, object], response_value)
    if response.get("ok") is not True:
        raise AdapterError(f"Piper worker failed: {response.get('error', 'unknown error')}")
    if not output_path.is_file() or output_path.stat().st_size <= 4:
        raise AdapterError("Piper did not create a non-empty WAV file")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalize local voice runtime interfaces for the acceptance probe")
    commands = parser.add_subparsers(dest="command", required=True)

    wake = commands.add_parser("wake")
    wake.add_argument("--model", type=Path, required=True)
    wake.add_argument("--audio", type=Path, required=True)
    wake.add_argument("--output", type=Path, required=True)

    transcribe = commands.add_parser("transcribe")
    transcribe.add_argument("--binary", type=Path, required=True)
    transcribe.add_argument("--binary-argument", action="append", default=[])
    transcribe.add_argument("--model", type=Path, required=True)
    transcribe.add_argument("--audio", type=Path, required=True)
    transcribe.add_argument("--output", type=Path, required=True)

    extract = commands.add_parser("extract")
    extract.add_argument("--model", type=Path)
    extract.add_argument("--library", type=Path)
    extract.add_argument("--transcript", type=Path, required=True)
    extract.add_argument("--output", type=Path, required=True)

    synthesize = commands.add_parser("synthesize")
    synthesize_runtime = synthesize.add_mutually_exclusive_group(required=True)
    synthesize_runtime.add_argument("--binary", type=Path)
    synthesize_runtime.add_argument("--socket", type=Path)
    synthesize.add_argument("--binary-argument", action="append", default=[])
    synthesize.add_argument("--model", type=Path)
    synthesize_input = synthesize.add_mutually_exclusive_group(required=True)
    synthesize_input.add_argument("--extraction", type=Path)
    synthesize_input.add_argument("--text")
    synthesize.add_argument("--output", type=Path, required=True)

    piper_worker = commands.add_parser("piper-worker")
    piper_worker.add_argument("--model", type=Path, required=True)
    piper_worker.add_argument("--socket", type=Path, required=True)
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    parsed = _parser().parse_args(arguments)
    try:
        if parsed.command == "wake":
            _wake(parsed.model, parsed.audio, parsed.output)
        elif parsed.command == "transcribe":
            _transcribe(parsed.binary, parsed.binary_argument, parsed.model, parsed.audio, parsed.output)
        elif parsed.command == "extract":
            _extract(parsed.model, parsed.library, parsed.transcript, parsed.output)
        elif parsed.command == "synthesize":
            text = parsed.text if parsed.text is not None else _speech_text(parsed.extraction)
            if parsed.socket:
                _synthesize_warm(parsed.socket, text, parsed.output)
            else:
                if parsed.model is None:
                    raise AdapterError("--model is required with --binary")
                _synthesize(parsed.binary, parsed.binary_argument, parsed.model, text, parsed.output)
        elif parsed.command == "piper-worker":
            _piper_worker(parsed.model, parsed.socket)
    except (AdapterError, ImportError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Voice adapter failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())