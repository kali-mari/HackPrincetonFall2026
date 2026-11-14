# Experiment 2 — clock, speech gating, CPU controls and GPU feasibility

Recommendation: **not yet established** for continuous listening or dependable AAC
application headroom. The best further-test candidate in this matrix is **tiny.en-q5_1,
three CPU threads, bounded WebRTC VAD**. It saves memory and avoids silence decoding,
but short-reply accuracy and latency remain limitations. Two threads failed sustained
operation. No production feature was enabled.

All reported transcription ran on the actual UNO Q. The original `FINDINGS.md`, worker,
source/build configuration, baseline setup record and all eight old JSON/CSV exports
were verified unchanged. New results are separate under `local/experiment2/`.

## Clock diagnosis and correction

Timezone was and remains Etc/UTC. Installed systemd-timesyncd was enabled/active but
not synchronized. Logs repeatedly showed NTP reply timeouts. A PMIC RTC is exposed
(`rtc-pm8xxx`); its value was near 1970 plus uptime. Battery-backed UTC retention is
**NOT ESTABLISHED**, not assumed absent. The exact network reason for the NTP failures
was not established; firewall/routing/captive-portal explanations remain hypotheses.
TLS/package checks were never disabled.

The Mac was verified against fresh, normal-TLS HTTPS Date responses from
`https://www.google.com/generate_204` and `https://www.cloudflare.com/cdn-cgi/trace`,
with nonces to avoid cached responses. Both agreed with the host within the script's
2 s acceptance bound and sub-second request RTT. HTTP Date has one-second granularity;
this is not precision NTP. Current verified host epoch was then set through USB ADB,
not a date copied from the prompt. No host clock change was made.

Commands: `systemctl enable --now systemd-timesyncd` and
`date -u --set=@<fresh-verified-host-epoch>`, using a hidden sudo password prompt.
The initial command included service startup delay; a separate refinement moved the
UTC capture after that service operation. Every attempt's evidence was retained.

| Evidence | Before UTC | Board minus host before s | After UTC | Board minus host after s | NTP synced |
|---|---|---:|---|---:|---|
| clock.json | 2025-12-10T15:55:17.088377+00:00 | -29298390.870 | 2026-11-14T18:21:56.355321+00:00 | -3.240 | no |
| clock-refined.json | 2026-11-14T18:22:47.040963+00:00 | -3.258 | 2026-11-14T18:23:00.394516+00:00 | -0.407 | no |
| clock-after-reconnect.json | 2026-11-14T18:42:57.715806+00:00 | -89.625 | 2026-11-14T18:44:39.204303+00:00 | -0.393 | no |

A USB disconnection coincided with an observed board restart (43 s uptime after
reconnection). Prior-boot kernel logs show compiler OOM; they do not establish the
restart's cause. The agent issued **no reboot command**. After reconnect, the clock
was about 89.6 s behind the verified host, consistent with recovery from a saved clock
floor rather than elapsed powered-off time. It was corrected again **before** tests.
A deliberate restart/power-loss persistence test remains **NOT TESTED**.

The final read-only check found board minus verified host =
-0.424 s. NTP still reported unsynchronized.
All measured sessions used monotonic scheduling/durations and passed their wall-step
check; no manual clock changes occurred during them. Old unreliable calendar dates
were not rewritten, nor were application event timestamps/databases changed.

Expected recovery: the enabled service saves a recent coarse clock floor and should
retry NTP when networking permits. Running without network still allows oscillator
drift; power loss may lose elapsed time because RTC retention is unproven. On restart,
verify UTC/`timedatectl`; obtain network sync or repeat `clock_usb.py`'s verified-host
manual correction before a benchmark. Manual correction is **not** proof of persistent
automatic synchronization. See `clock*.json` for reference sources, RTT/uncertainty,
commands and sync properties.

## Exact target, builds and backend evidence

UNO Q identified via Arduino App Lab, USB and device tree `Arduino SA,Imola`;
four aarch64 CPUs, Qualcomm implementer 0x51 / part 0x801, Cortex-A53-class target.
Debian GNU/Linux 13.2; kernel 6.16.7-g0dd6551ae96b. Kernel-visible RAM is
3,848,146,944 bytes (3.58 GiB on the 4 GB board). All metrics include before/after
memory, sampled MemAvailable/SwapFree, thermal/frequency nodes and boot identity.
The Mac performed downloads/orchestration only, never target inference timing.

whisper.cpp **a8d002cfd879315632a579e73f0148d06959de36**, v1.7.6, unchanged.
Original static Release CPU build, GCC 14.2.0; acceleration libraries/GPU disabled.
Decoding is greedy English, best_of=1, temperature=0, temperature increment=0,
no carried context, no VAD inside Whisper, and upstream default audio context.
CPU thread count is explicitly 1/2/3. A resident model serves each session's repeats;
model initialization and an excluded first decode are separate from measured repeats.
No warm-up decode runs when VAD emits no segment. Filesystem cache is uncontrolled.

- tiny.en SHA-256: `921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f`.
- tiny.en-q5_1 SHA-256: `c77c5766f1cef09b6b7d47f21b546cbddd4157886b3b5d6d4f709e91e66c7c2b`.
- WebRTC VAD wheel 2.0.14.post1, CPython 3.13 Linux aarch64, MIT;
  SHA-256 `9658d73f8d9aca3070244a359c36ac1c92b87551b4bc1525fbca8dd97fcef459`. Extracted only under local storage.

Every result records model revision/checksum, original build cache/options,
runner/segmenter/binary checksums, decoding policy, UTC/sync evidence and runtime.

Vulkan enumerated **Turnip Adreno 702**, integrated GPU, Mesa 25.2.6-1~bpo13+1,
physical API 1.0.318; loader API 1.4.309. It also enumerated **llvmpipe**, a CPU/software
implementation, API 1.4.318. Adreno reported 16-bit storage, float16/int8 and timeline
semaphores; this did not prove the pinned backend could execute inference on it.
No CUDA, Metal or NPU acceleration was assumed.

The explicitly approved packages libvulkan-dev, glslc and libshaderc1 were installed
from SHA-256-verified Debian packages; no driver/kernel/firmware update. A separate
`native2/` and `local/experiment2/build-vulkan/` preserved the CPU build. The first
parallel build generated a ~124 MiB shader C++ translation unit and hit compiler OOM;
kernel log reports the killed cc1plus at ~2.2 GiB anonymous RSS. A one-job retry did
not finish within the bounded, roughly 45-minute GPU investigation and was stopped.
Logs/cache/partial artifacts are retained. Original CPU binary SHA-256 stayed unchanged.

**GPU inference: NOT RUN. Hardware offload: UNPROVEN. CPU-vs-GPU trade-off: NOT MEASURED.**
No software Vulkan result is presented as acceleration. The prepared runtime would
restrict the ICD to freedreno, exclude llvmpipe, record backend diagnostics and sample
per-process DRM engine/cycle counters. No such successful runtime evidence exists yet.
A successful build or enumerated GPU alone would not change this conclusion.

## Controlled file comparisons

Same approved 11 s JFK fixture and unchanged decoding, one excluded warm-up followed
by three measured calls in one resident model session. RTF = decode seconds / source
seconds. Active CPU can exceed 100% because it sums threads. Load is a **single n=1**
initialization per configuration; warm timing n=3. Nearest-rank p95 with n=3 is maximum.

| Model | Threads | Warm n | Decode median / p95 s | Median RTF | Active CPU | Peak worker MiB | Model load s (n=1) |
|---|---:|---:|---:|---:|---:|---:|---:|
| tiny.en | 1 | 3 | 22.372 / 22.372 | 2.034 | 99.0% | 217.2 | 0.265 |
| tiny.en | 2 | 3 | 11.469 / 11.478 | 1.043 | 196.7% | 215.2 | 0.252 |
| tiny.en | 3 | 3 | 7.813 / 7.815 | 0.710 | 291.3% | 216.8 | 0.254 |
| tiny.en-q5_1 | 2 | 3 | 10.789 / 10.796 | 0.981 | 196.6% | 173.3 | 0.238 |
| tiny.en-q5_1 | 3 | 3 | 7.335 / 7.345 | 0.667 | 292.4% | 171.5 | 0.215 |

Three-thread tiny.en reproduces the earlier 7.76 s / RTF 0.705 baseline closely.
Q5 at three threads used about 21% less peak worker RSS and ~6% less decode time in
this control, but **did not reduce active core count**. Two-thread Q5's RTF near 0.98
on JFK was not enough evidence for sustained operation; the natural replay below
rejected it. One-/two-thread unquantized controls exceeded RTF 1. Quantized reference
controls at both two/three threads had 5.9% WER on the same 17-word read fixture.

## VAD policy, privacy and accuracy

WebRTC is a statistical speech detector, not only a volume threshold. Policy:
20 ms mono PCM16/16 kHz frames; mode 2; start at 3 positive frames in a 5-frame window;
200 ms pre-roll; 100 ms minimum positive speech; 500 ms silence hangover; 10 s maximum
segment; 20 s pending audio budget plus one active segment. Continuous speech is cut
at the maximum. Pre-roll is clamped to the previous consumed endpoint: **0 overlap**,
no repeated samples or heuristic transcript deduplication. WER counts boundary errors.

The producer reads prerecorded frames on monotonic deadlines and runs VAD locally;
consumer uses one resident decoder. Overflow drops oldest pending audio. A 30 s age
budget discards stale pending/final results, explicitly counted. All reference words
remain in WER, including dropped/missed speech. Stop discards pending/late output and
closes source/worker; there is no microphone device in this experiment.

Public fixtures were explicitly approved. LibriSpeech read/short samples have published
references; TED-LIUM long-form validation row 0 provides a 291.1 s natural speech item
and full reference. Source bytes are unchanged by this experiment; upstream long-form
preprocessing was not independently verified. Dataset revisions, row identifiers,
licenses and hashes are in local provenance. TED-LIUM source/reference are not
redistributed. Silence, -20 dB quiet speech, a 2 s inserted pause and seeded 10 dB
white-noise variants are synthetic and labelled. They are not realistic room noise.
The sustained fixture appends 8.9 s of known digital silence to the natural item for
exactly 300 s, without repeating JFK or dropping reference words.

WER: Unicode NFKC, casefold, replace nonalphanumeric characters with spaces, whitespace
words, unit-cost Levenshtein errors / reference words. No number expansion, spelling
repair, filler/annotation cleanup or inference from word counts. Apostrophes split.
Empty-reference WER is null; insertion/nonblank counts are used for non-speech.

All accuracy rows below use unquantized three-thread tiny.en, n=3 repeated calls on
the same source per policy; these are not independent speakers or unique examples.

| Fixture | WER file / VAD | Source RTF file / VAD | Nonblank non-speech file → VAD |
|---|---:|---:|---:|
| read_short | 5.9% / 5.9% | 1.314 / 1.310 | — |
| reply_short | 50.0% / 50.0% | 3.192 / 3.185 | — |
| quiet | 5.9% / 5.9% | 1.314 / 1.310 | — |
| pauses_ref | 10.5% / 10.5% | 0.781 / 1.479 | — |
| noisy_ref | 5.9% / 5.9% | 1.314 / 1.316 | — |
| silence | NOT MEASURED / NOT MEASURED | 0.673 / 0.000 | 3/3 → 0/3 |
| noise_only | NOT MEASURED / NOT MEASURED | 0.668 / 0.000 | 0/3 → 0/3 |

Digital silence produced nonblank text in 3/3 full-file observations; VAD emitted no
segment, made zero decode calls and produced no output in 3/3 observations. Non-speech
white noise also emitted no VAD segment: four false-positive detector frames per
550-frame fixture were rejected by the minimum-speech policy. The full-file noise
condition happened to output no text too; no hallucination-rate improvement is claimed
for it. VAD does not guarantee hallucination-free handling of other noise or speech.

Read, quiet and synthetic noisy speech retained 5.9% WER; the two-word short fixture
had one word error (50%) with/without VAD, also in the Q5 VAD check. The pause fixture
retained 10.5% WER but split into two decodes, raising source RTF from 0.781 to 1.479.
That measured compute demand would exceed one decoder if the same pattern continued
at the same pace. The long monologue is not proof of turn-taking conversation performance.

True missed/trimmed speech and phonetic speech-end latency are **NOT MEASURED**: the
selected reference fixtures lack independent speech-boundary annotations. Known
inserted/non-speech intervals permit limited frame false-positive measurement. No
boundary was invented from clip duration or from VAD itself. Harness support/tests
cover supplied independent annotations and separate VAD coverage from delivery loss.

## Four sequential five-minute paced sessions

All used the same exact 300 s fixture and 889-word reference; **session n=1 each**,
exploratory, no overlapping workers/compiler activity. Each model was warmed before
its monotonic replay epoch. Source RTF uses unique played source samples, including
silence, never duplicated pre-roll windows. Each session's trace captures backlog,
CPU/memory/thermal/frequency indicators; input was prerecorded, not live capture.

| Model / threads / policy | Source RTF | WER | Max pending s | Dropped segments / audio s | Stale finals discarded | Drain s | Segment-ready→final median / p95 s (segment n) | Peak worker MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| tiny.en, t3, vad | 0.878 | 12.1% | 10.00 | 0 / 0.00 | 0 | 4.88 | 8.53 / 15.61 (31) | 232.4 |
| tiny.en-q5_1, t3, fixed | 0.881 | 9.2% | 10.00 | 0 / 0.00 | 0 | 7.13 | 10.01 / 19.14 (30) | 188.8 |
| tiny.en-q5_1, t3, vad | 0.856 | 10.1% | 10.00 | 0 / 0.00 | 0 | 3.91 | 8.30 / 14.86 (31) | 188.4 |
| tiny.en-q5_1, t2, vad | 1.030 | 37.8% | 20.00 | 6 / 54.82 | 5 | 22.09 | 25.07 / 33.76 (25) | 189.6 |

Three-thread settings stayed bounded without drops or stale results. With matched
Q5/three-thread conditions, VAD changed source RTF 0.881→0.856 and drain 7.13→3.91 s,
but WER worsened 9.2%→10.1% (82→90 errors). Ready-to-final p95 improved 19.14→14.86 s;
this is a one-session observation, not a proven population latency/accuracy trade-off.
Q5 VAD versus unquantized VAD changed WER 12.1%→10.1% on this one recording; that is
not a general claim that quantization improves recognition.

Two-thread Q5 hit the queue budget, dropped **54.82 s across six segments**, and
additionally discarded **five already-decoded stale finals**. Its 37.8% WER includes
the full reference so losses are not hidden. Reported decode RTF still exceeded 1
despite skipping dropped audio; a low RTF produced by dropping work would not pass.
The capped 20 s queue is not stable lossless throughput. This setting is rejected.

Latency columns include decoded stale results for the two-thread case; dropped
segments have no final latency. Read these with both loss counters. True speech-end
to-final remains NOT MEASURED; the separate VAD-estimated endpoint in JSON is only a
proxy. Segment-ready latency also excludes earlier speech collection/endpointing time.
Natural-session frame counts/segment counts are correlated within one session, not
independent repeated sessions. No n=1 tail-confidence claim is made.

WebRTC CPU time was about 1.03 s per 300 s session (~0.34% of one core on average);
decoding dominated resource use. Parent CPU includes conversion/monitoring separately.
Sampled temperature peaked at 52 C in the three-thread sessions and 47.6 C in the
failed two-thread run. No direct throttle counter was established; frequency variation
alone does not prove throttling. Worker RSS excludes other processes and GPU driver
allocations; it is a process-lifetime high-water mark, not reset per decode. MemAvailable
is sampled, not an exact system-memory peak. Normalization/capture-device resampling
and microphone latency are outside these paced tests.

## Application headroom, verification and next experiment

**Actual Django/UI/SQLite load and physical-input latency: NOT MEASURED.** Expected
ports 8000/5173 were not listening on the board when checked before/after trials.
The repository now implements several app features, while unfinished review/learning
routes still return 501 scaffolds. Their transport latency would not represent
implemented feature load. No database writes, API-contract changes, firmware actions
or synthetic load were mislabelled as real application headroom. Lower RSS or a spare
core is not proof of application responsiveness.

All 20 old/new metric, queue, segmentation, privacy and fake-worker endpoint/stop tests
passed on the target. Approved fixture files remain ignored; transient normalized WAV
and active float buffers were cleaned up, and no worker remained at the end. No microphone
was recorded, no audio/decoded transcript was sent to hosted speech/agent services,
and no transcript content appears in reports/metrics. No commit or push was performed.

`local/experiment2/target-results/` on the Mac holds 27 separate JSON/CSV configurations;
`summary.json`/`.csv` provide compact aggregates. Board originals are under
`local/experiment2/results/`. Clock/GPU/source evidence is in `target-evidence/` and
individual `clock*.json`. Reproduction scripts and commands: `EXPERIMENT2_README.md`.

The current lowest-memory passing-throughput candidate is Q5/three threads with VAD,
but continuous listening is **not yet established**. The next smallest CPU experiment
is an isolated encoder/audio-context or batching-policy comparison on the same
reference clips, with independently annotated speech endpoints; the paused/short-turn
cost is the unresolved bottleneck. Then test alongside the actual deployed AAC app
with real input timestamps and agreed accuracy/latency budgets. A separate GPU follow-up
could finish the pinned build off-device and require hardware-only ICD plus positive
per-process DRM dispatch evidence before any acceleration recommendation. Do not
enable production Conversation Mode from these results.
