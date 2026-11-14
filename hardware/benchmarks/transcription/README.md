# Local transcription benchmark — Arduino UNO Q, 4 GB

**A tiny.en baseline has now run on the actual UNO Q. Recommendation: not yet established.**
See `FINDINGS.md` for measured results and remaining gaps.
This is an offline experiment, not Conversation Mode or firmware. No microphone is
opened. It has no network transcription path. The Python runner uses only the standard
library and existing FFmpeg. Explicit setup is the only network operation.

## Setup (operator initiated, on the target)

Read the repository's AGENTS.md. Work from this directory:

```sh
cd hardware/benchmarks/transcription
command -v python3 git cmake c++ make ffmpeg
python3 bench.py --inventory
python3 -m unittest -v test_bench.py
```

Required: Linux arm64 on the actual UNO Q, Python 3.9+, Git, CMake 3.16+, C++17
compiler, Make, FFmpeg, enough local disk for sources/build/models/normalized PCM.
No system package installation is performed here. **If prerequisites are missing,
ask the device owner before a system-wide install.** Do not run `sudo` automatically.
Models need roughly tens to hundreds of MB each plus build workspace; check `df -h .`.

Explicit source/model download and CPU build:

```sh
python3 setup_local.py --download-model tiny.en --jobs 2
# Optional, after tiny.en works and RAM/disk permit:
python3 setup_local.py --download-model base.en --jobs 2
# Optional quantized model comparison; same setup and metrics path:
python3 setup_local.py --download-model tiny.en-q5_1 --jobs 2
```

This fetches whisper.cpp **a8d002cfd879315632a579e73f0148d06959de36** (v1.7.6)
and builds the small C API worker. Static Release build; CUDA, Metal, Vulkan,
BLAS, Accelerate, CoreML, OpenVINO, OpenMP and native-host tuning are disabled.
Inference also explicitly disables GPU. Build options, compiler, CMake version,
complete CMake cache, worker/source SHA-256 and model SHA-256 go into ignored
`local/setup.json`, and are copied into each metrics export. The runner verifies
source cleanliness, commit and relevant file checksums before inference.

On first explicit download of each model, setup resolves the Hugging Face model
repository snapshot and verifies the file against its published LFS SHA-256.
That revision and checksum are retained in `local/setup.json`; preserve that file
for exact reruns (including on another target). Without it, a new setup may select
a newer model snapshot. Checksums are **not yet measured** in this checkout because
no models were downloaded. Delete a partial failed download before retrying if desired.
Do not delete the lock to conceal a checksum failure. No model or audio is fetched by
`bench.py`. Setup does not fetch sample speech. Review model/fixture licenses yourself.

Implementation references: [pinned whisper C API](https://github.com/ggml-org/whisper.cpp/blob/a8d002cfd879315632a579e73f0148d06959de36/include/whisper.h),
[pinned build configuration](https://github.com/ggml-org/whisper.cpp/blob/a8d002cfd879315632a579e73f0148d06959de36/CMakeLists.txt),
[upstream model download source](https://github.com/ggml-org/whisper.cpp/blob/a8d002cfd879315632a579e73f0148d06959de36/models/download-ggml-model.sh).

## Private fixtures

Place user-provided audio and optional UTF-8 references in `local/fixtures/`.
Nothing in `local/` is tracked. No public audio is automatically downloaded;
use only user-owned, appropriately licensed public, or synthetic fixtures after
an explicit download/generation action. Never record a microphone automatically.
This benchmark does not generate noisy speech from private audio without an operator
preparing it. Keep any source/license/consent notes with the private fixtures.

Create `local/files.json` using anonymous IDs; paths are relative to the manifest:

```json
[
  {"id":"c01", "category":"short", "audio":"fixtures/short.wav", "reference_file":"fixtures/short.txt"},
  {"id":"c02", "category":"continuous", "audio":"fixtures/long.wav", "reference_file":"fixtures/long.txt"},
  {"id":"c03", "category":"pauses", "audio":"fixtures/pauses.wav", "reference_file":"fixtures/pauses.txt"},
  {"id":"c04", "category":"silence", "silence":true, "audio":"fixtures/silence.wav"},
  {"id":"c05", "category":"noisy", "audio":"fixtures/noisy.wav", "reference_file":"fixtures/noisy.txt"}
]
```

Use approximately 3–10 s short clips, 2–10 min continuous speech, speech with
several 5–30 s pauses, standalone silence of several durations, and noisy speech
representative of the room, microphone, distances and voices. Include overlapping
speakers, different accents and child speech if those matter to the application.
Record SNR/noise source in private fixture notes; no SNR is inferred automatically.
Run silence independently: absence of a hallucination in speech-with-pauses is not
proof of silence safety. Supply an empty reference file for silence if desired;
zero reference words yields null WER and a word-error count.

Each local input is decoded with FFmpeg's file/pipe-only protocol whitelist and
normalized to **16 kHz, mono, float32 little-endian PCM** in a private temporary
directory. The worker consumes PCM floats directly, as required by the C API.
Duration comes from the actual normalized sample count. FFmpeg conversion is outside
inference timing. To create inspectable PCM WAV manually (also stays ignored):

```sh
ffmpeg -nostdin -v error -protocol_whitelist file,pipe -i local/fixtures/input.wav -vn -ac 1 -ar 16000 -c:a pcm_s16le local/fixtures/normalized.wav
```

Only paths to existing local files are accepted. Media is capped at one hour per
fixture after normalization; use sensible fixture sizes and free disk. Temp files
are deleted on normal exit and exceptions. A crash/power loss can leave them in
`local/pcm-*`; remove those private directories manually before sharing the device.
Do not put private text in IDs. The per-directory `.gitignore` is an allowlist of
implementation files and blank aggregate templates; generated audio, manifests,
references, transcripts, models, outputs and caches are ignored by default. Never
force-add them. A caller-selected output directory outside this tree has no such guard.

## Explicit public JFK smoke test

The operator authorized downloading the upstream public JFK sample for the actual
UNO Q run. This optional command reproduces that fixture preparation; it never
opens a microphone:

```sh
python3 prepare_jfk.py --download --variants
python3 bench.py --manifest local/jfk.json --model tiny.en --threads 3 --runs 5 --load-kind idle --confirm-uno-q --output local/results/uno-q-jfk-t3-20261114
python3 bench.py --manifest local/jfk-replay.json --mode replay --max-segment-seconds 11 --buffer-seconds 22 --model tiny.en --threads 3 --runs 1 --load-kind idle --confirm-uno-q --output local/results/uno-q-jfk-replay-idle-20261114
python3 bench.py --manifest local/jfk-replay.json --mode replay --max-segment-seconds 11 --buffer-seconds 22 --model tiny.en --threads 3 --runs 1 --load-kind synthetic --synthetic-load-workers 1 --confirm-uno-q --output local/results/uno-q-jfk-replay-synthetic-20261114
python3 bench.py --manifest local/jfk-variants.json --model tiny.en --threads 3 --runs 1 --load-kind idle --confirm-uno-q --output local/results/uno-q-jfk-variants-20261114
```

Run those commands **sequentially**, waiting for each to finish. The original WAV
is 11 s. Replay uses six identical copies (66 s), not six independent speech samples.
Variants are 55 s of repeated speech, 33 s of speech/silence/speech, 11 s silence,
and 11 s with seeded Gaussian white noise at 10 dB SNR before clipping. Generation
parameters, source hash and clipping count are saved in ignored fixture provenance.
These are smoke tests, not representative conversations or a room-noise dataset.
No human reference or speech-end annotation is supplied; WER and speech-end latency
remain unmeasured. A one-repeat variant or replay is not a robust tail estimate.

The first run used USB ADB because Wi-Fi SSH timed out and board-side downloads
failed certificate/hash verification. All downloads kept verification enabled on
the Mac, then transferred to the target. Debian package SHA-256 values were checked
against the board's existing APT metadata before installation; the local manifest
is `local/offline-packages.json`. Packages included Make as the CMake generator.
For an already verified local package cache, the actual offline install was:

```sh
sudo apt-get install --no-download -y --no-install-recommends -o Dir::Cache::archives=/home/arduino/hardware/benchmarks/transcription/local/debs cmake g++ ffmpeg make
```

For offline source/model setup, transfer the pinned `local/whisper.cpp` checkout
(including `.git`), checksummed model and `local/setup.json` from the download host,
then run the same setup command on the board. ADB can omit empty directories; restore
`.git/refs/heads`, `.git/refs/tags` and `.git/objects/info` after transfer if needed.
Verify Git HEAD and cleanliness before building. No source or model download is
needed when that pinned checkout, model and model-lock entry already exist. Build
and benchmark execution for the reported run happened on the UNO Q, not the Mac.
The board calendar clock was incorrect; reported durations use the monotonic clock.

## File benchmark: exact commands

After verifying physical board identity and Linux/arm64 inventory:

```sh
python3 bench.py --manifest local/files.json --model tiny.en --threads 3 --runs 5 --load-kind idle --confirm-uno-q --output local/results/tiny-t3-idle
python3 bench.py --manifest local/files.json --model tiny.en --threads 2 --runs 5 --load-kind idle --confirm-uno-q --output local/results/tiny-t2-idle
python3 bench.py --manifest local/files.json --model tiny.en --threads 4 --runs 5 --load-kind idle --confirm-uno-q --output local/results/tiny-t4-idle
# Only after the optional model setup:
python3 bench.py --manifest local/files.json --model base.en --threads 3 --runs 5 --load-kind idle --confirm-uno-q --output local/results/base-t3-idle
python3 bench.py --manifest local/files.json --model tiny.en-q5_1 --threads 3 --runs 5 --load-kind idle --confirm-uno-q --output local/results/tiny-q5-t3-idle
```

Omit `--confirm-uno-q` on other machines; all exports then mark target results
NOT RUN. That flag is an operator attestation, not automatic board detection;
Linux/arm64 is checked, but a different ARM board can pass it. Verify model,
Cortex-A53 CPU, Debian version and approximately 4 GB RAM from inventory before
using it. Record available RAM, swap, power/cooling, CPU governor and sustained
thermal behavior. Inventory captures Linux MemAvailable, swap, CPU info, board model,
and one thermal/frequency node before/after; nodes may be absent or unrepresentative.
No privilege elevation or governor change is performed.

Runtime: greedy English decoding, best_of=1, temperature=0, no temperature fallback,
no carried text context, no VAD, no transcript prompt, upstream defaults otherwise.
No VAD means silence results deliberately expose the baseline's behavior. Results
apply to English models and these settings only. Quantization must be compared
using the same fixtures, threads, loads and repeat counts, including WER.

Each repeat starts a fresh process/model, decodes once, then decodes the same fixture
again with the model resident. Warm sample count equals `--runs`, not two times runs.
New-process measurements are **process-cold, filesystem-cache uncontrolled**; no
root cache drop is attempted. Randomize configuration order and repeat over a long
session to check heat/throttling and cache effects. Use `--runs 20` or more for a more
informative observed p95; p95 with n=5 is simply the maximum, not a tail guarantee.

## Persistent model and bounded replay

Prepare `local/replay.json` with an ordered sequence of presegmented nearby
conversation clips, each at most 10 s, including pauses/noise/silence. Format is the
same as above; optionally annotate `speech_end_s` with the last speech endpoint in
each segment, measured relative to that segment's start. Do not invent endpoints
from total duration. Silence segments omit `speech_end_s`. Supply segment-aligned
references for WER. Keep the same sequence for all comparisons, preferably 10–30 min.

```sh
python3 bench.py --manifest local/replay.json --mode replay --max-segment-seconds 10 --buffer-seconds 20 --model tiny.en --threads 3 --runs 5 --load-kind idle --confirm-uno-q --output local/results/replay-idle
```

One model process remains resident for each repeat; one warm-up decode is excluded.
Each segment becomes available only when its full audio duration has elapsed on a
monotonic clock. A pending FIFO holds at most 20 audio seconds; overflow drops oldest
pending segments. The active decode adds at most one 10 s segment. All normalized
fixtures are prepared on disk first, but only one segment is decoded at a time;
this is a bound on queued audio/work, not total fixture disk storage.

The producer is a **clock-scheduled replay**, not a live microphone thread. Arrivals
and FIFO admission are accounted at decoder service boundaries; the trace samples
pending audio there, after drops. It does not measure sub-decode scheduling jitter,
pre-drop instantaneous backlog, microphone capture, VAD endpointing, resampling under
load, or input-event latency. No rolling context, overlap correction or partial-text
updates are implemented. Final latency includes segment assembly plus queue wait and
decode when a real speech endpoint is annotated. Drop counts/durations, post-drop
queue trace, wait times, elapsed drain time and final-latency median/p95/n are exported.
Dropped clips are excluded from WER/latency, so always read those metrics with drops.
Replay repeats are exported separately; do not pool correlated segments as independent
whole-session runs. Retain the per-repeat sample counts.

Fast file RTF alone does not establish live performance. Even this replay only tests
the chosen segmenting/buffer policy on prerecorded data. Bounded queue occupancy with
drops is **not** sustained lossless throughput. Require zero drops, no upward queue
trend over a sustained run, acceptable endpoint-to-final latency and acceptable WER
under the real application workload before considering continuous listening suitable.

## Idle vs application load

First measure idle. For an explicitly **synthetic** CPU load, repeat files and replay:

```sh
python3 bench.py --manifest local/files.json --model tiny.en --threads 3 --runs 5 --load-kind synthetic --synthetic-load-workers 1 --confirm-uno-q --output local/results/files-synthetic
python3 bench.py --manifest local/replay.json --mode replay --model tiny.en --threads 3 --runs 5 --load-kind synthetic --synthetic-load-workers 1 --confirm-uno-q --output local/results/replay-synthetic
```

This adds one busy Python CPU worker, not a realistic AAC application. It is terminated
on normal exit/errors; no arbitrary workload command is executed by the benchmark.
Then run the actual AAC UI, backend and input bridge locally in their existing
supported configuration and repeat with `--load-kind application`:

```sh
python3 bench.py --manifest local/replay.json --mode replay --model tiny.en --threads 3 --runs 5 --load-kind application --confirm-uno-q --output local/results/replay-application
```

The label records the operator's assertion; it does not start or verify an application.
Record actual processes/settings/actions in private run notes. Existing application
features may contact cloud APIs: disable those paths or use local stubs and verify
network isolation before exercising them. Never feed benchmark transcripts to the
application. Do not change API contracts/firmware to run this benchmark.

Exercise the physical NEXT/SELECT switches and UI scanning while decoding. If existing
instrumentation provides synchronized input-send and UI-receipt/render timestamps,
report p50/p95/max latency, counts, misses and clock method. Otherwise record subjective
responsiveness separately; the runner explicitly says input responsiveness NOT MEASURED.
A synthetic load and a local stubbed application are not a measured production load.
Three decode threads are a starting experiment, not a guarantee that a core remains
available; measure 2/3/4 threads and application responsiveness.

## Metrics and privacy

`metrics.json` contains numeric per-repeat observations, provenance and aggregate
median/p95/max/n; `metrics.csv` is a numeric per-observation export for analysis.
Outputs default under ignored `local/results`; use unique output directories to avoid
overwriting previous runs. No decoded transcript or reference text is exported or
printed. Text exists in the worker and private parent pipe/RAM for WER then is discarded;
upstream logs and FFmpeg diagnostics are suppressed. Private filenames are not fixture
IDs in exports. Audio hashes allow matching fixture versions, so treat exports as
potentially sensitive metadata. Core dumps, swap and OS-level tracing are outside this
script's control. This is not a forensic data-erasure tool.

- Audio duration: normalized samples / 16000. RTF = `inference_s / duration_s`.
  This excludes load, file read, segment assembly and queueing; read `request_wall_s`
  and replay endpoint latency as well. CPU percentage = inference CPU seconds / wall
  seconds × 100; multiple cores can exceed 100%.
- `load_s`: C API model initialization wall time. `startup_to_ready_s`: process spawn
  through ready reply. `spawn_to_final_s`: spawn through first final reply. These are
  separate observations; do not subtract unrelated medians. Ready time includes
  startup overhead; load includes model I/O, not guaranteed physical-disk cold I/O.
- `inference_s`: wall time inside whisper_full. `request_wall_s` also includes worker
  PCM file read, result extraction and pipe transfer. It excludes earlier normalization.
- CPU seconds and peak RSS: getrusage(RUSAGE_SELF) in worker, all its threads. CPU is
  delta for each inference (model-load CPU separately); peak RSS is process lifetime
  high-water RSS in bytes, **not reset between warm requests**. It includes model/load
  and PCM buffers, not just incremental decode memory. macOS RSS bytes vs Linux KiB
  are converted explicitly. Python, FFmpeg, page cache, synthetic worker and AAC process
  memory are excluded. Before/after system memory is not a peak system-memory measure.
- WER: unit-cost word Levenshtein errors / reference words; can exceed 1. Unicode NFKC,
  casefold, replace every nonalphanumeric character with a space, split whitespace.
  Apostrophes/hyphens split words; numerals are not expanded. Empty references yield
  null WER plus insertion/error counts. No reference means no WER. No spelling cleanup,
  label-vocabulary mapping or semantic accuracy adjustment. Each repeat's WER is
  retained; corpus WER is sum(errors)/sum(reference_words), not mean clip WER.
- Silence: `hallucinated_on_silence` flags **any nonblank output**, including annotations
  or punctuation; this is a conservative output flag, not a human-adjudicated semantic
  hallucination label. Decoded word counts are exported, actual words are not. Inspect
  private fixtures manually under an explicit separate workflow if content review is
  needed. Accuracy for overlap, distance, noise, accents and child speech remains
  unestablished until representative references are evaluated.

`results-template.json` and `.csv` are blank aggregate reporting templates. `FINDINGS.md`
distinguishes work performed here from pending target runs. Never publish laptop
measurements as UNO Q performance. No automatic pass threshold beyond arithmetic is
encoded: final suitability needs explicit application latency/accuracy/resource budgets.
