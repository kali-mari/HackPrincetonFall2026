#!/usr/bin/env python3
"""Explicit opt-in network/build setup. No sudo, pip, package manager or audio downloads."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

COMMIT = "a8d002cfd879315632a579e73f0148d06959de36"  # v1.7.6
OPTIONS = ["-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LIBS=OFF",
           "-DGGML_CUDA=OFF", "-DGGML_METAL=OFF", "-DGGML_VULKAN=OFF",
           "-DGGML_BLAS=OFF", "-DGGML_OPENMP=OFF", "-DGGML_NATIVE=OFF",
           "-DGGML_ACCELERATE=OFF", "-DWHISPER_COREML=OFF", "-DWHISPER_OPENVINO=OFF",
           "-DWHISPER_CURL=OFF", "-DWHISPER_BUILD_TESTS=OFF",
           "-DWHISPER_BUILD_EXAMPLES=OFF", "-DWHISPER_BUILD_SERVER=OFF"]

def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()

def run(*args):
    return subprocess.check_output(args, stderr=subprocess.STDOUT, text=True).strip()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--download-model", required=True, choices=["tiny.en", "base.en", "tiny.en-q5_1", "base.en-q5_1"])
    p.add_argument("--jobs", type=int, default=2)
    a = p.parse_args()
    if a.jobs < 1: p.error("jobs must be positive")
    root = Path(__file__).resolve().parent
    state = root / "local"; state.mkdir(exist_ok=True, mode=0o700)
    source = state / "whisper.cpp"; build = state / "build"
    if not source.exists():
        run("git", "init", str(source))
        run("git", "-C", str(source), "fetch", "--depth=1", "https://github.com/ggml-org/whisper.cpp.git", COMMIT)
        run("git", "-C", str(source), "checkout", "--detach", "FETCH_HEAD")
    if run("git", "-C", str(source), "rev-parse", "HEAD") != COMMIT:
        raise RuntimeError("Existing source has wrong commit")
    if run("git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("Existing upstream source is modified")
    run("cmake", "-S", str(root), "-B", str(build), "-DWHISPER_SOURCE="+str(source), *OPTIONS)
    run("cmake", "--build", str(build), "--target", "transcription-worker", "-j", str(a.jobs))
    lockpath = state / "setup.json"
    lock = json.loads(lockpath.read_text()) if lockpath.exists() else {"models": {}}
    name = a.download_model; model = state / ("ggml-"+name+".bin")
    entry = lock["models"].get(name)
    if entry is None:
        # Pin the first explicitly selected snapshot; later setup reuses its checksum.
        with urllib.request.urlopen("https://huggingface.co/api/models/ggerganov/whisper.cpp?blobs=true", timeout=60) as r:
            meta = json.load(r)
        info = next(x for x in meta["siblings"] if x["rfilename"] == model.name)
        entry = {"revision": meta["sha"], "sha256": info["lfs"]["sha256"], "file": model.name}
    if not model.exists():
        url = "https://huggingface.co/ggerganov/whisper.cpp/resolve/"+entry["revision"]+"/"+model.name
        partial = model.with_suffix(".partial")
        with urllib.request.urlopen(url, timeout=120) as src, partial.open("wb") as dst:
            while True:
                block = src.read(1024*1024)
                if not block: break
                dst.write(block)
        if sha(partial) != entry["sha256"]:
            partial.unlink(); raise RuntimeError("Downloaded model checksum mismatch")
        partial.rename(model)
    if sha(model) != entry["sha256"]: raise RuntimeError("Model checksum mismatch")
    lock["models"][name] = entry
    worker = build / "transcription-worker"
    lock.update(commit=COMMIT, options=OPTIONS, worker_sha256=sha(worker),
                worker_source_sha256=sha(root/"worker.cpp"),
                cmake_source_sha256=sha(root/"CMakeLists.txt"),
                cmake_cache=(build/"CMakeCache.txt").read_text(),
                compiler=run("c++", "--version"), cmake=run("cmake", "--version"))
    lockpath.write_text(json.dumps(lock, indent=2)+"\n")
    print("Local CPU build and checksummed model ready:", name)

if __name__ == "__main__": main()
