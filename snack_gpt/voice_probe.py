from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, BinaryIO, TypedDict, cast


STAGE_NAMES = ("wake_detection", "transcription", "extraction", "speech_synthesis")
EXPECTED_LATENCY_SECONDS = 15.0
HARD_TIMEOUT_SECONDS = 30.0
STAGE_STDERR_LIMIT_BYTES = 4096


class StageResult(TypedDict):
    name: str
    duration_seconds: float
    peak_memory_bytes: int


class ProbeError(Exception):
    pass


class StageExecutionError(ProbeError):
    def __init__(self, message: str, result: StageResult, *, timed_out: bool = False) -> None:
        super().__init__(message)
        self.result = result
        self.timed_out = timed_out


def _read_rss_bytes(process_id: int) -> int:
    status_path = Path(f"/proc/{process_id}/status")
    try:
        for line in status_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        pass
    usage = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    return int(usage if sys.platform == "darwin" else usage * 1024)


def _descendant_processes(process_id: int) -> set[int]:
    descendants = {process_id}
    pending = [process_id]
    while pending:
        parent = pending.pop()
        children_path = Path(f"/proc/{parent}/task/{parent}/children")
        try:
            children = [int(value) for value in children_path.read_text(encoding="utf-8").split()]
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        for child in children:
            if child not in descendants:
                descendants.add(child)
                pending.append(child)
    return descendants


def _read_stderr_tail(stderr_file: BinaryIO) -> str:
    stderr_file.seek(0, os.SEEK_END)
    size = stderr_file.tell()
    stderr_file.seek(max(0, size - STAGE_STDERR_LIMIT_BYTES))
    detail = stderr_file.read().decode("utf-8", errors="replace").strip()
    return f"[truncated] {detail}" if size > STAGE_STDERR_LIMIT_BYTES else detail


def _run_stage(
    name: str,
    command: Sequence[str],
    deadline: float,
    worker_process_ids: Sequence[int] = (),
) -> StageResult:
    started = time.monotonic()
    stderr_file = tempfile.TemporaryFile()
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=stderr_file,
            start_new_session=True,
        )
    except Exception:
        stderr_file.close()
        raise
    peak_memory = 0
    while process.poll() is None:
        measured_processes = _descendant_processes(process.pid)
        for worker_process_id in worker_process_ids:
            measured_processes.update(_descendant_processes(worker_process_id))
        peak_memory = max(
            peak_memory,
            sum(_read_rss_bytes(process_id) for process_id in measured_processes),
        )
        if time.monotonic() >= deadline:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            result: StageResult = {
                "name": name,
                "duration_seconds": round(time.monotonic() - started, 6),
                "peak_memory_bytes": peak_memory,
            }
            stderr_file.close()
            raise StageExecutionError(
                f"{name} exceeded the {HARD_TIMEOUT_SECONDS:g}-second pipeline timeout",
                result,
                timed_out=True,
            )
        time.sleep(0.01)
    peak_memory = max(peak_memory, _read_rss_bytes(process.pid))
    result = {
        "name": name,
        "duration_seconds": round(time.monotonic() - started, 6),
        "peak_memory_bytes": peak_memory,
    }
    stderr_detail = _read_stderr_tail(stderr_file)
    stderr_file.close()
    if process.returncode != 0:
        message = f"{name} exited with status {process.returncode}"
        if stderr_detail:
            message = f"{message}: {stderr_detail}"
        raise StageExecutionError(message, result)
    return result


def _stop_workers(workers: Sequence[subprocess.Popen[bytes]]) -> None:
    for worker in workers:
        if worker.poll() is None:
            os.killpg(worker.pid, signal.SIGTERM)
    for worker in workers:
        if worker.poll() is None:
            worker.wait()


def _start_workers(
    manifest: Mapping[str, object],
    isolation_command: Sequence[str],
    replacements: Mapping[str, str],
) -> list[subprocess.Popen[bytes]]:
    workers_value = manifest.get("workers", [])
    if not isinstance(workers_value, list):
        raise ProbeError("workers must be a list")
    workers: list[subprocess.Popen[bytes]] = []
    try:
        for worker_value in cast(list[object], workers_value):
            if not isinstance(worker_value, dict):
                raise ProbeError("each worker must be an object")
            worker = cast(dict[str, object], worker_value)
            name = worker.get("name")
            command_value = worker.get("command")
            ready_value = worker.get("ready_path")
            if not isinstance(name, str) or not isinstance(command_value, list) or not isinstance(ready_value, str):
                raise ProbeError("each worker must contain name, command, and ready_path")
            command_parts = cast(list[object], command_value)
            if not command_parts or not all(isinstance(part, str) for part in command_parts):
                raise ProbeError(f"worker {name} command must be a non-empty list of strings")
            command = [part.format_map(replacements) for part in cast(list[str], command_parts)]
            ready_path = Path(ready_value.format_map(replacements))
            ready_path.unlink(missing_ok=True)
            process = subprocess.Popen(
                [*isolation_command, *command],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            workers.append(process)
            deadline = time.monotonic() + HARD_TIMEOUT_SECONDS
            while not ready_path.exists():
                if process.poll() is not None:
                    raise ProbeError(f"worker {name} exited with status {process.returncode} during startup")
                if time.monotonic() >= deadline:
                    raise ProbeError(f"worker {name} did not become ready within {HARD_TIMEOUT_SECONDS:g} seconds")
                time.sleep(0.01)
    except Exception:
        _stop_workers(workers)
        raise
    return workers


def _is_subset(expected: object, actual: object) -> bool:
    if isinstance(expected, dict) and isinstance(actual, dict):
        expected_mapping = cast(dict[object, object], expected)
        actual_mapping = cast(dict[object, object], actual)
        return all(
            key in actual_mapping and _is_subset(value, actual_mapping[key])
            for key, value in expected_mapping.items()
        )
    if isinstance(expected, list) and isinstance(actual, list):
        expected_items = cast(list[object], expected)
        actual_items = cast(list[object], actual)
        return len(expected_items) == len(actual_items) and all(
            _is_subset(expected_value, actual_value)
            for expected_value, actual_value in zip(expected_items, actual_items, strict=True)
        )
    return expected == actual


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProbeError(f"cannot read JSON from {path}: {error}") from error
    if not isinstance(value, dict):
        raise ProbeError(f"{path} must contain a JSON object")
    return cast(dict[str, Any], value)


def _platform_details() -> dict[str, object]:
    model_path = Path("/proc/device-tree/model")
    try:
        model = model_path.read_text(encoding="utf-8").rstrip("\x00")
    except OSError:
        model = platform.machine()
    return {
        "model": model,
        "operating_system": platform.platform(),
        "architecture": platform.machine(),
        "is_64_bit": sys.maxsize > 2**32,
        "is_raspberry_pi_3b_plus": "Raspberry Pi 3 Model B Plus" in model,
    }


def _required_list(manifest: Mapping[str, object], key: str) -> list[str]:
    value = manifest.get(key)
    if not isinstance(value, list):
        raise ProbeError(f"{key} must be a non-empty list of strings")
    items = cast(list[object], value)
    if not items or not all(isinstance(item, str) for item in items):
        raise ProbeError(f"{key} must be a non-empty list of strings")
    return cast(list[str], items)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ProbeError(f"cannot read evidence file {path}: {error}") from error
    return digest.hexdigest()


def _write_failure_report(
    output_path: Path,
    error: Exception,
    platform_details: Mapping[str, object],
    stages: Sequence[StageResult] = (),
    *,
    offline: bool = False,
    latency_verdict: str = "not_measured",
) -> int:
    processing_duration = sum(stage["duration_seconds"] for stage in stages if stage["name"] != "wake_detection")
    report = {
        "passed": False,
        "blocking_incompatibilities": [str(error)],
        "platform": dict(platform_details),
        "offline": offline,
        "stages": list(stages),
        "processing_duration_seconds": round(processing_duration, 6),
        "peak_memory_bytes": max((stage["peak_memory_bytes"] for stage in stages), default=0),
        "expected_latency_seconds": EXPECTED_LATENCY_SECONDS,
        "hard_timeout_seconds": HARD_TIMEOUT_SECONDS,
        "latency_verdict": latency_verdict,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Voice probe failed: {error}", file=sys.stderr)
    return 1


def run(manifest_path: Path, output_path: Path) -> int:
    manifest = _load_object(manifest_path)
    platform_details = _platform_details()
    if manifest.get("require_raspberry_pi_3b_plus", True) and not platform_details["is_raspberry_pi_3b_plus"]:
        raise ProbeError("probe requires a Raspberry Pi 3B+")
    if not platform_details["is_64_bit"]:
        raise ProbeError("probe requires a 64-bit operating system")

    isolation_command = _required_list(manifest, "network_isolation_command")
    evidence_paths = [Path(value) for value in _required_list(manifest, "evidence_files")]
    evidence = [{"path": str(path), "sha256": _hash_file(path)} for path in evidence_paths]
    fixture = Path(str(manifest.get("fixture_audio", "")))
    if not fixture.is_file():
        raise ProbeError(f"fixture_audio does not exist: {fixture}")
    artifacts = Path(str(manifest.get("artifacts_directory", "probe-artifacts")))
    artifacts.mkdir(parents=True, exist_ok=True)
    paths = {
        "audio": fixture,
        "artifacts": artifacts,
        "wake_result": artifacts / "wake.json",
        "transcript": artifacts / "transcript.txt",
        "extraction": artifacts / "extraction.json",
        "speech": artifacts / "speech.wav",
    }
    commands_value = manifest.get("commands")
    if not isinstance(commands_value, dict):
        raise ProbeError("commands must be an object")
    commands = cast(dict[str, object], commands_value)
    stages: list[StageResult] = []
    processing_deadline = 0.0
    replacements = {key: str(value) for key, value in paths.items()}
    workers = _start_workers(manifest, isolation_command, replacements)
    try:
        for name in STAGE_NAMES:
            command_template = commands.get(name)
            if not isinstance(command_template, list):
                raise ProbeError(f"commands.{name} must be a non-empty list of strings")
            command_parts = cast(list[object], command_template)
            if not command_parts or not all(isinstance(part, str) for part in command_parts):
                raise ProbeError(f"commands.{name} must be a non-empty list of strings")
            command = [part.format_map(replacements) for part in cast(list[str], command_parts)]
            if name == "wake_detection":
                deadline = time.monotonic() + HARD_TIMEOUT_SECONDS
            else:
                if processing_deadline == 0.0:
                    processing_deadline = time.monotonic() + HARD_TIMEOUT_SECONDS
                deadline = processing_deadline
            try:
                stages.append(
                    _run_stage(
                        name,
                        [*isolation_command, *command],
                        deadline,
                        [worker.pid for worker in workers],
                    )
                )
            except StageExecutionError as error:
                stages.append(error.result)
                verdict = "hard_timeout_exceeded" if error.timed_out else "not_measured"
                return _write_failure_report(
                    output_path,
                    error,
                    platform_details,
                    stages,
                    offline=True,
                    latency_verdict=verdict,
                )
    finally:
        _stop_workers(workers)

    wake_result = _load_object(paths["wake_result"])
    if wake_result.get("detected") is not True:
        raise ProbeError("wake detection did not report detected=true")
    transcript = paths["transcript"].read_text(encoding="utf-8")
    expected_terms = _required_list(manifest, "expected_transcript_terms")
    missing_terms = [term for term in expected_terms if term.casefold() not in transcript.casefold()]
    if missing_terms:
        raise ProbeError(f"transcript is missing expected terms: {', '.join(missing_terms)}")
    extraction = _load_object(paths["extraction"])
    expected_extraction = manifest.get("expected_extraction")
    if not isinstance(expected_extraction, dict) or not _is_subset(
        cast(dict[object, object], expected_extraction), extraction
    ):
        raise ProbeError("extraction did not match expected_extraction")
    if not paths["speech"].is_file() or paths["speech"].stat().st_size <= 4:
        raise ProbeError("speech synthesis did not create a non-empty audio artifact")

    total_duration = sum(stage["duration_seconds"] for stage in stages)
    processing_duration = sum(stage["duration_seconds"] for stage in stages[1:])
    if processing_duration <= EXPECTED_LATENCY_SECONDS:
        verdict = "expected_latency_achievable"
    else:
        verdict = "hard_timeout_only"
    report = {
        "passed": True,
        "blocking_incompatibilities": [],
        "platform": platform_details,
        "offline": True,
        "network_isolation_command": isolation_command,
        "evidence_files": evidence,
        "stages": stages,
        "total_duration_seconds": round(total_duration, 6),
        "processing_duration_seconds": round(processing_duration, 6),
        "peak_memory_bytes": max(stage["peak_memory_bytes"] for stage in stages),
        "expected_latency_seconds": EXPECTED_LATENCY_SECONDS,
        "hard_timeout_seconds": HARD_TIMEOUT_SECONDS,
        "latency_verdict": verdict,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Voice probe passed: {verdict} ({processing_duration:.2f}s processing)")
    return 0


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the offline Raspberry Pi voice runtime acceptance probe")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, default=Path("voice-probe-results.json"))
    parsed = parser.parse_args(arguments)
    try:
        return run(parsed.manifest, parsed.output)
    except (ProbeError, OSError, KeyError, ValueError) as error:
        return _write_failure_report(parsed.output, error, _platform_details())


if __name__ == "__main__":
    raise SystemExit(main())