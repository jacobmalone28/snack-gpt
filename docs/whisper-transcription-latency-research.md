# Reducing whisper.cpp transcription latency on Raspberry Pi 3B+

Research date: 2026-08-25  
Pinned runtime: whisper.cpp v1.8.0, commit
[`41fc9dea`](https://github.com/ggml-org/whisper.cpp/tree/41fc9dea6a4fe056424be86f61164413903fcff4)  
Target: Raspberry Pi 3 Model B Plus, 64-bit Raspberry Pi OS, `tiny.en`

## Conclusion

> **Benchmark update:** On 2026-08-26, five isolated Pi runs with `-t 4 -ac
> 512` all retained `two` and `eggs`. Median transcription wall time was 5.126
> seconds (4.918-5.199 seconds), compared with 23.467 seconds at default audio
> context. The Pi manifest now uses `-ac 512`. A fresh end-to-end voice probe
> must still confirm the projected processing time, and this single fixture
> does not remove upstream's experimental quality warning.

The source review alone identified no flag combination that could be claimed to
reduce the measured 22.43-second transcription to the required 9.16 seconds.
The subsequent controlled Pi benchmark supplied that missing device evidence
for `-ac 512`, subject to the fixture-specific quality limitation above.

Test in this order:

1. Capture whisper.cpp's own load, mel, encode, decode, and total timings. This
   establishes whether a warm worker can save enough time to matter.
2. Sweep `-t 1` through `-t 4`. Passing `-t 4` alone is not an optimization:
   v1.8.0 already defaults to four threads on a four-core Pi.
3. Test `-ac 768` and `-ac 512`. This directly reduces the encoder graph, but
   upstream labels `audio_ctx` experimental and warns it can reduce quality.
4. Compare the existing OpenBLAS build with native ggml CPU kernels, controlling
   both ggml and OpenBLAS thread counts.
5. Only then test `tiny.en-q5_1`, decoding changes, VAD, and a persistent worker.

A true warm start is possible. The official C API permits one initialized
`whisper_context` to serve repeated `whisper_full()` calls, and the official
`whisper-server` loads a model once for repeated HTTP requests. A second
`whisper-cli` process is not a warm model start: every CLI invocation initializes
and frees its own context. It may only benefit from the OS file cache.

## Current constraint

| Stage | Time |
| --- | ---: |
| Transcription | 22.427344 s |
| Extraction | 4.322635 s |
| Warm synthesis | 1.513204 s |
| Total | 28.263183 s |

With extraction and synthesis unchanged, transcription must be at most about
9.16 seconds to meet the 15-second expected target. The current command uses
`tiny.en`, OpenBLAS, one CLI subprocess per report, no explicit thread count,
and Bubblewrap network isolation. It must continue to produce `two` and `eggs`.
These facts come from the local [provisioner](../scripts/provision-voice-probe.sh),
[adapter](../snack_gpt/voice_adapters.py), and [Pi manifest](voice-probe.pi.json).

## Findings

### Measure before tuning

`whisper-cli` calls `whisper_print_timings()` before freeing its context. The
pinned implementation reports model load, mel, sample, encode, decode, prompt,
and total time. Snack-GPT passes `-np`, which suppresses those logs. Run the same
command without `-np` in a benchmark harness and retain stderr; production need
not change to collect this evidence.

Sources: [`cli.cpp`](https://github.com/ggml-org/whisper.cpp/blob/41fc9dea6a4fe056424be86f61164413903fcff4/examples/cli/cli.cpp)
and [`whisper_print_timings()`](https://github.com/ggml-org/whisper.cpp/blob/41fc9dea6a4fe056424be86f61164413903fcff4/src/whisper.cpp).

This decomposition answers the warm-start question. The direct saving from
retaining the model is bounded by the measured load and initialization portion,
not the whole 22.43 seconds.

### Threads

The CLI default is `min(4, hardware_concurrency())`, and its `-t` value is used
for mel, encoder, and decoder work. Therefore `-t 4` reproduces the current
default on this device; it does not create a new speedup. Thread scaling remains
hardware-specific because the cores share memory bandwidth and OpenBLAS can use
its own thread pool.

Source: [v1.8.0 CLI defaults and `--threads`](https://github.com/ggml-org/whisper.cpp/blob/41fc9dea6a4fe056424be86f61164413903fcff4/examples/cli/cli.cpp).

Benchmark `-t 1`, `-t 2`, `-t 3`, and `-t 4`. Let median wall time, frequency,
temperature, memory, and transcript acceptance determine the winner.

### Audio context

The CLI exposes `-ac N` / `--audio-ctx N`. At the library boundary it replaces
the model's default audio context of 1500, and the encoder graph uses the smaller
context. The public header calls this an experimental speed-up technique and
warns that it can significantly reduce output quality.

Sources: [`whisper_full_params.audio_ctx`](https://github.com/ggml-org/whisper.cpp/blob/41fc9dea6a4fe056424be86f61164413903fcff4/include/whisper.h)
and the [encoder graph](https://github.com/ggml-org/whisper.cpp/blob/41fc9dea6a4fe056424be86f61164413903fcff4/src/whisper.cpp).

This makes `-ac 768` and `-ac 512` the most direct latency experiments, but not
safe defaults. Every run must retain `two` and `eggs`; a single successful
transcript is not enough evidence for a quality-sensitive default.

### Decoding controls

The CLI selects beam search when beam size is greater than one. The library
defaults are beam size 5, greedy best-of 5, and temperature increment 0.2. `-nf`
sets the increment to zero; `-bs` and `-bo` change candidate counts. These flags
only help when the affected decode or fallback work occurs, and they change the
search behavior.

Source: [v1.8.0 parameter mapping and sampling selection](https://github.com/ggml-org/whisper.cpp/blob/41fc9dea6a4fe056424be86f61164413903fcff4/examples/cli/cli.cpp).

Inspect decode time and fallback count first. If material, test `-nf`, then
`-bs 1 -bo 1`, separately and with transcript acceptance checks.

### OpenBLAS and native ARM kernels

Upstream documents `GGML_BLAS=1` as CPU encoder acceleration through OpenBLAS.
Pinned ggml also defaults `GGML_NATIVE` on for native builds and exposes
`GGML_CPU_ARM_ARCH`. The source does not establish whether OpenBLAS or native
ggml is faster on a Pi 3B+.

Sources: [BLAS CPU support](https://github.com/ggml-org/whisper.cpp/blob/41fc9dea6a4fe056424be86f61164413903fcff4/README.md#blas-cpu-support-via-openblas),
[ggml build options](https://github.com/ggml-org/whisper.cpp/blob/41fc9dea6a4fe056424be86f61164413903fcff4/ggml/CMakeLists.txt),
and [OpenBLAS thread controls](https://github.com/OpenMathLib/OpenBLAS/wiki/Faq#how-can-i-use-openblas-in-multi-threaded-applications).

Compare `GGML_BLAS=ON` and `OFF`. Retain `compile_commands.json` and
`whisper_print_system_info()` rather than assuming native flags or NEON were
selected. With BLAS enabled, test `OPENBLAS_NUM_THREADS=1`, `2`, and `4` while
holding `-t` fixed to expose oversubscription.

### Quantization

The official pinned download script lists `tiny.en-q5_1`. Upstream says
quantized models use less memory and disk and may be processed more efficiently
depending on hardware; it does not promise lower Pi latency or equal accuracy.

Sources: [official model list](https://github.com/ggml-org/whisper.cpp/blob/41fc9dea6a4fe056424be86f61164413903fcff4/models/download-ggml-model.sh)
and [quantization documentation](https://github.com/ggml-org/whisper.cpp/blob/41fc9dea6a4fe056424be86f61164413903fcff4/README.md#quantization).

Testing requires a new pinned model checksum and evidence hash. Compare latency,
peak RSS, and transcript against unquantized `tiny.en`. This is not the first
experiment because current peak memory, 347 MB, is below capacity and a latency
benefit is unproven.

### VAD and shorter input

v1.8.0 can run a Silero VAD model, extract detected speech, and pass only those
samples to Whisper. Upstream says this can speed inputs with removable
non-speech audio, but it adds another model and inference step.

Source: [v1.8.0 VAD design](https://github.com/ggml-org/whisper.cpp/blob/41fc9dea6a4fe056424be86f61164413903fcff4/README.md#voice-activity-detection-vad).

Measure this fixture's speech and silence first. Shortening a seven-second WAV
does not guarantee proportional savings: without `audio_ctx`, the pinned code
pads mel input and builds the encoder at model context. VAD is lower priority
than `audio_ctx` here and could clip required words. It also adds a model to
provisioning and evidence.

Do not shorten the representative fixture merely to pass latency. If production
capture includes avoidable pre-roll or post-roll, test boundary trimming while
preserving the seven-second end-to-end probe scenario.

## Warm-start options

### Official server

When examples are enabled, v1.8.0 builds `whisper-server`. It accepts repeated
multipart inference requests and has a `/load` endpoint, so it is the cheapest
upstream implementation for measuring model-preload savings.

Source: [v1.8.0 server API](https://github.com/ggml-org/whisper.cpp/blob/41fc9dea6a4fe056424be86f61164413903fcff4/examples/server/README.md).

It listens on TCP, not a Unix socket. Snack-GPT must not expose it outside the
offline sandbox. Worker and caller need one isolated network namespace,
loopback-only binding, lifecycle handling, request limits, and memory accounting.
The current per-stage Bubblewrap invocation does not establish that shared
namespace. Use the server as a benchmark probe first; if savings are small, do
not absorb its HTTP and sandbox complexity.

### C API worker

The cleaner production shape is a small worker that initializes one
`whisper_context`, accepts jobs over a Unix domain socket, calls `whisper_full()`
repeatedly, and frees the context at shutdown. The API says one context must not
be used concurrently, matching Snack-GPT's sequential pipeline.

Source: [v1.8.0 C API lifecycle and thread-safety contract](https://github.com/ggml-org/whisper.cpp/blob/41fc9dea6a4fe056424be86f61164413903fcff4/include/whisper.h).

This mirrors the Piper worker and avoids TCP. Costs include custom native code,
worker failure and timeout handling, model memory held for the worker lifetime,
and a new evidence binary. Implement only after decomposition proves retained
initialization is worth those costs.

## Alternatives

No reviewed primary source demonstrates another offline ASR engine is both
faster and accurate enough on this exact Pi and fixture.

- OpenAI's reference implementation uses PyTorch; it is not a lighter path for
  this CPU-only 1 GB target. `tiny.en` is already the smallest English Whisper
  model. Source: [OpenAI Whisper](https://github.com/openai/whisper#available-models-and-languages).
- Vosk officially supports offline use and Raspberry Pi, but its first-party
  site gives no controlled comparison for this fixture. It is a benchmark
  candidate, not an evidence-backed improvement. Source: [Vosk](https://alphacephei.com/vosk/).
- Pinned whisper.cpp supports distilled `medium.en` and `large-v2`, and warns
  that its missing chunk strategy can reduce quality. Both are larger than
  `tiny.en`. Source: [distilled-model notes](https://github.com/ggml-org/whisper.cpp/blob/41fc9dea6a4fe056424be86f61164413903fcff4/models/README.md#distilled-models).

If tuning cannot reach the target, benchmark Vosk against the same WAV,
acceptance terms, memory limit, and offline sandbox. Do not infer comparative
accuracy or latency from project descriptions.

## Pi benchmark protocol

Use the provisioned `report.wav`, pinned source and model, and Bubblewrap
isolation. Put timing-only changes in a benchmark harness, not the adapter.

For every configuration:

1. Record binary and model SHA-256, commit, CMake cache, compile commands,
   `whisper_print_system_info()`, OS version, and architecture.
2. Reboot or label cold-cache runs. A new CLI after a prior run is warm only at
   the filesystem-cache level.
3. Run one discarded warm-up and at least five measured runs in randomized
   configuration order. Report all runs and the median; do not silently discard
   thermal outliers.
4. Record wall time, whisper load/mel/encode/decode/total timings, peak RSS,
   transcript, CPU temperature, ARM frequency, and throttling status before and
   after each run.
5. Reject a variant if any transcript misses `two` or `eggs`, it breaks offline
   isolation, or processing exceeds the 30-second hard timeout.

Run one variable at a time:

| Phase | Variant |
| --- | --- |
| Baseline | Current CLI, logs enabled only for benchmark |
| Threads | `-t 1`, `-t 2`, `-t 3`, `-t 4` |
| Context | Best thread count with `-ac 768`, then `-ac 512` |
| BLAS | `GGML_BLAS=ON/OFF`; BLAS threads `1/2/4` |
| Decode | `-nf`; then `-bs 1 -bo 1`, separately |
| Model | `tiny.en-q5_1` versus `tiny.en` |
| Silence | VAD only if material removable silence exists |
| Warm | CLI baseline versus persistent server/C API context |

The decision metric is end-to-end processing time, not an isolated encoder
benchmark. A variant is promotable only when repeated runs satisfy transcript,
offline, evidence, memory, and timeout contracts. Results below 22.43 seconds
increase hard-timeout margin; only transcription at or below about 9.16 seconds
meets the expected-latency goal with other stages unchanged.

## Facts versus hypotheses

| Statement | Status |
| --- | --- |
| CLI defaults to at most four compute threads | Pinned source fact |
| `-t 4` changes the current four-core default | False; it only makes it explicit |
| Lower `audio_ctx` builds a smaller graph and can reduce quality | Pinned source fact |
| `-ac 512` meets 9.16 seconds here | Unmeasured hypothesis |
| OpenBLAS supports CPU encoder acceleration | Upstream claim |
| OpenBLAS beats native ggml on Cortex-A53 | Unmeasured hypothesis |
| Official download tooling offers `tiny.en-q5_1` | Pinned source fact |
| Quantized `tiny.en` is faster or equally accurate here | Unmeasured hypothesis |
| One C API context can process repeated jobs | Pinned source fact |
| A persistent worker saves enough to justify complexity | Unmeasured hypothesis |
| VAD removes detected non-speech before Whisper | Pinned source fact |
| VAD materially helps this seven-second sample | Unmeasured hypothesis |

The immediate recommendation is to follow the
[on-device benchmark procedure](whisper-transcription-benchmark.md) to collect
stage timings and execute the thread/context/BLAS matrix on the physical Pi.
Do not change production until measurements identify a configuration or
warm-worker design that improves the probe without weakening acceptance.