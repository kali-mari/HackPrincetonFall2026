# Experiment 2: clock, WebRTC VAD and optional Vulkan

This is benchmark-only tooling. The original `FINDINGS.md`, CPU worker/build and
original generated results are retained. New outputs live in ignored
`local/experiment2/`; reference text, audio, wheels, model files and build products
must never be force-added to Git. No microphone capture or hosted speech processing
exists here. No application/API/database or firmware changes are part of this work.

## Clock correction before any measured session

On the online Mac, using the already installed Arduino App Lab ADB binary:

```sh
python3 clock_usb.py --adb "$HOME/Library/Application Support/arduino_applab_workspace/arduino15/data/packages/arduino/tools/adb/32.0.0/adb" --serial 2579142805 --apply --output local/experiment2/clock-new.json
```

This checks fresh HTTPS Date headers from Google and Cloudflare with normal TLS
verification. It refuses a host differing by more than 2 s or a slow reference check.
HTTP Date has one-second granularity; it is not a precision time protocol. The host
is used only after verification, not because the prompt/calendar says a date.
The script reads the board's UTC, timezone, NTP and RTC status, enables the existing
time-sync service, then sets current UTC over USB with a password prompt. Credentials
are not saved. It does not install packages, write the RTC, reboot, or alter app data.
Use a fresh output name for every attempt; earlier correction evidence is preserved.

The run used a manual correction because the installed systemd-timesyncd service was
already enabled but its NTP requests timed out. A PMIC RTC exists, but battery-backed
retention is not established. A corrected save-file timestamp can supply a coarse
clock floor after restart; it does not preserve elapsed powered-off time. Automatic
NTP sync is still not established. No deliberate reboot test is authorized/performed.
After power/network loss: reconnect; inspect UTC/`timedatectl`; let the installed
service synchronize if reachable, otherwise repeat the verified-host correction
**before** timing tests. Never disable TLS/package verification or adjust time inside
a measured session. A large wall-clock step is flagged by the runner; duration and
queue scheduling always use monotonic time.

Copy the latest verified record to the board as
`local/experiment2/clock-current.json`; keep the individual evidence files too. New
metrics record UTC, sync status, last correction evidence, boot ID, and a wall-step
check. See `EXPERIMENT2.md` for actual offsets/status rather than assuming NTP works.

## Explicit approved data/dependency setup

The operator approved public reference fixtures and Vulkan build dependencies.
Any future system-wide install requires permission first. The WebRTC wheel is
extracted only under `local/experiment2/python`; no system pip/venv installation.
On the online download host:

```sh
python3 prepare_experiment2.py --download-approved-public-fixtures
```

This downloads WebRTC VAD wheels **2.0.14.post1**, the CPython 3.13 Linux aarch64
wheel, pinned SHA-256; two selected LibriSpeech utterances with published references;
and one published TED-LIUM long-form validation item with published full text (upstream
preprocessing was not independently verified).
Dataset revisions, row IDs, licenses and content checksums are saved locally. The
LibriSpeech fixture is CC BY 4.0; TED-LIUM's published license is CC BY-NC-ND 3.0.
Audio/reference derivatives stay local for evaluation and are not redistributed.
Source/license links are retained in `fixture-provenance.json`. References never print.
The cached audio asset URLs can return FLAC even when named `.wav`; normalization
uses FFmpeg's detected container, not the extension. The script also downloads a
checksummed tiny.en-q5_1 model from the original model repository snapshot, keeping
the baseline model and lock unchanged.

Transfer `fixtures/`, `fixtures.json`, `fixture-provenance.json`, `models-vad.json`,
the wheel and the quantized model into the same `local/experiment2/` directory on
the UNO Q. Transfer the new scripts and `native2/` only within this benchmark folder.
Then on the board:

```sh
python3 derive_experiment2.py
python3 -m unittest -v test_bench.py test_vad.py
```

Derivation generates a -20 dB quiet version, two reference utterances with a 2 s
inserted pause, exact digital silence, and seeded non-speech Gaussian white noise.
The selected natural recording is 291.1 s; adding 8.9 s digital silence yields an
exact 300 s session while retaining its complete published reference. This is not
repeated JFK audio. Only inserted silence is labelled exact; no phonetic speech
boundary is guessed. Natural room/microphone noise remains a separate unavailable
condition, not simulated by calling white noise realistic.

Approved fixtures persist in ignored local storage. Normalized working WAV and raw
float active-segment files live in per-session temporary directories, are removed
on normal exit/errors, and each active float file is removed after its decode. A
power loss can leave `local/experiment2/session-*` or `derive-*`; inspect/remove those
private leftovers manually. The new runner never exports decoded strings or references.
Full-session hypotheses exist in RAM only long enough for aggregate WER.

## Build GPU support separately, if practical

The original CPU build remains in `local/build/`. The original source commit is
`a8d002cfd879315632a579e73f0148d06959de36`. `native2/` uses the same whisper.cpp revision
and decoding settings; the new worker permits either CPU or Vulkan at runtime.
Use `local/experiment2/build-vulkan/` as its build directory.

Inspect before installing anything:

```sh
vulkaninfo --summary
command -v glslc
```

The approved missing packages were `libvulkan-dev` and `glslc` (plus `libshaderc1`).
Package files were fetched over verified HTTPS on the download host and checked
against SHA-256 values from the board's existing APT metadata; the plan/manifest are
under `local/experiment2/`. The board-side offline install used:

```sh
sudo apt-get install --no-download -y --no-install-recommends -o Dir::Cache::archives=/home/arduino/hardware/benchmarks/transcription/local/experiment2/gpu-debs libvulkan-dev glslc
```

Configure with the original `setup_local.OPTIONS`, replace `-DGGML_VULKAN=OFF` with
`-DGGML_VULKAN=ON`, set `WHISPER_SOURCE` to the original pinned checkout and source
folder to `native2/`. Exact CMake commands/options and cache are in `gpu-build.json`:

```sh
cmake --build local/experiment2/build-vulkan --target transcription-worker2 -j 1
```

Use a single job on the 4 GB device. The first parallel attempt caused an observed
compiler OOM; generated embedded shader source was approximately 124 MiB. This is a
build-resource issue, not a measured inference result. GPU investigation is limited
to about 45 minutes, including a bounded retry; retain CPU fallback if blocked.
No driver/kernel/firmware change or requested reboot is part of this experiment.

The runtime restricts `VK_ICD_FILENAMES` to `freedreno_icd.json` for both matched CPU
and GPU runs, excluding llvmpipe. Device enumeration, a Vulkan library, or compilation
alone is not proof of acceleration. Collect actual backend diagnostics and positive
per-process DRM engine/cycle deltas during successful inference. If those cannot be
established, label hardware execution unproven. Do not recommend GPU from build status.
GPU and matched CPU use the same binary/revision/model/settings to isolate offload;
the original CPU baseline remains a separate reproduced anchor.

## Sequential benchmark commands

All commands below run **on the UNO Q**, after setup/compilation ends. The runner
refuses other known inference workers or active compiler/shader processes. A file
lock prevents overlapping experiment sessions; a suite lock prevents two coordinators.
Completed outputs are preserved and never silently overwritten.

```sh
python3 run_experiment2_suite.py --stage controlled
python3 run_experiment2_suite.py --stage accuracy
# Choose the shortlist only after inspecting controlled timing and reference WER:
python3 run_experiment2_suite.py --stage sustained --shortlist-model tiny.en --shortlist-threads 3 --sustained-runs 1
# Optional second five-minute comparison after a supported quantized shortlist:
python3 run_experiment2_suite.py --stage sustained --shortlist-model tiny.en-q5_1 --shortlist-threads 2 --sustained-runs 1
# Only if the GPU build and hardware execution probe genuinely succeeded:
python3 run_experiment2_suite.py --stage gpu
```

Controlled trials reproduce JFK and compare 1/2/3 CPU threads, then Q5_1 at 2/3
threads with the model changed separately. Accuracy trials compare full-file and
VAD output on public reference clips, quiet speech, inserted pauses, silence and
non-speech white noise. The resident model is retained across repeats of each
configuration; initialization and excluded first decode are recorded separately.
No warm-up decode occurs if the selected VAD policy emits no segment.

Each sustained stage compares fixed 10 s segmentation with VAD in separate 300 s
clock-paced sessions. The recording is prerecorded, not live microphone capture.
Reference WER always uses **all** reference words for the exact played audio; missed
or dropped difficult speech is not removed from the reference. WER normalization is
unchanged: Unicode NFKC, casefold, nonalphanumeric characters replaced by spaces,
whitespace tokenization, unit-cost word Levenshtein distance. No number expansion,
spelling repair, filler removal or source-label cleanup. Empty-reference WER is null;
use insertion counts and nonblank-output flags for silence/noise. TED reference
annotation markers, if present, are not silently removed. Do not infer accuracy from
word counts. Individual file references are not published in reports.

WebRTC VAD is a statistical speech detector, not just a volume threshold. Aggressiveness
is mode 2 by default (`--vad-mode` supports 0–3); a 20 ms frame becomes a speech trigger
with 3 of the last 5 frames positive. Pre-roll 200 ms, minimum positive speech 100 ms,
silence hangover 500 ms, maximum segment 10 s and pending queue budget 20 audio seconds.
The active decoder adds one bounded segment. Pre-roll is clamped to the prior emitted
endpoint; overlap is **0 ms**. Continuous speech is cut at the maximum and retained
once. No heuristic text deduplication hides boundary errors; reference WER counts them.

A producer thread reads 20 ms PCM frames on a monotonic schedule and runs VAD locally.
A consumer decodes one resident-model segment at a time. Overflow drops oldest pending
segments. Pending or final results older than `--stale-s` (default 30 s) are discarded
and counted; their reference words still count for WER. Ctrl-C stops the producer,
discards pending audio/late results and closes the worker. No capture device exists
to leak or leave running. Queue occupancy and resource indicators are sampled every
250 ms; exact queue maximum/drop accounting is also maintained under the queue lock.

## Reading results correctly

Each configuration writes JSON and aggregate CSV under `local/experiment2/results/`.
Per-repeat and per-segment metrics include durations, model load/first decode, CPU,
worker/parent RSS, source-audio RTF, queue wait/backlog/drop/stale counts and drain time.
Source RTF uses unique played samples, not duplicated pre-roll or summed windows.
The last frame may contain under 20 ms of zero padding; that is documented and bounded.
VAD CPU time is measured independently; parent CPU includes monitoring/PCM conversion.
Worker RSS is a lifetime high-water mark; GPU driver allocations are not fully captured
by RSS, and before/after system memory is not a peak. Thermal/frequency readings are
indicators, not proof of throttling. Per-process DRM deltas distinguish the actual
inference client from display rendering if supported by the kernel.

For independent speech annotations, supply sorted disjoint `speech_boundaries` in
seconds and an `annotation_kind` describing their granularity. Frame errors and
emitted/delivered interval coverage are measured separately. For the supplied public
fixtures those boundaries are absent: semantic missed/trimmed speech and true
speech-end-to-final latency are NOT MEASURED. The runner separately reports the
VAD-estimated last voiced frame and segment-availability-to-final latency; neither is
a human ground-truth endpoint. Exact synthetic non-speech and inserted silent spans
permit false-positive measurement only on those known intervals.

Read median/p95 together with n. With n=3, nearest-rank p95 is the observed maximum;
n=1 is exploratory. Six segments in one session are not six independent sessions.
Queue caps with drops are not evidence of sustainable lossless throughput. Require
no growing queue, zero drops, acceptable accuracy/endpoint latency and actual AAC
responsiveness before recommending continuous listening. No actual Django/UI server
was listening when availability was checked; API scaffolds returning 501 would not
represent implemented feature load anyway. Synthetic busy load is not an application
headroom measurement. No API/DB writes are used to manufacture that load.

To collect only numeric exports and setup/clock/GPU evidence onto the online host:

```sh
python3 collect_experiment2.py --adb "$HOME/Library/Application Support/arduino_applab_workspace/arduino15/data/packages/arduino/tools/adb/32.0.0/adb" --serial 2579142805
```

It refuses to overwrite a changed collected result. Audio and reference files are not
pulled by this collector. `summary.json`/`.csv` remain ignored under the new experiment.
