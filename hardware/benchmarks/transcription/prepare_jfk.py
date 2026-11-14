#!/usr/bin/env python3
"""Explicit public-fixture preparation; never accesses a microphone."""
import argparse
import array
import hashlib
import json
import math
from pathlib import Path
import platform
import random
import shutil
import sys
import urllib.request
import wave

COMMIT = "a8d002cfd879315632a579e73f0148d06959de36"
URL = "https://raw.githubusercontent.com/ggml-org/whisper.cpp/"+COMMIT+"/samples/jfk.wav"

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--download", action="store_true", help="explicitly download the public JFK WAV")
    p.add_argument("--variants", action="store_true", help="generate synthetic repeated, paused, silent and noisy fixtures")
    a = p.parse_args()
    root = Path(__file__).resolve().parent/"local"
    fixtures = root/"fixtures"; fixtures.mkdir(parents=True, exist_ok=True, mode=0o700)
    audio = fixtures/"jfk.wav"
    if not audio.exists():
        source = root/"whisper.cpp/samples/jfk.wav"
        if source.is_file(): shutil.copyfile(source, audio)
        elif a.download:
            with urllib.request.urlopen(URL, timeout=60) as r: audio.write_bytes(r.read())
        else: p.error("Public fixture missing; use --download to explicitly fetch it")
    with wave.open(str(audio), "rb") as f:
        if (f.getframerate(), f.getnchannels(), f.getsampwidth()) != (16000, 1, 2):
            raise ValueError("Expected 16 kHz mono signed PCM16 fixture")
        frames = f.readframes(f.getnframes())
    provenance = {"source": URL, "source_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
                  "upstream_license": "https://github.com/ggml-org/whisper.cpp/blob/"+COMMIT+"/LICENSE",
                  "python": platform.python_version(), "variants": "synthetic; not representative conversation or room noise"}
    (root/"jfk.json").write_text(json.dumps([{"id":"jfk01", "category":"short", "audio":"fixtures/jfk.wav"}], indent=2))
    (root/"jfk-replay.json").write_text(json.dumps([{"id":f"jfk{i:02d}", "category":"short", "audio":"fixtures/jfk.wav"} for i in range(6)], indent=2))
    if a.variants:
        def save(name, data):
            with wave.open(str(fixtures/name), "wb") as f:
                f.setnchannels(1); f.setsampwidth(2); f.setframerate(16000); f.writeframes(data)
        save("jfk-continuous.wav", frames*5)
        save("jfk-pauses.wav", frames+bytes(len(frames))+frames)
        save("jfk-silence.wav", bytes(len(frames)))
        samples = array.array("h"); samples.frombytes(frames)
        if sys.byteorder != "little": samples.byteswap()
        rng = random.Random(20261114)
        noise = [rng.gauss(0, 1) for _ in samples]
        signal_power = sum(x*x for x in samples)/len(samples)
        noise_power = sum(x*x for x in noise)/len(noise)
        scale = math.sqrt(signal_power/(10*noise_power))  # 10 dB before clipping
        mixed = [int(round(x+n*scale)) for x,n in zip(samples, noise)]
        clipped = sum(x < -32768 or x > 32767 for x in mixed)
        out = array.array("h", [max(-32768, min(32767, x)) for x in mixed])
        if sys.byteorder != "little": out.byteswap()
        save("jfk-noisy.wav", out.tobytes())
        provenance.update(noise_seed=20261114, noise_kind="white Gaussian", snr_db_before_clipping=10, clipped_samples=clipped)
        cases = [{"id":"jfk_repeat", "category":"continuous", "audio":"fixtures/jfk-continuous.wav"},
                 {"id":"jfk_pauses", "category":"pauses", "audio":"fixtures/jfk-pauses.wav"},
                 {"id":"jfk_silence", "category":"silence", "silence":True, "audio":"fixtures/jfk-silence.wav"},
                 {"id":"jfk_noisy", "category":"noisy", "audio":"fixtures/jfk-noisy.wav"}]
        (root/"jfk-variants.json").write_text(json.dumps(cases, indent=2))
    (fixtures/"provenance.json").write_text(json.dumps(provenance, indent=2)+"\n")
    print("Public fixture manifests prepared; synthetic variants:", a.variants)

if __name__ == "__main__": main()
