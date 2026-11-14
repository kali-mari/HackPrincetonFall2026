#!/usr/bin/env python3
"""Fetch the pinned sherpa-onnx ARM64 wheels and the two candidate models into
local/sherpa/. Run on the online Mac, then copy local/sherpa/ to the board.
Nothing is installed system-wide; sherpa_bench.py unpacks the wheels itself.
"""
import hashlib, json, subprocess, sys, tarfile, urllib.request
from pathlib import Path

STATE = Path(__file__).resolve().parent / "local/sherpa"
VERSION = "2.0.1"
RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
# engine -> (archive, files the runner needs)
MODELS = {
    "zipformer": ("sherpa-onnx-streaming-zipformer-en-20M-2023-02-17",
                  ["encoder-epoch-99-avg-1.int8.onnx", "decoder-epoch-99-avg-1.onnx",
                   "joiner-epoch-99-avg-1.int8.onnx", "tokens.txt"]),
    "moonshine": ("sherpa-onnx-moonshine-tiny-en-int8",
                  ["preprocess.onnx", "encode.int8.onnx", "uncached_decode.int8.onnx",
                   "cached_decode.int8.onnx", "tokens.txt"]),
}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    wheels = STATE / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "pip", "download", f"sherpa-onnx=={VERSION}",
                    "--platform", "manylinux2014_aarch64", "--platform", "manylinux_2_17_aarch64",
                    "--python-version", "3.13", "--implementation", "cp", "--abi", "cp313",
                    "--only-binary=:all:", "-d", str(wheels)], check=True)
    record = {"sherpa_onnx_version": VERSION,
              "wheels": {w.name: sha(w) for w in sorted(wheels.glob("*.whl"))}, "models": {}}
    for engine, (name, files) in MODELS.items():
        dest = STATE / "models" / engine
        dest.mkdir(parents=True, exist_ok=True)
        if not all((dest / f).is_file() for f in files):
            archive = STATE / f"{name}.tar.bz2"
            print("downloading", name, flush=True)
            urllib.request.urlretrieve(RELEASES + archive.name, archive)
            with tarfile.open(archive) as tar:
                for f in files:
                    (dest / f).write_bytes(tar.extractfile(f"{name}/{f}").read())
            archive.unlink()
        record["models"][engine] = {"archive": name, "files": {f: sha(dest / f) for f in files}}
    (STATE / "setup.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))

if __name__ == "__main__":
    main()
