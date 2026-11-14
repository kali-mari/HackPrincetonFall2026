#!/bin/sh
set -eu
export TMPDIR=/out/tmp
mkdir -p "$TMPDIR"
git -c safe.directory=/src -C /src rev-parse HEAD > /out/source-commit.txt
test "$(cat /out/source-commit.txt)" = a8d002cfd879315632a579e73f0148d06959de36
test -z "$(git -c safe.directory=/src -C /src status --porcelain --untracked-files=no)"
cmake -S /native -B /out/build -DWHISPER_SOURCE=/src \
 -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
 -DGGML_NATIVE=OFF -DGGML_CPU_ARM_ARCH=armv8-a \
 -DGGML_CUDA=OFF -DGGML_METAL=OFF -DGGML_VULKAN=ON \
 -DGGML_BLAS=OFF -DGGML_OPENMP=OFF -DGGML_ACCELERATE=OFF \
 -DWHISPER_COREML=OFF -DWHISPER_OPENVINO=OFF -DWHISPER_CURL=OFF \
 -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_EXAMPLES=OFF -DWHISPER_BUILD_SERVER=OFF
cmake --build /out/build --target transcription-worker2 -j 1
cp /out/build/transcription-worker2 /out/transcription-worker2
sha256sum /out/transcription-worker2 > /out/binary.sha256
readelf -h /out/transcription-worker2 > /out/elf-header.txt
readelf -d /out/transcription-worker2 > /out/elf-dynamic.txt
readelf --version-info /out/transcription-worker2 > /out/elf-versions.txt
c++ --version > /out/compiler.txt
cmake --version > /out/cmake.txt
glslc --version > /out/glslc.txt
dpkg-query -W > /out/packages.txt
