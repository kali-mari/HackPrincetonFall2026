# Findings — actual UNO Q measurements

Recommendation: **not yet established** for continuous listening or AAC application
headroom. The baseline is promising for segmented English speech, but digital silence
produced nonblank text. No production Conversation Mode is implemented.

Operator session date: 2026-11-14. The board's calendar clock reported 2025-12-10 and
was not changed. JSON wall-clock dates are therefore unreliable; all elapsed times
use monotonic clocks. No laptop inference timings are included.

## Verified target and setup

Arduino UNO Q identified through App Lab and USB; device-tree model `Arduino SA,Imola`.
Four aarch64 CPUs, Qualcomm implementer 0x51 / part 0x801; expected UNO Q Cortex-A53-class
hardware. Debian GNU/Linux 13.2 (trixie), kernel 6.16.7-g0dd6551ae96b. Kernel-visible RAM:
3,848,146,944 bytes (3.58 GiB; 4 GB board). Baseline pre-run MemAvailable:
3,245,338,624 bytes (3.02 GiB). Orchestration/download host was an M3 Pro MacBook Pro;
compilation and every reported decode ran on the UNO Q via the existing ADB USB shell.
Network SSH timed out; board downloads failed TLS hostname/hash checks. Normal TLS and
package checks remained enabled; approved downloads were transferred over USB.

whisper.cpp commit: `a8d002cfd879315632a579e73f0148d06959de36` (v1.7.6).
Model: tiny.en; SHA-256:
`921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f`.
CPU-only static Release build, GCC 14.2.0, CMake 3.31.6. Three inference threads;
greedy English, best_of=1, temperature=0, no fallback, no carried context, no VAD.
GPU disabled both at build and runtime; acceleration libraries disabled as documented
in README. Full cache/options, model revision/checksum and binary/source checksums are
in every metrics JSON. System dependency installation was explicitly authorized;
Make was needed for the CMake generator. No firmware/API/data-document changes.

## File results

Public pinned upstream JFK sample, 11 s; downloaded explicitly with permission.
Its synthetic derivatives are repeated speech, speech/silence/speech, digital silence
and seeded Gaussian white noise at 10 dB SNR (zero clipped samples). These are not
independent speakers, natural continuous conversation or representative room noise.
Each repeat has one process-cold decode and one warm decode; counts below are warm
observations. Fresh process does not imply cold filesystem cache.

| Fixture | Audio s | Warm n | Median decode s | Observed p95 s | Median RTF |
|---|---:|---:|---:|---:|---:|
| jfk01 | 11 | 5 | 7.756 | 7.799 | 0.705 |
| jfk_repeat | 55 | 1 | 18.135 | 18.135 | 0.330 |
| jfk_pauses | 33 | 1 | 15.568 | 15.568 | 0.472 |
| jfk_silence | 11 | 1 | 7.386 | 7.386 | 0.671 |
| jfk_noisy | 11 | 1 | 7.829 | 7.829 | 0.712 |

For the original 11 s sample, median model load was 0.251 s;
median process-spawn-to-first-final was 8.115 s.
Peak worker RSS was 216.9 MiB;
median inference CPU use was 292.9% (about 2.93 cores).
Largest observed file-worker RSS across all fixtures was 249.6 MiB (55 s repeated clip).
Peak RSS excludes Python, FFmpeg, page cache and application memory. System memory
snapshots were taken before/after, not continuously during decoding. Sampled thermal
values reached 48.5 C after the final run; this is not a sustained thermal test.

Digital silence emitted two decoded words in **both** the cold and warm observations
(2/2 nonblank output flags, one repeat). Content was not logged or retained. Nonblank
output is a conservative hallucination flag; it demonstrates why ungated decoding
cannot be treated as reliable continuous listening. Same word counts on noisy/clean
audio do not demonstrate equal accuracy. No human reference was supplied: **WER NOT
MEASURED** for all fixtures. No natural conversational accuracy claim is supported.
For n=5, nearest-rank p95 is the observed maximum; n=1 has no useful tail evidence.

## Persistent-model bounded replay

Six copies of the same 11 s public sample; 66 s of clock-paced input, one resident model
and one excluded warm-up decode per session. Pending FIFO budget 22 audio seconds,
plus at most one active 11 s segment. Two valid sessions ran strictly sequentially.

| Load | Session n | Segments decoded | Drops / dropped s | Max pending s | Median decode s | Total elapsed/drain s |
|---|---:|---:|---:|---:|---:|---:|
| Idle baseline | 1 | 6 | 0 / 0 | 11 | 7.754 | 73.763 |
| Synthetic: one busy CPU worker | 1 | 6 | 0 / 0 | 11 | 7.670 | 73.673 |

Pending audio did not grow beyond one segment in these short valid sessions, and
neither dropped audio. The last final arrived about 7.7 s after the 66 s input ended.
Slightly lower synthetic-load time is one-session variation, not evidence of a speedup.
No speech endpoints were annotated: **speech-end-to-final latency NOT MEASURED**.
This tests scheduled segment availability, not live capture, endpoint detection,
partial text, overlapping context or microphone processing. One 66 s repeated-sample
session per condition cannot establish sustained conversation throughput.

An earlier pair of replay attempts overlapped unintentionally. They were excluded;
any completed output was archived under an explicit INVALID-overlap name on the board.
Only the later clean sequential sessions appear in this report and collected results.

## Evidence still needed

Real AAC application load and physical R4 switch/UI latency: **NOT MEASURED**. Synthetic
CPU load is not the AAC UI/backend/SQLite/input bridge. Base.en, quantization and
2/4-thread comparisons: **NOT RUN**. Natural multi-minute conversations, overlapping
speakers, room/microphone noise, accents and child-speech WER: **NOT MEASURED**.

All 10 metric/queue/privacy/protocol tests passed on the actual board, and the native
worker built and linked successfully. Audio and text never went to a hosted speech
service; no microphone was recorded. Private references/transcripts are absent from
exports. Generated fixtures/models/dependencies/results remain ignored by Git.

Valid JSON/CSV exports are under `local/target-results/` on the Mac and `local/results/`
on the board, in the four `uno-q-jfk-*-20261114` directories documented in README.
Fixture generation and exact rerun commands are in README; blank reporting templates
remain intentionally unpopulated. No commit or push was performed.

The measured RTF below 1 and short zero-drop replay satisfy necessary throughput checks
for this narrow policy. They do **not** establish acceptable latency, silence behavior,
accuracy or resources left for the actual AAC application. Recommend **not yet
established**, with segmented-speech experiments as the next step; do not enable
production continuous listening from these results.
