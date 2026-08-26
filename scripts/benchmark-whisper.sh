#!/usr/bin/env bash
set -euo pipefail

export LC_ALL=C

SCRIPT_DIRECTORY=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPOSITORY_ROOT=$(cd -- "$SCRIPT_DIRECTORY/.." && pwd)
PREFIX=/opt/snack-gpt
WHISPER_BINARY=$PREFIX/bin/whisper-cli
WHISPER_MODEL=$PREFIX/models/ggml-tiny.en.bin
WHISPER_AUDIO=$PREFIX/probe/report.wav
WHISPER_SOURCE=$PREFIX/src/whisper.cpp
PYTHON=$PREFIX/venv/bin/python
RUNS=5
TIMEOUT_SECONDS=30
TARGET_SECONDS=9.16
OUTPUT_DIRECTORY=
QUANT_MODEL=
SKIP_ACCEPTANCE=false
SKIP_BLAS=false
SCRIPT_STATE=initializing

usage() {
    cat <<'EOF'
Usage: scripts/benchmark-whisper.sh [OPTIONS]

Runs the controlled whisper.cpp latency benchmark on a provisioned Raspberry
Pi 3B+. Results include raw per-run artifacts, evidence hashes, summary.json,
summary.md, and a TSV run index.

Options:
  --output DIRECTORY       Result directory (default: ~/whisper-benchmark-TIME)
  --runs COUNT             Measured runs per configuration (default: 5)
  --timeout SECONDS        Per-run hard timeout (default: 30)
  --quant-model FILE       Also compare a pre-downloaded tiny.en-q5_1 model
  --skip-acceptance        Do not run the normal end-to-end voice probe first
  --skip-blas              Do not build and compare BLAS/native binaries
  -h, --help               Show this help

The script must run as the unprivileged Snack-GPT account. It never replaces
the production whisper-cli binary or model.
EOF
}

die() {
    echo "Benchmark failed: $*" >&2
    exit 1
}

while (($#)); do
    case "$1" in
        --output)
            [[ $# -ge 2 ]] || die "--output requires a directory"
            OUTPUT_DIRECTORY=$2
            shift 2
            ;;
        --runs)
            [[ $# -ge 2 ]] || die "--runs requires a count"
            RUNS=$2
            shift 2
            ;;
        --timeout)
            [[ $# -ge 2 ]] || die "--timeout requires seconds"
            TIMEOUT_SECONDS=$2
            shift 2
            ;;
        --quant-model)
            [[ $# -ge 2 ]] || die "--quant-model requires a file"
            QUANT_MODEL=$2
            shift 2
            ;;
        --skip-acceptance)
            SKIP_ACCEPTANCE=true
            shift
            ;;
        --skip-blas)
            SKIP_BLAS=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "unknown argument: $1"
            ;;
    esac
done

[[ $RUNS =~ ^[1-9][0-9]*$ ]] || die "--runs must be a positive integer"
[[ $TIMEOUT_SECONDS =~ ^[1-9][0-9]*$ ]] || die "--timeout must be a positive integer"
[[ $EUID -ne 0 ]] || die "run as the unprivileged Snack-GPT account, not root"

if [[ -z $OUTPUT_DIRECTORY ]]; then
    OUTPUT_DIRECTORY=$HOME/whisper-benchmark-$(date -u +%Y%m%dT%H%M%SZ)
fi
OUTPUT_DIRECTORY=$(realpath -m "$OUTPUT_DIRECTORY")
RUNS_DIRECTORY=$OUTPUT_DIRECTORY/runs
EVIDENCE_DIRECTORY=$OUTPUT_DIRECTORY/evidence
BUILDS_DIRECTORY=$OUTPUT_DIRECTORY/builds
INDEX_PATH=$OUTPUT_DIRECTORY/runs.tsv

for command in awk bwrap cmake git grep sha256sum shuf timeout; do
    command -v "$command" >/dev/null 2>&1 || die "required command is missing: $command"
done
[[ -x $PYTHON ]] || PYTHON=$(command -v python3 || true)
[[ -n $PYTHON && -x $PYTHON ]] || die "Python 3 is required"
[[ -x $WHISPER_BINARY ]] || die "missing Whisper binary: $WHISPER_BINARY"
[[ -f $WHISPER_MODEL ]] || die "missing Whisper model: $WHISPER_MODEL"
[[ -f $WHISPER_AUDIO ]] || die "missing audio fixture: $WHISPER_AUDIO"
[[ -f $PREFIX/bin/whisper-cli.commit ]] || die "missing Whisper commit evidence"
WHISPER_COMMIT=$(<"$PREFIX/bin/whisper-cli.commit")
[[ -r /proc/device-tree/model ]] || die "cannot identify Raspberry Pi model"
MODEL_NAME=$(tr -d '\0' </proc/device-tree/model)
[[ $MODEL_NAME == *"Raspberry Pi 3 Model B Plus"* ]] || {
    die "benchmark requires a Raspberry Pi 3B+; found: $MODEL_NAME"
}
if [[ -n $QUANT_MODEL ]]; then
    QUANT_MODEL=$(realpath "$QUANT_MODEL")
    [[ -f $QUANT_MODEL ]] || die "quantized model does not exist: $QUANT_MODEL"
fi
if [[ $SKIP_BLAS == false ]]; then
    [[ -f $WHISPER_SOURCE/CMakeLists.txt ]] || die "missing Whisper source: $WHISPER_SOURCE"
    SOURCE_COMMIT=$(git -C "$WHISPER_SOURCE" rev-parse HEAD)
    [[ $SOURCE_COMMIT == "$WHISPER_COMMIT" ]] || {
        die "Whisper source $SOURCE_COMMIT does not match installed commit $WHISPER_COMMIT"
    }
fi

mkdir -p "$RUNS_DIRECTORY" "$EVIDENCE_DIRECTORY" "$BUILDS_DIRECTORY"
printf 'phase\tconfiguration\twarmup\taccepted\twall_seconds\texit_status\tpeak_rss_bytes\trun_directory\n' > "$INDEX_PATH"

snapshot_pi() {
    local destination=$1
    {
        printf 'utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        if [[ -r /sys/class/thermal/thermal_zone0/temp ]]; then
            printf 'temperature_millidegrees_c='
            cat /sys/class/thermal/thermal_zone0/temp
        fi
        if [[ -r /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq ]]; then
            printf 'cpu0_frequency_khz='
            cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq
        fi
        if command -v vcgencmd >/dev/null 2>&1; then
            vcgencmd get_throttled
        fi
    } > "$destination"
}

process_tree_rss_kib() {
    local root_pid=$1 process_id rss_kib children_path child
    local total_kib=0
    local -a pending=("$root_pid") children=()

    while ((${#pending[@]})); do
        process_id=${pending[0]}
        pending=("${pending[@]:1}")
        if [[ -r /proc/$process_id/status ]]; then
            rss_kib=$(awk '/^VmRSS:/ { print $2; exit }' "/proc/$process_id/status")
            total_kib=$((total_kib + ${rss_kib:-0}))
        fi
        children_path=/proc/$process_id/task/$process_id/children
        if [[ -r $children_path ]]; then
            read -r -a children < "$children_path" || true
            for child in "${children[@]}"; do
                pending+=("$child")
            done
        fi
    done
    printf '%s\n' "$total_kib"
}

capture_evidence() {
    cat "$PREFIX/bin/whisper-cli.commit" > "$EVIDENCE_DIRECTORY/whisper-commit.txt"
    sha256sum "$WHISPER_BINARY" "$WHISPER_MODEL" "$WHISPER_AUDIO" \
        > "$EVIDENCE_DIRECTORY/sha256.txt"
    if [[ -n $QUANT_MODEL ]]; then
        sha256sum "$QUANT_MODEL" >> "$EVIDENCE_DIRECTORY/sha256.txt"
    fi
    uname -a > "$EVIDENCE_DIRECTORY/uname.txt"
    cat /etc/os-release > "$EVIDENCE_DIRECTORY/os-release.txt"
    printf '%s\n' "$MODEL_NAME" > "$EVIDENCE_DIRECTORY/device-model.txt"
    "$WHISPER_BINARY" --help > "$EVIDENCE_DIRECTORY/whisper-help.txt" 2>&1
    if [[ -f $WHISPER_SOURCE/build/CMakeCache.txt ]]; then
        cp "$WHISPER_SOURCE/build/CMakeCache.txt" "$EVIDENCE_DIRECTORY/CMakeCache.production.txt"
    fi
    if [[ -f $WHISPER_SOURCE/build/compile_commands.json ]]; then
        cp "$WHISPER_SOURCE/build/compile_commands.json" \
            "$EVIDENCE_DIRECTORY/compile_commands.production.json"
    fi
    {
        printf 'runs=%s\n' "$RUNS"
        printf 'timeout_seconds=%s\n' "$TIMEOUT_SECONDS"
        printf 'target_seconds=%s\n' "$TARGET_SECONDS"
        printf 'skip_acceptance=%s\n' "$SKIP_ACCEPTANCE"
        printf 'skip_blas=%s\n' "$SKIP_BLAS"
        printf 'quant_model=%s\n' "$QUANT_MODEL"
    } > "$EVIDENCE_DIRECTORY/benchmark-options.txt"
}

benchmark_one() {
    local phase=$1
    local configuration=$2
    local warmup=$3
    local binary=$4
    local model=$5
    local openblas_threads=$6
    shift 6
    local run_id run_directory output_prefix started_ns finished_ns status command_pid
    local accepted=false current_rss_kib=0 peak_rss_kib=0 peak_rss_bytes=0
    local -a command

    run_id=$(date -u +%Y%m%dT%H%M%S)-$(date +%N)
    run_directory=$RUNS_DIRECTORY/$phase/$configuration/$run_id
    output_prefix=$run_directory/transcript
    mkdir -p "$run_directory"

    command=(
        timeout --signal=KILL "$TIMEOUT_SECONDS"
        bwrap --unshare-net --bind / / -- env
    )
    if [[ -n $openblas_threads ]]; then
        command+=("OPENBLAS_NUM_THREADS=$openblas_threads")
    else
        command+=(-u OPENBLAS_NUM_THREADS)
    fi
    command+=(
        "$binary" "$@"
        -m "$model"
        -f "$WHISPER_AUDIO"
        -l en -otxt -of "$output_prefix" -nt
    )

    printf '%q ' "${command[@]}" > "$run_directory/command.txt"
    printf '\n' >> "$run_directory/command.txt"
    {
        printf 'phase=%s\n' "$phase"
        printf 'configuration=%s\n' "$configuration"
        printf 'warmup=%s\n' "$warmup"
        printf 'binary=%s\n' "$binary"
        printf 'model=%s\n' "$model"
        printf 'openblas_num_threads=%s\n' "$openblas_threads"
    } > "$run_directory/metadata.txt"
    sha256sum "$binary" "$model" "$WHISPER_AUDIO" > "$run_directory/sha256.txt"
    snapshot_pi "$run_directory/before.txt"
    started_ns=$(date +%s%N)

    set +e
    "${command[@]}" \
        > "$run_directory/stdout.txt" \
        2> "$run_directory/stderr.txt" &
    command_pid=$!
    while kill -0 "$command_pid" 2>/dev/null; do
        current_rss_kib=$(process_tree_rss_kib "$command_pid")
        if ((current_rss_kib > peak_rss_kib)); then
            peak_rss_kib=$current_rss_kib
        fi
        sleep 0.01
    done
    wait "$command_pid"
    status=$?
    set -e

    finished_ns=$(date +%s%N)
    awk -v start="$started_ns" -v finish="$finished_ns" \
        'BEGIN { printf "%.6f\n", (finish - start) / 1000000000 }' \
        > "$run_directory/wall-seconds.txt"
    printf '%s\n' "$status" > "$run_directory/exit-status.txt"
    snapshot_pi "$run_directory/after.txt"

    if [[ $status -eq 0 && -f $output_prefix.txt ]] \
        && grep -Fqi two "$output_prefix.txt" \
        && grep -Fqi eggs "$output_prefix.txt"; then
        accepted=true
    fi
    printf '%s\n' "$accepted" > "$run_directory/accepted.txt"
    peak_rss_bytes=$((peak_rss_kib * 1024))
    printf 'peak_rss_bytes=%s\n' "$peak_rss_bytes" > "$run_directory/resource.txt"

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$phase" "$configuration" "$warmup" "$accepted" \
        "$(<"$run_directory/wall-seconds.txt")" "$status" "$peak_rss_bytes" \
        "$run_directory" >> "$INDEX_PATH"
    printf '%-9s %-18s %-8s %7ss\n' \
        "$phase" "$configuration" "$accepted" "$(<"$run_directory/wall-seconds.txt")"
}

run_phase() {
    local phase=$1
    local dispatcher=$2
    shift 2
    local configuration repetition
    local -a configurations=("$@")
    local -a schedule=()

    echo
    echo "Running $phase warm-ups..."
    for configuration in "${configurations[@]}"; do
        "$dispatcher" "$configuration" true
    done
    for ((repetition = 1; repetition <= RUNS; repetition++)); do
        schedule+=("${configurations[@]}")
    done
    mapfile -t schedule < <(printf '%s\n' "${schedule[@]}" | shuf)
    printf '%s\n' "${schedule[@]}" > "$OUTPUT_DIRECTORY/$phase-schedule.txt"

    echo "Running $phase measurements..."
    for configuration in "${schedule[@]}"; do
        "$dispatcher" "$configuration" false
    done
}

select_winner() {
    local phase=$1
    "$PYTHON" - "$INDEX_PATH" "$phase" "$RUNS" <<'PY'
import csv
import statistics
import sys

index_path, phase, expected_text = sys.argv[1:]
expected = int(expected_text)
groups = {}
with open(index_path, encoding="utf-8", newline="") as source:
    for row in csv.DictReader(source, delimiter="\t"):
        if row["phase"] == phase and row["warmup"] == "false":
            groups.setdefault(row["configuration"], []).append(row)

candidates = []
for configuration, rows in groups.items():
    if len(rows) != expected or any(row["accepted"] != "true" for row in rows):
        continue
    median = statistics.median(float(row["wall_seconds"]) for row in rows)
    candidates.append((median, configuration))
if not candidates:
    raise SystemExit(f"no fully accepted configuration in phase {phase}")
print(min(candidates)[1])
PY
}

generate_report() {
    "$PYTHON" - "$INDEX_PATH" "$OUTPUT_DIRECTORY" "$TARGET_SECONDS" "$RUNS" "$SCRIPT_STATE" <<'PY'
import csv
import json
from pathlib import Path
import re
import statistics
import sys

index_path = Path(sys.argv[1])
output_directory = Path(sys.argv[2])
target_seconds = float(sys.argv[3])
expected_runs = int(sys.argv[4])
script_state = sys.argv[5]

rows = []
if index_path.exists():
    with index_path.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source, delimiter="\t"))

timing_pattern = re.compile(
    r"^\s*(whisper_[^:]+):\s+(.+?time)\s*=\s*([0-9.]+)\s*ms",
    re.MULTILINE,
)

def read_key_values(path):
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
        elif ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    return values

runs = []
for row in rows:
    run_directory = Path(row["run_directory"])
    stderr = (run_directory / "stderr.txt").read_text(encoding="utf-8", errors="replace")
    transcript_path = run_directory / "transcript.txt"
    transcript = transcript_path.read_text(encoding="utf-8", errors="replace").strip() if transcript_path.exists() else ""
    timings = {
        f"{function}.{label.strip().replace(' ', '_')}": float(value)
        for function, label, value in timing_pattern.findall(stderr)
    }
    runs.append(
        {
            "phase": row["phase"],
            "configuration": row["configuration"],
            "warmup": row["warmup"] == "true",
            "accepted": row["accepted"] == "true",
            "wall_seconds": float(row["wall_seconds"]),
            "exit_status": int(row["exit_status"]),
            "peak_rss_bytes": int(float(row["peak_rss_bytes"])),
            "transcript": transcript,
            "whisper_timings_ms": timings,
            "command": (run_directory / "command.txt").read_text(encoding="utf-8").strip(),
            "metadata": read_key_values(run_directory / "metadata.txt"),
            "hardware_before": read_key_values(run_directory / "before.txt"),
            "hardware_after": read_key_values(run_directory / "after.txt"),
            "resource_usage": read_key_values(run_directory / "resource.txt"),
            "artifacts": str(run_directory.relative_to(output_directory)),
        }
    )

groups = {}
for run in runs:
    if not run["warmup"]:
        groups.setdefault((run["phase"], run["configuration"]), []).append(run)

configurations = []
for (phase, configuration), measured in sorted(groups.items()):
    wall_times = [run["wall_seconds"] for run in measured]
    accepted_runs = sum(run["accepted"] for run in measured)
    fully_accepted = len(measured) == expected_runs and accepted_runs == expected_runs
    configurations.append(
        {
            "phase": phase,
            "configuration": configuration,
            "run_count": len(measured),
            "accepted_runs": accepted_runs,
            "fully_accepted": fully_accepted,
            "wall_seconds": {
                "all": wall_times,
                "minimum": min(wall_times),
                "median": statistics.median(wall_times),
                "mean": statistics.mean(wall_times),
                "maximum": max(wall_times),
            },
            "peak_rss_bytes": max(run["peak_rss_bytes"] for run in measured),
            "meets_transcription_target": fully_accepted and statistics.median(wall_times) <= target_seconds,
        }
    )

selected_path = output_directory / "selected-configuration.txt"
report = {
    "schema_version": 1,
    "state": script_state,
    "target_seconds": target_seconds,
    "expected_runs_per_configuration": expected_runs,
    "configurations": configurations,
    "runs": runs,
    "selected_configuration": read_key_values(selected_path),
    "evidence_directory": "evidence",
}
(output_directory / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

lines = [
    "# whisper.cpp benchmark summary",
    "",
    f"State: **{script_state}**  ",
    f"Target median: **{target_seconds:.2f} seconds**  ",
    f"Measured runs per configuration: **{expected_runs}**",
    "",
    "| Phase | Configuration | Accepted | Median | Range | Peak RSS | Target |",
    "| --- | --- | ---: | ---: | ---: | ---: | --- |",
]
for item in configurations:
    timing = item["wall_seconds"]
    target = "yes" if item["meets_transcription_target"] else "no"
    lines.append(
        f"| {item['phase']} | {item['configuration']} | "
        f"{item['accepted_runs']}/{item['run_count']} | {timing['median']:.3f} s | "
        f"{timing['minimum']:.3f}-{timing['maximum']:.3f} s | "
        f"{item['peak_rss_bytes'] / 1024 / 1024:.1f} MiB | {target} |"
    )
lines.extend(
    [
        "",
        "Raw commands, transcripts, Whisper timing logs, resource measurements,",
        "and temperature/frequency snapshots are retained under `runs/`.",
    ]
)
(output_directory / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

finalize() {
    local status=$?
    trap - EXIT
    if [[ -f $INDEX_PATH ]]; then
        generate_report || true
        echo
        echo "Benchmark report: $OUTPUT_DIRECTORY/summary.md"
        echo "Machine-readable report: $OUTPUT_DIRECTORY/summary.json"
    fi
    exit "$status"
}
trap finalize EXIT

dispatch_threads() {
    local configuration=$1 warmup=$2
    case "$configuration" in
        baseline) benchmark_one threads baseline "$warmup" "$WHISPER_BINARY" "$WHISPER_MODEL" "" ;;
        t1) benchmark_one threads t1 "$warmup" "$WHISPER_BINARY" "$WHISPER_MODEL" "" -t 1 ;;
        t2) benchmark_one threads t2 "$warmup" "$WHISPER_BINARY" "$WHISPER_MODEL" "" -t 2 ;;
        t3) benchmark_one threads t3 "$warmup" "$WHISPER_BINARY" "$WHISPER_MODEL" "" -t 3 ;;
        t4) benchmark_one threads t4 "$warmup" "$WHISPER_BINARY" "$WHISPER_MODEL" "" -t 4 ;;
    esac
}

dispatch_context() {
    local configuration=$1 warmup=$2
    case "$configuration" in
        default) benchmark_one context default "$warmup" "$WHISPER_BINARY" "$WHISPER_MODEL" "" -t "$SELECTED_THREADS" ;;
        768) benchmark_one context 768 "$warmup" "$WHISPER_BINARY" "$WHISPER_MODEL" "" -t "$SELECTED_THREADS" -ac 768 ;;
        512) benchmark_one context 512 "$warmup" "$WHISPER_BINARY" "$WHISPER_MODEL" "" -t "$SELECTED_THREADS" -ac 512 ;;
    esac
}

dispatch_blas() {
    local configuration=$1 warmup=$2
    case "$configuration" in
        native) benchmark_one blas native "$warmup" "$NATIVE_BINARY" "$WHISPER_MODEL" "" "${SELECTED_FLAGS[@]}" ;;
        blas-1) benchmark_one blas blas-1 "$warmup" "$BLAS_BINARY" "$WHISPER_MODEL" 1 "${SELECTED_FLAGS[@]}" ;;
        blas-2) benchmark_one blas blas-2 "$warmup" "$BLAS_BINARY" "$WHISPER_MODEL" 2 "${SELECTED_FLAGS[@]}" ;;
        blas-4) benchmark_one blas blas-4 "$warmup" "$BLAS_BINARY" "$WHISPER_MODEL" 4 "${SELECTED_FLAGS[@]}" ;;
    esac
}

dispatch_decode() {
    local configuration=$1 warmup=$2
    case "$configuration" in
        default) benchmark_one decode default "$warmup" "$SELECTED_BINARY" "$WHISPER_MODEL" "$SELECTED_BLAS_THREADS" "${SELECTED_FLAGS[@]}" ;;
        no-fallback) benchmark_one decode no-fallback "$warmup" "$SELECTED_BINARY" "$WHISPER_MODEL" "$SELECTED_BLAS_THREADS" "${SELECTED_FLAGS[@]}" -nf ;;
        search-1) benchmark_one decode search-1 "$warmup" "$SELECTED_BINARY" "$WHISPER_MODEL" "$SELECTED_BLAS_THREADS" "${SELECTED_FLAGS[@]}" -bs 1 -bo 1 ;;
    esac
}

dispatch_model() {
    local configuration=$1 warmup=$2
    case "$configuration" in
        tiny-en) benchmark_one model tiny-en "$warmup" "$SELECTED_BINARY" "$WHISPER_MODEL" "$SELECTED_BLAS_THREADS" "${SELECTED_FLAGS[@]}" ;;
        tiny-en-q5-1) benchmark_one model tiny-en-q5-1 "$warmup" "$SELECTED_BINARY" "$QUANT_MODEL" "$SELECTED_BLAS_THREADS" "${SELECTED_FLAGS[@]}" ;;
    esac
}

echo "Writing benchmark data to $OUTPUT_DIRECTORY"
capture_evidence

if [[ $SKIP_ACCEPTANCE == false ]]; then
    echo "Running the end-to-end acceptance baseline..."
    (
        cd "$REPOSITORY_ROOT"
        "$PYTHON" -m snack_gpt.voice_probe docs/voice-probe.pi.json \
            --output "$OUTPUT_DIRECTORY/voice-probe-results.before.json"
    )
fi

SCRIPT_STATE=threads
run_phase threads dispatch_threads baseline t1 t2 t3 t4
THREAD_WINNER=$(select_winner threads) || die "thread phase produced no acceptable winner"
if [[ $THREAD_WINNER == baseline ]]; then
    SELECTED_THREADS=4
else
    SELECTED_THREADS=${THREAD_WINNER#t}
fi
echo "Selected Whisper threads: $SELECTED_THREADS ($THREAD_WINNER)"

SCRIPT_STATE=context
run_phase context dispatch_context default 768 512
CONTEXT_WINNER=$(select_winner context) || die "context phase produced no acceptable winner"
SELECTED_FLAGS=(-t "$SELECTED_THREADS")
if [[ $CONTEXT_WINNER != default ]]; then
    SELECTED_FLAGS+=(-ac "$CONTEXT_WINNER")
fi
echo "Selected audio context: $CONTEXT_WINNER"

SELECTED_BINARY=$WHISPER_BINARY
SELECTED_BLAS_THREADS=
SELECTED_MODEL=$WHISPER_MODEL
if [[ $SKIP_BLAS == false ]]; then
    SCRIPT_STATE=building-blas
    BLAS_BUILD=$BUILDS_DIRECTORY/blas
    NATIVE_BUILD=$BUILDS_DIRECTORY/native
    echo "Building isolated BLAS and native variants..."
    cmake -S "$WHISPER_SOURCE" -B "$BLAS_BUILD" \
        -DCMAKE_BUILD_TYPE=Release -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
        -DGGML_BLAS=ON > "$OUTPUT_DIRECTORY/cmake-blas.log" 2>&1
    cmake --build "$BLAS_BUILD" --config Release --parallel 2 --target whisper-cli \
        > "$OUTPUT_DIRECTORY/build-blas.log" 2>&1
    cmake -S "$WHISPER_SOURCE" -B "$NATIVE_BUILD" \
        -DCMAKE_BUILD_TYPE=Release -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
        -DGGML_BLAS=OFF > "$OUTPUT_DIRECTORY/cmake-native.log" 2>&1
    cmake --build "$NATIVE_BUILD" --config Release --parallel 2 --target whisper-cli \
        > "$OUTPUT_DIRECTORY/build-native.log" 2>&1
    BLAS_BINARY=$BLAS_BUILD/bin/whisper-cli
    NATIVE_BINARY=$NATIVE_BUILD/bin/whisper-cli
    [[ -x $BLAS_BINARY && -x $NATIVE_BINARY ]] || die "benchmark builds did not produce whisper-cli"
    sha256sum "$BLAS_BINARY" "$NATIVE_BINARY" > "$EVIDENCE_DIRECTORY/sha256-builds.txt"
    cp "$BLAS_BUILD/CMakeCache.txt" "$EVIDENCE_DIRECTORY/CMakeCache.blas.txt"
    cp "$NATIVE_BUILD/CMakeCache.txt" "$EVIDENCE_DIRECTORY/CMakeCache.native.txt"
    cp "$BLAS_BUILD/compile_commands.json" "$EVIDENCE_DIRECTORY/compile_commands.blas.json"
    cp "$NATIVE_BUILD/compile_commands.json" "$EVIDENCE_DIRECTORY/compile_commands.native.json"

    SCRIPT_STATE=blas
    run_phase blas dispatch_blas native blas-1 blas-2 blas-4
    BLAS_WINNER=$(select_winner blas) || die "BLAS phase produced no acceptable winner"
    case "$BLAS_WINNER" in
        native)
            SELECTED_BINARY=$NATIVE_BINARY
            SELECTED_BLAS_THREADS=
            ;;
        blas-*)
            SELECTED_BINARY=$BLAS_BINARY
            SELECTED_BLAS_THREADS=${BLAS_WINNER#blas-}
            ;;
    esac
    echo "Selected CPU backend: $BLAS_WINNER"
fi

SCRIPT_STATE=decode
run_phase decode dispatch_decode default no-fallback search-1
DECODE_WINNER=$(select_winner decode) || die "decode phase produced no acceptable winner"
case "$DECODE_WINNER" in
    no-fallback) SELECTED_FLAGS+=(-nf) ;;
    search-1) SELECTED_FLAGS+=(-bs 1 -bo 1) ;;
esac
echo "Selected decoding configuration: $DECODE_WINNER"

if [[ -n $QUANT_MODEL ]]; then
    SCRIPT_STATE=model
    run_phase model dispatch_model tiny-en tiny-en-q5-1
    MODEL_WINNER=$(select_winner model) || die "model phase produced no acceptable winner"
    if [[ $MODEL_WINNER == tiny-en-q5-1 ]]; then
        SELECTED_MODEL=$QUANT_MODEL
    fi
    echo "Selected model: $MODEL_WINNER"
fi

{
    printf 'thread_configuration=%s\n' "$THREAD_WINNER"
    printf 'threads=%s\n' "$SELECTED_THREADS"
    printf 'audio_context=%s\n' "$CONTEXT_WINNER"
    printf 'binary=%s\n' "$SELECTED_BINARY"
    printf 'model=%s\n' "$SELECTED_MODEL"
    printf 'openblas_num_threads=%s\n' "$SELECTED_BLAS_THREADS"
    printf 'decode_configuration=%s\n' "$DECODE_WINNER"
    printf 'flags='
    printf '%q ' "${SELECTED_FLAGS[@]}"
    printf '\n'
} > "$OUTPUT_DIRECTORY/selected-configuration.txt"

SCRIPT_STATE=completed
echo "Benchmark completed."