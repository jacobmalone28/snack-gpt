# Benchmarking whisper.cpp transcription on Raspberry Pi 3B+

Use this procedure to test the latency hypotheses in
[`whisper-transcription-latency-research.md`](whisper-transcription-latency-research.md)
without changing the production adapter or acceptance manifest. Run it on the
provisioned Raspberry Pi 3B+ with the same `report.wav`, whisper.cpp commit, and
`tiny.en` model used by the voice probe.

The promotion target is a median transcription wall time at or below 9.16
seconds. Every measured run must remain below the 30-second hard timeout,
contain `two` and `eggs`, and execute inside Bubblewrap's isolated network
namespace.

## Run the automated benchmark

The repository script performs the acceptance baseline, evidence capture,
randomized thread and context sweeps, isolated BLAS/native builds, decoding
tests, winner selection, and report generation:

```console
scripts/benchmark-whisper.sh
```

It writes raw per-run artifacts plus `summary.json`, `summary.md`, `runs.tsv`,
and `selected-configuration.txt` under
`~/whisper-benchmark-<UTC timestamp>`. Use `--output DIRECTORY` to choose a
stable destination. A pre-downloaded quantized model can be included with
`--quant-model FILE`; the script never downloads benchmark inputs or replaces
the provisioned binary and model.

Use `scripts/benchmark-whisper.sh --help` for controls such as run count,
timeout, skipping the initial acceptance probe, or skipping the BLAS builds.
The remaining sections describe the protocol implemented by the script and how
to interpret its artifacts.

## 1. Establish the acceptance baseline

Run the normal probe before changing or rebuilding anything:

```console
python3 -m snack_gpt.voice_probe docs/voice-probe.pi.json \
  --output voice-probe-results.before.json
```

Keep that report. It records the end-to-end baseline and evidence hashes. Stop
if the probe fails transcript, extraction, offline, or hardware acceptance;
tuning a failing baseline would confound the results.

Install GNU `time` while the Pi is still network-connected if `/usr/bin/time`
is absent:

```console
sudo apt-get update
sudo apt-get install time
```

No benchmarked inference command needs network access.

## 2. Create a run directory and capture evidence

Run as the same unprivileged account used for the acceptance probe:

```console
export BENCHMARK_ROOT="$HOME/whisper-benchmark-$(date -u +%Y%m%dT%H%M%SZ)"
export WHISPER_BINARY=/opt/snack-gpt/bin/whisper-cli
export WHISPER_MODEL=/opt/snack-gpt/models/ggml-tiny.en.bin
export WHISPER_AUDIO=/opt/snack-gpt/probe/report.wav
mkdir -p "$BENCHMARK_ROOT/runs"

cat /opt/snack-gpt/bin/whisper-cli.commit > "$BENCHMARK_ROOT/whisper-commit.txt"
sha256sum "$WHISPER_BINARY" "$WHISPER_MODEL" "$WHISPER_AUDIO" \
  > "$BENCHMARK_ROOT/sha256.txt"
uname -a > "$BENCHMARK_ROOT/uname.txt"
cat /etc/os-release > "$BENCHMARK_ROOT/os-release.txt"
cp /opt/snack-gpt/src/whisper.cpp/build/CMakeCache.txt \
  "$BENCHMARK_ROOT/CMakeCache.baseline.txt"
if test -f /opt/snack-gpt/src/whisper.cpp/build/compile_commands.json; then
  cp /opt/snack-gpt/src/whisper.cpp/build/compile_commands.json \
    "$BENCHMARK_ROOT/compile_commands.baseline.json"
fi
"$WHISPER_BINARY" --help > "$BENCHMARK_ROOT/whisper-help.txt" 2>&1
```

The first benchmark run's stderr includes `whisper_print_system_info()`. Retain
it with the per-run timing output.

## 3. Define the measurement function

Paste this function into the same Bash session. It invokes `whisper-cli`
directly because the production adapter always adds `-np`, which suppresses the
internal timing breakdown. The remaining production arguments are unchanged.

```bash
snapshot_pi() {
  local destination=$1
  {
    printf 'utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if test -r /sys/class/thermal/thermal_zone0/temp; then
      printf 'temperature_millidegrees_c=' 
      cat /sys/class/thermal/thermal_zone0/temp
    fi
    if test -r /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq; then
      printf 'cpu0_frequency_khz='
      cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq
    fi
    if command -v vcgencmd >/dev/null 2>&1; then
      vcgencmd get_throttled
    fi
  } > "$destination"
}

benchmark_one() {
  local configuration=$1
  local binary=$2
  shift 2
  local run_id run_directory output_prefix started_ns finished_ns status
  run_id="$(date -u +%Y%m%dT%H%M%S)-$(date +%N)"
  run_directory="$BENCHMARK_ROOT/runs/$configuration/$run_id"
  output_prefix="$run_directory/transcript"
  mkdir -p "$run_directory"

  printf '%q ' \
    "$binary" "$@" \
    -m "$WHISPER_MODEL" \
    -f "$WHISPER_AUDIO" \
    -l en -otxt -of "$output_prefix" -nt \
    > "$run_directory/command.txt"
  printf '\n' >> "$run_directory/command.txt"
  printf 'OPENBLAS_NUM_THREADS=%s\n' "${OPENBLAS_NUM_THREADS-}" \
    > "$run_directory/environment.txt"
  snapshot_pi "$run_directory/before.txt"
  started_ns=$(date +%s%N)

  set +e
  /usr/bin/time -v -o "$run_directory/resource.txt" \
    timeout --signal=KILL 30 \
    bwrap --unshare-net --bind / / -- \
    "$binary" "$@" \
      -m "$WHISPER_MODEL" \
      -f "$WHISPER_AUDIO" \
      -l en -otxt -of "$output_prefix" -nt \
    > "$run_directory/stdout.txt" \
    2> "$run_directory/stderr.txt"
  status=$?
  set -e

  finished_ns=$(date +%s%N)
  awk -v start="$started_ns" -v finish="$finished_ns" \
    'BEGIN { printf "%.6f\n", (finish - start) / 1000000000 }' \
    > "$run_directory/wall-seconds.txt"
  printf '%s\n' "$status" > "$run_directory/exit-status.txt"
  snapshot_pi "$run_directory/after.txt"

  if test "$status" -eq 0 \
      && grep -Fqi two "$output_prefix.txt" \
      && grep -Fqi eggs "$output_prefix.txt"; then
    printf 'accepted\n' > "$run_directory/verdict.txt"
  else
    printf 'rejected\n' > "$run_directory/verdict.txt"
  fi

  printf '%s %s %ss\n' \
    "$configuration" "$(cat "$run_directory/verdict.txt")" \
    "$(cat "$run_directory/wall-seconds.txt")"
}
```

Do not add `-np`: `stderr.txt` must retain model load, mel, encode, decode, and
total timings. A status of 137 indicates the 30-second timeout killed the run.

## 4. Measure the baseline and thread sweep

First perform one discarded warm-up for each configuration. Then run every
configuration five times in randomized order:

```console
unset OPENBLAS_NUM_THREADS
benchmark_one warmup-baseline "$WHISPER_BINARY"
for threads in 1 2 3 4; do
  benchmark_one "warmup-t$threads" "$WHISPER_BINARY" -t "$threads"
done

for repetition in 1 2 3 4 5; do
  printf '%s\n' baseline t1 t2 t3 t4
done | shuf | while read -r configuration; do
  case "$configuration" in
    baseline) benchmark_one baseline "$WHISPER_BINARY" ;;
    t1) benchmark_one t1 "$WHISPER_BINARY" -t 1 ;;
    t2) benchmark_one t2 "$WHISPER_BINARY" -t 2 ;;
    t3) benchmark_one t3 "$WHISPER_BINARY" -t 3 ;;
    t4) benchmark_one t4 "$WHISPER_BINARY" -t 4 ;;
  esac
done
```

`-t 4` is a control, not an expected optimization: it matches the CLI default
on this four-core Pi. Select the thread count with the lowest accepted median,
not the fastest individual run.

## 5. Test audio context

Hold the winning thread count fixed and test the default context against `768`
and `512`. Replace `THREADS` below with the selected value:

```console
export THREADS=4
for context in default 768 512; do
  case "$context" in
    default) benchmark_one "warmup-context-default" "$WHISPER_BINARY" -t "$THREADS" ;;
    *) benchmark_one "warmup-context-$context" "$WHISPER_BINARY" -t "$THREADS" -ac "$context" ;;
  esac
done

for repetition in 1 2 3 4 5; do
  printf '%s\n' default 768 512
done | shuf | while read -r context; do
  case "$context" in
    default) benchmark_one context-default "$WHISPER_BINARY" -t "$THREADS" ;;
    *) benchmark_one "context-$context" "$WHISPER_BINARY" -t "$THREADS" -ac "$context" ;;
  esac
done
```

Reject an audio-context setting if any measured transcript misses either
required term. Because `audio_ctx` is experimental, passing this one fixture is
necessary but not sufficient evidence for production quality.

## 6. Compare OpenBLAS and native ggml

Build separate binaries; do not overwrite `/opt/snack-gpt/bin/whisper-cli`.
Keeping separate build directories prevents stale CMake settings from crossing
between variants.

```console
export WHISPER_SOURCE=/opt/snack-gpt/src/whisper.cpp
sudo cmake -S "$WHISPER_SOURCE" -B "$WHISPER_SOURCE/build-benchmark-blas" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
  -DGGML_BLAS=ON
sudo cmake --build "$WHISPER_SOURCE/build-benchmark-blas" \
  --config Release --parallel 2 --target whisper-cli

sudo cmake -S "$WHISPER_SOURCE" -B "$WHISPER_SOURCE/build-benchmark-native" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
  -DGGML_BLAS=OFF
sudo cmake --build "$WHISPER_SOURCE/build-benchmark-native" \
  --config Release --parallel 2 --target whisper-cli

export BLAS_BINARY="$WHISPER_SOURCE/build-benchmark-blas/bin/whisper-cli"
export NATIVE_BINARY="$WHISPER_SOURCE/build-benchmark-native/bin/whisper-cli"
sha256sum "$BLAS_BINARY" "$NATIVE_BINARY" > "$BENCHMARK_ROOT/sha256-builds.txt"
cp "$WHISPER_SOURCE/build-benchmark-blas/CMakeCache.txt" \
  "$BENCHMARK_ROOT/CMakeCache.blas.txt"
cp "$WHISPER_SOURCE/build-benchmark-native/CMakeCache.txt" \
  "$BENCHMARK_ROOT/CMakeCache.native.txt"
cp "$WHISPER_SOURCE/build-benchmark-blas/compile_commands.json" \
  "$BENCHMARK_ROOT/compile_commands.blas.json"
cp "$WHISPER_SOURCE/build-benchmark-native/compile_commands.json" \
  "$BENCHMARK_ROOT/compile_commands.native.json"
```

Hold Whisper's selected `-t` value and selected audio context fixed. Benchmark
the native binary, then the BLAS binary with `OPENBLAS_NUM_THREADS=1`, `2`, and
`4`. Perform one warm-up per configuration and five randomized measured runs.
Set `OPENBLAS_NUM_THREADS` immediately before each BLAS call and record it in the
configuration name. Do not compare builds whose stderr reports unexpected
architecture or backend information.

## 7. Test lower-priority variants

Only continue when the preceding phase has a stable accepted winner. Change one
item at a time and use the same warm-up, five-run randomization, evidence, and
acceptance rules.

| Phase | Comparison |
| --- | --- |
| Decode fallback | Winner versus `-nf` |
| Decode search | Winner versus `-bs 1 -bo 1` |
| Quantization | `tiny.en` versus separately hashed `tiny.en-q5_1` |
| Silence | Winner versus VAD, only if the fixture contains material removable silence |
| Warm start | CLI winner versus an official server or C API worker retaining one context |

For quantization, record the model SHA-256 and use a separate model path. For
VAD, record the VAD model hash and include its inference time and memory. Do not
shorten `report.wav` merely to reach the target.

Attempt a warm-start benchmark only after internal timings show model loading is
large enough to affect the decision. A second CLI process is not a warm-model
run. The persistent process and caller must share one isolated network
namespace; bind an official server to loopback only, or prefer a C API worker on
a Unix socket. Include worker memory and startup amortization in the report.

## 8. Summarize and decide

For every configuration, report:

- all five wall times and their median;
- Whisper load, mel, encode, decode, and total timings from `stderr.txt`;
- peak RSS from `resource.txt`;
- every transcript and acceptance verdict;
- temperature, frequency, and throttling snapshots;
- binary, model, fixture, source commit, CMake, and compile-command evidence.

Do not silently discard thermal or throttled outliers. Label cold-cache runs and
warm filesystem-cache runs separately. Reject a configuration if any measured
run has a bad transcript, loses offline isolation, exceeds 30 seconds, or lacks
evidence needed to reproduce it.

A variant is promotable only when its repeated accepted median improves the
end-to-end voice probe and preserves all contracts. Re-run the normal probe with
the candidate represented in a temporary manifest or adapter argument, then
compare its processing duration against `voice-probe-results.before.json`.
Transcription at or below 9.16 seconds is required to meet the current 15-second
processing target with extraction and synthesis unchanged; a smaller
improvement only increases hard-timeout margin.
