#!/usr/bin/env python3
"""CPU benchmark for two lighter speech models through sherpa-onnx:

  zipformer  streaming transducer, fed 100 ms chunks as audio arrives
  moonshine  Moonshine tiny, decoding the same WebRTC VAD segments as experiment 2

Same fixtures and WER code as the whisper.cpp experiments. No microphone, and
no transcript is written to disk (use --show-text to print it to the terminal).

Timing: each unit (chunk or segment) becomes available when its audio ends.
"lag" is how long after that moment its decode finished. By default the
timeline is simulated from measured decode times; --realtime sleeps instead.
"""
import argparse, array, json, resource, sys, tempfile, time, wave, zipfile
from pathlib import Path
from bench import hardware, summary, wer, words
from vad_segments import Policy, Segmenter

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "local/sherpa"
RATE = 16000
CHUNK_MS = 100
TAIL_S = 0.5  # trailing silence so the streaming model flushes its last words

def import_sherpa():
    """Use an installed sherpa_onnx, else unpack the wheels fetched by setup_sherpa.py."""
    try:
        import sherpa_onnx
    except ImportError:
        dest = STATE / "python"
        if not dest.exists():
            for wheel in sorted((STATE / "wheels").glob("*.whl")):
                zipfile.ZipFile(wheel).extractall(dest)
        sys.path.insert(0, str(dest))
        import sherpa_onnx
    return sherpa_onnx

def load_recognizer(sherpa_onnx, engine, threads):
    m = STATE / "models" / engine
    if engine == "zipformer":
        return sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(m / "tokens.txt"), encoder=str(m / "encoder-epoch-99-avg-1.int8.onnx"),
            decoder=str(m / "decoder-epoch-99-avg-1.onnx"), joiner=str(m / "joiner-epoch-99-avg-1.int8.onnx"),
            num_threads=threads, decoding_method="greedy_search")
    return sherpa_onnx.OfflineRecognizer.from_moonshine(
        preprocessor=str(m / "preprocess.onnx"), encoder=str(m / "encode.int8.onnx"),
        uncached_decoder=str(m / "uncached_decode.int8.onnx"), cached_decoder=str(m / "cached_decode.int8.onnx"),
        tokens=str(m / "tokens.txt"), num_threads=threads)

def read_pcm(path):
    """Fixtures can be any ffmpeg-readable format; normalize to 16 kHz mono 16-bit like experiment 2."""
    from vad_bench import normal_wav
    with tempfile.TemporaryDirectory() as temp:
        wav = Path(temp) / "normalized.wav"
        normal_wav(path, wav)
        with wave.open(str(wav), "rb") as f:
            return f.readframes(f.getnframes())

def floats(pcm):
    return [x / 32768 for x in array.array("h", pcm)]

def chunk_units(pcm):
    """(available_at_s, pcm) for fixed 100 ms chunks."""
    step = RATE * CHUNK_MS // 1000 * 2
    return [(min(i + step, len(pcm)) / 2 / RATE, pcm[i:i + step]) for i in range(0, len(pcm), step)]

def vad_units(pcm, is_speech, policy=Policy()):
    """(available_at_s, pcm) for each VAD segment, available when the segment closes."""
    seg, out, step = Segmenter(policy), [], RATE * policy.frame_ms // 1000 * 2
    for i in range(0, len(pcm), step):
        frame = pcm[i:i + step].ljust(step, b"\0")
        out += seg.feed(frame, is_speech(frame))
    out += seg.flush()
    return [(s["end_frame"] * policy.frame_ms / 1000, s["pcm"]) for s in out]

def timeline(units, decode, realtime=False):
    """Decode units in order. Returns per-unit decode seconds and lag seconds."""
    costs, lags, clock, epoch = [], [], 0.0, time.monotonic()
    for available, pcm in units:
        if realtime:
            time.sleep(max(0, epoch + available - time.monotonic()))
        t = time.monotonic()
        decode(pcm)
        cost = time.monotonic() - t
        clock = (time.monotonic() - epoch) if realtime else max(clock, available) + cost
        costs.append(cost)
        lags.append(clock - available)
    return costs, lags

def run(recognizer, engine, units, realtime):
    """One pass over the units. Returns (text, decode costs, lags)."""
    if engine == "zipformer":
        stream = recognizer.create_stream()
        def decode(pcm):
            stream.accept_waveform(RATE, floats(pcm))
            while recognizer.is_ready(stream):
                recognizer.decode_stream(stream)
        costs, lags = timeline(units, decode, realtime)
        t = time.monotonic()
        stream.accept_waveform(RATE, [0.0] * int(TAIL_S * RATE))
        stream.input_finished()
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
        costs.append(time.monotonic() - t)
        return recognizer.get_result(stream), costs, lags
    texts = []
    def decode(pcm):
        stream = recognizer.create_stream()
        stream.accept_waveform(RATE, floats(pcm))
        recognizer.decode_stream(stream)
        texts.append(stream.result.text)
    costs, lags = timeline(units, decode, realtime)
    return " ".join(texts), costs, lags

def peak_rss_bytes():
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss if sys.platform == "darwin" else rss * 1024

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--engine", choices=["zipformer", "moonshine"], required=True)
    p.add_argument("--manifest", default=str(ROOT / "local/experiment2/fixtures.json"))
    p.add_argument("--case", required=True, help="fixture id, or 'silence' for 30 s of digital silence")
    p.add_argument("--threads", type=int, choices=[1, 2, 3], default=1)
    p.add_argument("--policy", choices=["vad", "file"], default="vad",
                   help="moonshine only: decode VAD segments, or the whole file as one segment")
    p.add_argument("--realtime", action="store_true", help="feed audio at real-time pace instead of simulating")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--show-text", action="store_true")
    p.add_argument("--output", required=True, help="new folder inside local/sherpa/results")
    a = p.parse_args()
    out = Path(a.output).resolve()
    if out.exists(): p.error("Output already exists; preserve previous results")
    if not out.is_relative_to(STATE.resolve()): p.error("Keep outputs inside ignored local/sherpa")

    reference = None
    if a.case == "silence":
        pcm = bytes(30 * RATE * 2)
    else:
        manifest = Path(a.manifest).resolve()
        case = next(x for x in json.loads(manifest.read_text()) if x["id"] == a.case)
        pcm = read_pcm(manifest.parent / case["audio"])
        if "reference_file" in case:
            reference = (manifest.parent / case["reference_file"]).read_text()
    duration = len(pcm) / 2 / RATE

    if a.engine == "zipformer":
        units = chunk_units(pcm)
    elif a.policy == "file":
        if duration > 30: p.error("--policy file is for clips up to 30 s")
        units = [(duration, pcm)]
    else:
        from vad_bench import load_vad
        vad = load_vad()[0].Vad(2)
        units = vad_units(pcm, lambda frame: vad.is_speech(frame, RATE))

    sherpa_onnx = import_sherpa()
    t = time.monotonic()
    recognizer = load_recognizer(sherpa_onnx, a.engine, a.threads)
    load_s = time.monotonic() - t
    run(recognizer, a.engine, [u for u in units if u[0] <= 10][:100] or units[:1], False)  # warm-up, excluded

    result = dict(schema_version=1, engine=a.engine, case_id=a.case, configuration=vars(a),
                  sherpa_onnx_version=sherpa_onnx.__version__, source_duration_s=duration,
                  on_target=sys.platform == "linux" and hardware()["architecture"] in ("aarch64", "arm64"),
                  pacing="realtime" if a.realtime else "simulated from measured decode times",
                  hardware_before=hardware(), model_load_s=load_s, units=len(units), runs=[])
    for n in range(a.runs):
        cpu, t = time.process_time(), time.monotonic()
        text, costs, lags = run(recognizer, a.engine, units, a.realtime)
        cpu = time.process_time() - cpu
        item = dict(repeat=n + 1, decode_s=sum(costs), decode_rtf_source_audio=sum(costs) / duration,
                    cpu_s=cpu, average_cores_at_realtime=cpu / duration, elapsed_s=time.monotonic() - t,
                    lag_s=summary(lags), final_lag_s=lags[-1] if lags else None,
                    hypothesis_words=len(words(text)),
                    accuracy=wer(reference, text) if reference is not None else None)
        result["runs"].append(item)
        print(json.dumps({k: item[k] for k in ("repeat", "decode_rtf_source_audio", "average_cores_at_realtime",
                                               "final_lag_s", "hypothesis_words")}
                         | {"lag_p95_s": item["lag_s"]["p95"], "wer": (item["accuracy"] or {}).get("wer")}), flush=True)
        if a.show_text: print(text, flush=True)
    result["peak_rss_bytes"] = peak_rss_bytes()
    result["summaries"] = {k: summary([r[k] for r in result["runs"]])
                           for k in ("decode_s", "decode_rtf_source_audio", "cpu_s", "average_cores_at_realtime")}
    result["hardware_after"] = hardware()
    out.mkdir(parents=True)
    (out / "metrics.json").write_text(json.dumps(result, indent=2) + "\n")

if __name__ == "__main__":
    main()
