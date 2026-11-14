# GPU follow-up: newer backend

GPU transcription remains **not working on this tested stack**. This is a runtime failure, not a missing compiler or a failed installation. No conclusion that the hardware can never run speech inference follows from this test.

## What ran

Actual UNO Q 4GB, Linux ARM64, Turnip Adreno 702, Mesa 25.2.6-1~bpo13+1. The physical GPU ICD alone was selected, excluding llvmpipe. No microphone, cloud inference, driver/kernel/firmware changes, or reboot. All inference ran on the board. Compilation alone used the existing Debian ARM64 Docker builder off-device.

Separately pinned whisper.cpp **v1.8.7**, commit `48f628a84833905ee4a0658ee6d4a5c915ce1997`. Unlike the original v1.7.6 results, this revision contains newer shared-memory accounting and tile selection. The relevant upstream change is https://github.com/ggml-org/llama.cpp/pull/22693 ; its presence did not establish compatibility with this GPU.

Release build, static ggml/whisper libraries, ARMv8-a, native tuning disabled, CPU plus Vulkan enabled. CUDA/Metal/BLAS/OpenMP/Accelerate/CoreML/OpenVINO disabled. One build job, container capped at 6GB and four CPUs. `spirv-headers` was installed only inside the disposable container. Compiler/package versions, CMake cache, source/binary checksums and exact build command are in ignored `local/experiment4/`.

Model: original tiny.en, SHA256 `921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f`. Runtime: three CPU threads, greedy English, best_of=1, temperature=0, increment=0, no context carry, flash attention disabled. Public reference fixture `read_short`, 5.855 seconds, 16kHz mono. Original metric and reference-normalization code reused unchanged.

| Configuration | Valid warm samples | Result |
|---|---:|---|
| Vulkan default | 0 | Model allocated on Vulkan0; first decode failed with `vk::Device::waitForFences: ErrorDeviceLost` |
| Vulkan conservative | 0 | Same failure with async, graph optimization, and fusion disabled |
| Matched CPU control, same new binary | 3 | Median decode 8.118s; median source RTF 1.386; WER 1/17 = 5.9% |

The CPU control validates binary/model/fixture compatibility. It is not a replacement for the older CPU benchmark or a cross-version GPU speed comparison. GPU RTF, accuracy, and latency are **unavailable**, not zero. The two failed first decodes are not repeated valid inference samples. Kernel logs attribute a hang and UCHE READ TRANSLATION fault to the new transcription worker, followed by kernel recovery. These observations do not isolate whether the root cause is backend, shader compiler, driver, or an interaction.

## OpenCL assessment (inference NOT RUN)

Read-only `clinfo` shows existing Mesa Rusticl, GPU device `FD702`, Qualcomm, OpenCL 3.0, FP16. It reports zero maximum subgroups and no `cl_khr_subgroups` or `cl_intel_subgroups` extension. This revision's OpenCL backend (`ggml/src/ggml-opencl/ggml-opencl.cpp`, `ggml_opencl_is_device_supported`) requires subgroups for OpenCL 3.0 and recognizes device names containing Adreno/Qualcomm or Intel; `FD702` with version `OpenCL 3.0` also fails that name check. A name alias alone cannot supply missing subgroup capabilities. No feature checks were bypassed and no OpenCL inference or performance is claimed.

## Reproduce

Preserve the original builds. From this benchmark folder, after the already documented dependency/model/fixture setup:

```sh
mkdir -p local/experiment4/whisper.cpp
git -C local/experiment4/whisper.cpp init
git -C local/experiment4/whisper.cpp fetch --depth 1 https://github.com/ggml-org/whisper.cpp.git 48f628a84833905ee4a0658ee6d4a5c915ce1997
git -C local/experiment4/whisper.cpp checkout --detach FETCH_HEAD
# Build the existing builder image using GPU_OFFDEVICE.md first.
docker run --rm --platform linux/arm64 --memory 6g --cpus 4 --entrypoint sh \
  --mount "type=bind,source=$PWD/local/experiment4/whisper.cpp,target=/src,readonly" \
  --mount "type=bind,source=$PWD/native2,target=/native,readonly" \
  --mount "type=bind,source=$PWD/gpu_newbackend/build.sh,target=/build4.sh,readonly" \
  --mount "type=bind,source=$PWD/local/experiment4,target=/out" \
  unoq-whisper-vulkan-builder:exp3 /build4.sh
```

The recorded successful build provenance includes binary SHA256 and must accompany the binary. Transfer `gpu_trial4.py`, `local/experiment4/transcription-worker2`, and `local/experiment4/build-provenance.json` to the same paths on the board, chmod executable, then run there (use fresh output names):

```sh
python3 gpu_trial4.py --backend gpu --case read_short --runs 3 --output local/experiment4/results/vulkan-new
GGML_VK_DISABLE_ASYNC=1 GGML_VK_DISABLE_GRAPH_OPTIMIZE=1 GGML_VK_DISABLE_FUSION=1 \
 python3 gpu_trial4.py --backend gpu --case read_short --runs 3 --worker-timeout 120 --output local/experiment4/results/vulkan-conservative-new
python3 gpu_trial4.py --backend cpu --case read_short --runs 3 --output local/experiment4/results/cpu-new
```

Rebuilding requires regenerating provenance and checksums from that build; never copy an old checksum onto a different binary. The exact successful Docker invocation and package snapshot are retained locally. The runner rejects pin/checksum mismatches and existing result folders. Diagnostics exclude decoded transcript content, core dumps are disabled per worker, private artifacts remain ignored.

## Saved evidence and next step

`local/experiment4/summary.json` and `.csv`, `target-results/*/metrics.json` and `.csv`, `kernel-gpu-faults.txt`, `opencl-capabilities.txt`, build logs/cache and `build-provenance.json`. Host copy and board evidence are kept separately from experiment3 and older trials. GPU failures are explicit with empty valid samples.

Do not treat another package install as a demonstrated fix. Further GPU work needs an identified Turnip/kernel fix for the observed translation fault, or a compatible backend with kernels that do not require the missing OpenCL subgroup capability. A supported driver change would require separate approval and rollback planning. Continuous or segmented GPU transcription is **not yet established**.

Successful new binary SHA256: `7881fee74d7fc163301c3b5556e024b4ed6e86066165855962fdd8c30323c269`. Build wall time: 219.357 seconds (build host only).
