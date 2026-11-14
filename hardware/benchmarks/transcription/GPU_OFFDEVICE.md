# Off-device Vulkan build and UNO Q runtime probes

Outcome: **the off-device build succeeded; the tested GPU inference paths failed**.
CPU fallback remains usable. No successful hardware GPU transcription, GPU speedup,
CPU reduction or GPU accuracy measurement is established. The earlier experiment
reports/results remain unchanged; this is a separate follow-up.

## Build and compatibility evidence

The existing Mac Docker engine provided Linux aarch64, 11 CPUs and ~8 GB VM RAM.
The isolated build container used 6 GB maximum memory, a four-CPU quota and one build
job. It used Debian 13 ARM64 to match the board; package installs happened only inside
the container. No Mac/UNO Q system packages, driver, kernel, firmware or clock settings
were changed in this follow-up; no reboot command was issued.

whisper.cpp commit: `a8d002cfd879315632a579e73f0148d06959de36` (v1.7.6), unchanged.
Compiler: Debian GCC 14.2.0-19. Release, static whisper/ggml libraries, Vulkan enabled,
other acceleration libraries disabled, `GGML_NATIVE=OFF`, explicit `armv8-a` CPU ISA.
The same `native2/worker.cpp` supports CPU and Vulkan selection in one binary.
Only the public upstream source, native wrapper and output directory were mounted;
no models, reference files or private recordings were needed by the build container.

- Base image: `debian:13-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2`.
- Completed build image ID: `sha256:6ac33ce9757bbe557ac114566358bfd8c8699c323af646b9b24e9f1ff286a594`.
- Build duration on the Mac's Linux VM: **179.7 s**. This is compilation
  time, not UNO Q transcription performance.
- ARM64 Linux executable SHA-256: `d8a31cc62c4f94fbe039c142dddbebe61c936b24bbcb2dcf49d52a3d79a07b24`.
- ELF dependencies: libvulkan.so.1, libstdc++.so.6, libm.so.6, libgcc_s.so.1, libc.so.6.
  Highest required glibc symbol version 2.38; the board has glibc 2.41. `ldd` resolved
  all dependencies, and actual CPU decoding on the board confirmed executable compatibility.

`local/experiment3/` retains the compile log, complete CMake cache/options, installed
container package versions, compiler/glslc versions, ELF metadata and image provenance.
The Dockerfile pins its base digest. Reuse the recorded completed image ID for exact
compiler-package reuse; rebuilding APT packages later can select newer package revisions.

## Actual board probes

Every inference attempt ran on the USB-connected UNO Q as `arduino`, never on the Mac.
The existing Debian 13.2 / kernel 6.16.7 / Mesa Turnip 25.2.6 stack was retained.
`VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/freedreno_icd.json` restricted enumeration to
physical **Turnip Adreno 702**, excluding llvmpipe. No Vulkan API-version override or
software renderer was used. The GPU reports 16,384 bytes shared memory per workgroup,
32-wide subgroups, FP16 support, and no matrix cores/integer-dot acceleration in the
pinned backend's diagnostics. Reported Vulkan API remained 1.0.318 on the physical GPU.

The public approved 11 s JFK sample was normalized locally. Same pinned model(s),
greedy English, three CPU threads, temperature 0, no carried context, no transcript
logging. Initial model load/first decode were separate; failed probes have zero valid
warm samples. Runtime diagnostics contain backend/error messages only, not decoded text.

| Probe | Outcome | Valid measured n | Evidence |
|---|---|---:|---|
| tiny.en Vulkan default, initial attempt | Failed during first decode | 0 | Selected Vulkan0; model/compute buffers created; initial error filtering was incomplete |
| tiny.en Vulkan default, diagnostic retry | Failed during first decode | 0 | Mesa workgroup-barrier/concurrent-wave error; worker exit 1 |
| tiny.en Vulkan with `GGML_VK_DISABLE_F16=1` | Failed initialization | 0 | Backend rejected insufficient shared memory for matrix multiplication |
| tiny.en-q5_1 Vulkan default | Failed during first decode | 0 | Same Mesa concurrent-wave/workgroup-barrier error |
| Same binary, CPU selection | Completed on UNO Q | 1 | 7.844 s decode, RTF 0.713, 223.9 MiB peak worker RSS |

The default GPU path loaded 77.11 MB of tiny.en weights into the Vulkan0 backend and
allocated compute buffers. That was **not proof of successful inference**. Its exact
Mesa diagnostic was:

```
Compute shader ((null)) which has workgroup barrier cannot be used because it's impossible to have enough concurrent waves.
```

The upstream-supported FP32 diagnostic switch selected `fp16: 0`, but the pinned
backend then raised:

```
Shared memory size too small for matrix multiplication.
```

This 16 KiB shared-memory limit is a per-workgroup GPU shader resource, distinct
from the board's 4 GB system RAM that constrained compilation earlier. No driver tweak
was used to conceal the limit. Q5 weights loaded as 31.57 MB but did not avoid the
concurrent-wave failure. These results apply to the tested pinned backend/driver/kernel
paths; they do not prove that this GPU can never transcribe with another compatible
implementation.

No completed GPU decode exists, so there is **no valid GPU RTF, WER, CPU-use reduction,
latency comparison or sustained replay result**. Hardware engine/cycle counters were
prepared as runtime evidence but cannot establish a successful inference from these
failed calls. The successful CPU result is n=1 compatibility evidence, not a robust
performance benchmark; no new reference transcript was supplied for JFK, so WER is
NOT MEASURED. Earlier CPU/VAD accuracy/sustained findings remain the applicable results.

## Reproduction

From `hardware/benchmarks/transcription/`, start the existing Docker engine and build
only the minimal compiler context. Normal TLS and Debian package verification stay on.

```sh
docker desktop start
docker build --platform linux/arm64 -t unoq-whisper-vulkan-builder:exp3 gpu_offdevice
docker run --rm --platform linux/arm64 --memory 6g --cpus 4 \
  --mount "type=bind,source=$PWD/local/whisper.cpp,target=/src,readonly" \
  --mount "type=bind,source=$PWD/native2,target=/native,readonly" \
  --mount "type=bind,source=$PWD/local/experiment3,target=/out" \
  unoq-whisper-vulkan-builder:exp3
```

The build script verifies the source commit/cleanliness and never performs inference.
Transfer the binary and `build-provenance.json` over the existing ADB connection to
`/home/arduino/hardware/benchmarks/transcription/local/experiment3/`, along with
`gpu_trial3.py` in the benchmark root. Preserve originals and verify SHA-256. On the board,
use new output names for each attempt:

```sh
python3 gpu_trial3.py --backend cpu --case jfk --runs 1 --output local/experiment3/results/new-cpu-control
python3 gpu_trial3.py --backend gpu --case jfk --runs 1 --output local/experiment3/results/new-gpu-probe
GGML_VK_DISABLE_F16=1 python3 gpu_trial3.py --backend gpu --case jfk --runs 1 --output local/experiment3/results/new-gpu-f32-probe
python3 gpu_trial3.py --backend gpu --model tiny.en-q5_1 --case jfk --runs 1 --worker-timeout 60 --output local/experiment3/results/new-gpu-q5-probe
```

The runner uses exclusive session locking and existing experiment2 metric/queue logic;
it does not rewrite those sources/results. Worker core dumps are disabled for the
diagnostic reruns. No microphone is opened; no transcript content is exported. Model,
fixtures and transient normalized audio remain local. The build container has stopped;
its image and build artifacts are retained for reproduction. No commit/push was made.

Aggregate JSON/CSV and individual probe records: `local/experiment3/summary.*` and
`local/experiment3/target-results/` on the Mac; `local/experiment3/results/` on the UNO Q.

## Recommendation

**GPU use is not established for this stack.** Keep the measured CPU/VAD fallback and
its existing **not yet established for continuous listening** recommendation. The build
RAM obstacle is solved. The next GPU experiment would need a deliberate backend/shader
workgroup adaptation or separately pinned compatible backend revision, followed by a
matched CPU rerun, real hardware dispatch proof, reference accuracy and latency tests.
Do not infer a GPU speed benefit from successful loading or hide these failures with
software Vulkan. No such source/driver change was attempted in this follow-up.
