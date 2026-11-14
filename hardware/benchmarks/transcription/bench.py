#!/usr/bin/env python3
"""Offline file and paced bounded-segment replay benchmark (stdlib Python)."""
import argparse
import array
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import selectors
import statistics
import subprocess
import sys
import tempfile
import time
import unicodedata
from collections import deque
from contextlib import contextmanager
from setup_local import COMMIT, OPTIONS, sha

ROOT = Path(__file__).resolve().parent

def words(text):
    """NFKC + casefold; punctuation becomes spaces, no number expansion."""
    text = unicodedata.normalize("NFKC", text).casefold()
    return "".join(c if c.isalnum() else " " for c in text).split()

def wer(reference, hypothesis):
    r, h = words(reference), words(hypothesis)
    row = list(range(len(h)+1))
    for i, a in enumerate(r, 1):
        nxt = [i]
        for j, b in enumerate(h, 1):
            nxt.append(min(nxt[-1]+1, row[j]+1, row[j-1]+(a != b)))
        row = nxt
    return {"word_errors": row[-1], "reference_words": len(r),
            "wer": row[-1]/len(r) if r else None}

def percentile(values, p=0.95):
    """Nearest-rank percentile; never implies population tail confidence."""
    return sorted(values)[max(0, math.ceil(len(values)*p)-1)] if values else None

def summary(values):
    return {"n": len(values), "median": statistics.median(values) if values else None,
            "p95": percentile(values), "max": max(values) if values else None}

def rtf(seconds, duration):
    if duration <= 0: raise ValueError("Audio must have positive duration")
    return seconds/duration

def capture(*cmd):
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError): return None

def hardware():
    info = {"os": platform.system(), "os_release": platform.release(),
            "architecture": platform.machine(), "logical_cpus": os.cpu_count(),
            "target_status": "NOT RUN", "target_identity": "unverified"}
    if sys.platform.startswith("linux"):
        info["os_version"] = Path("/etc/os-release").read_text() if Path("/etc/os-release").exists() else None
        info["cpu_info"] = Path("/proc/cpuinfo").read_text() if Path("/proc/cpuinfo").exists() else None
        if info["cpu_info"]:
            info["cpu_info"] = "\n".join(x for x in info["cpu_info"].splitlines() if not x.lower().startswith("serial"))
        info["memory"] = {k: int(v.split()[0])*1024 for k, v in
                          (line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
                          if k in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree")}
        dt = Path("/proc/device-tree/model")
        info["board_model"] = dt.read_bytes().decode(errors="replace").strip("\0") if dt.exists() else None
        for key, path in [("temperature_millidegrees_c", "/sys/class/thermal/thermal_zone0/temp"),
                          ("cpu0_frequency_khz", "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq")]:
            info[key] = Path(path).read_text().strip() if Path(path).exists() else None
    elif sys.platform == "darwin":
        info["os_version"] = capture("sw_vers", "-productVersion")
        info["board_model"] = capture("sysctl", "-n", "hw.model")
        info["cpu"] = capture("sysctl", "-n", "machdep.cpu.brand_string")
        info["memory_total_bytes"] = capture("sysctl", "-n", "hw.memsize")
        info["available_memory_snapshot"] = capture("vm_stat")
    info["load_average"] = list(os.getloadavg())
    return info

class Worker:
    def __init__(self, model, threads, timeout):
        self.timeout = timeout
        self.started = time.monotonic()
        self.p = subprocess.Popen([str(ROOT/"local/build/transcription-worker"), str(model), str(threads)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, bufsize=1)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.p.stdout, selectors.EVENT_READ)
        try:
            self.load = self.read()
            self.load["startup_to_ready_s"] = time.monotonic()-self.started
        except BaseException:
            self.close(); raise
    def read(self):
        if not self.selector.select(self.timeout): raise RuntimeError("Worker timed out; no decoded text logged")
        line = self.p.stdout.readline()
        if not line: raise RuntimeError("Worker failed; no decoded text logged")
        return json.loads(line)
    def infer(self, path):
        started = time.monotonic()
        self.p.stdin.write(str(path)+"\n"); self.p.stdin.flush()
        result = self.read()
        result["request_wall_s"] = time.monotonic()-started
        return result
    def close(self):
        self.selector.close()
        if self.p.poll() is None:
            self.p.terminate()
            try: self.p.wait(timeout=5)
            except subprocess.TimeoutExpired: self.p.kill(); self.p.wait()
        for f in (self.p.stdin, self.p.stdout):
            if f: f.close()
    def __enter__(self): return self
    def __exit__(self, *args): self.close()

def normalize(source, output):
    # All decoding is local. No microphone/device input and no network protocols.
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
                    "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le",
                    "-c:a", "pcm_f32le", "-y", str(output)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    duration = output.stat().st_size/64000
    if duration <= 0 or duration > 3600: raise ValueError("Fixture duration must be in (0, 3600] seconds")
    return duration

def score(result, case):
    text = result.pop("text")  # never written to metrics, console or exception
    result.update(duration_s=case["duration_s"], rtf=rtf(result["inference_s"], case["duration_s"]),
                  cpu_percent=100*result["cpu_s"]/result["inference_s"],
                  decoded_words=len(words(text)),
                  hallucinated_on_silence=bool(text.strip()) if case.get("silence") else None)
    if "reference" in case: result.update(wer(case["reference"], text))
    return result

def admit(queue, index, durations, capacity):
    """Drop oldest pending segments; active decode is outside the queue budget."""
    queue.append(index)
    dropped = []
    while sum(durations[i] for i in queue) > capacity+1e-9:
        dropped.append(queue.popleft())
    return dropped

def replay(worker, cases, capacity):
    durations = [c["duration_s"] for c in cases]
    arrivals = []; total = 0
    for duration in durations:
        total += duration; arrivals.append(total)
    epoch = time.monotonic(); pending = deque(); cursor = 0
    rows = []; dropped = []; trace = []; max_queue = 0
    while cursor < len(cases) or pending:
        now = time.monotonic()-epoch
        while cursor < len(cases) and arrivals[cursor] <= now:
            lost = admit(pending, cursor, durations, capacity)
            dropped.extend(lost); cursor += 1
        queued = sum(durations[i] for i in pending)
        max_queue = max(max_queue, queued)
        trace.append({"elapsed_s": now, "pending_audio_s": queued, "dropped_count": len(dropped)})
        if not pending:
            if cursor < len(cases): time.sleep(max(0, min(0.05, arrivals[cursor]-now)))
            continue
        i = pending.popleft(); case = cases[i]
        started = time.monotonic()-epoch
        result = score(worker.infer(case["pcm"]), case)
        final = time.monotonic()-epoch
        # Whole segment must arrive before decoding; annotation is within segment.
        speech_end = case.get("speech_end_s")
        result.update(case_id=case["id"], arrival_s=arrivals[i], decode_start_s=started,
                      final_s=final, wait_after_arrival_s=started-arrivals[i],
                      speech_end_to_final_s=(final-(arrivals[i]-durations[i]+speech_end))
                      if speech_end is not None else None)
        rows.append(result)
    return {"rows": rows, "trace": trace, "dropped_segments": len(dropped),
            "dropped_audio_s": sum(durations[i] for i in dropped), "max_pending_audio_s": max_queue,
            "input_audio_s": total, "elapsed_s": time.monotonic()-epoch,
            "capacity_pending_audio_s": capacity,
            "final_latency_s": summary([r["speech_end_to_final_s"] for r in rows if r["speech_end_to_final_s"] is not None])}

def validate_manifest(manifest, base):
    if not isinstance(manifest, list) or not manifest: raise ValueError("Manifest must be a nonempty list")
    seen = set()
    for c in manifest:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", c["id"]) or c["id"] in seen:
            raise ValueError("Use unique anonymous fixture IDs")
        seen.add(c["id"])
        if c.get("category") not in ("short", "continuous", "pauses", "silence", "noisy"):
            raise ValueError("Invalid category")
        path = (base/c["audio"]).resolve()
        if not path.is_file(): raise ValueError("Fixture missing")
        c["source"] = path
        if c.get("silence", False) != (c["category"] == "silence"):
            raise ValueError("Silence cases require silence=true")
        if "reference_file" in c: c["reference"] = (base/c["reference_file"]).read_text()
    return manifest

@contextmanager
def synthetic_load(count):
    processes = []
    try:
        for _ in range(count):
            processes.append(subprocess.Popen([sys.executable, "-c", "while True: pass"],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        yield
    finally:
        for p in processes: p.terminate()
        for p in processes: p.wait()

def execute(a):
    state = ROOT/"local"; lock = json.loads((state/"setup.json").read_text())
    if lock["commit"] != COMMIT or lock["options"] != OPTIONS: raise ValueError("Setup pin/options mismatch")
    worker = state/"build/transcription-worker"; model = state/lock["models"][a.model]["file"]
    for path, expected in [(worker, lock["worker_sha256"]), (model, lock["models"][a.model]["sha256"]),
                           (ROOT/"worker.cpp", lock["worker_source_sha256"]),
                           (ROOT/"CMakeLists.txt", lock["cmake_source_sha256"])]:
        if sha(path) != expected: raise ValueError("Setup checksum mismatch; rerun explicit setup")
    source = state/"whisper.cpp"
    if capture("git", "-C", str(source), "rev-parse", "HEAD") != COMMIT or capture(
            "git", "-C", str(source), "status", "--porcelain", "--untracked-files=no") != "":
        raise ValueError("Upstream source pin/cleanliness mismatch")
    manifest_path = Path(a.manifest).resolve()
    cases = validate_manifest(json.loads(manifest_path.read_text()), manifest_path.parent)
    before = hardware()
    if a.confirm_uno_q:
        if before["os"] != "Linux" or before["architecture"] not in ("aarch64", "arm64"):
            raise ValueError("UNO Q run requires Linux arm64 plus physical device verification")
        before.update(target_status="RUN (operator-confirmed UNO Q)", target_identity="operator-confirmed; inspect recorded board/CPU/RAM")
    result = {"schema_version": 1, "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "target_status": before["target_status"], "hardware_before": before, "setup": lock,
              "runtime": {"model": a.model, "threads": a.threads, "runs": a.runs,
                          "language": "en", "greedy_best_of": 1, "temperature": 0,
                          "temperature_inc": 0, "no_context": True, "use_gpu": False,
                          "vad": False, "ffmpeg_version": capture("ffmpeg", "-version"),
                          "load_kind": a.load_kind, "synthetic_load_workers": a.synthetic_load_workers,
                          "application_input_responsiveness": "NOT MEASURED"},
              "cases": [], "recommendation": "not yet established"}
    with tempfile.TemporaryDirectory(prefix="pcm-", dir=state) as temp, synthetic_load(a.synthetic_load_workers):
        for i, c in enumerate(cases):
            c["pcm"] = Path(temp)/f"{i}.f32"
            c["duration_s"] = normalize(c["source"], c["pcm"])
            if "speech_end_s" in c and not 0 <= c["speech_end_s"] <= c["duration_s"]:
                raise ValueError("speech_end_s outside fixture")
        if a.mode == "files":
            for c in cases:
                cold = []; warm = []; loads = []
                for _ in range(a.runs):
                    start = time.monotonic()
                    with Worker(model, a.threads, a.timeout) as w:
                        first = score(w.infer(c["pcm"]), c)
                        first["spawn_to_final_s"] = time.monotonic()-start
                        cold.append(first); loads.append(w.load)
                        warm.append(score(w.infer(c["pcm"]), c))
                result["cases"].append({"id": c["id"], "category": c["category"],
                    "duration_s": c["duration_s"], "audio_sha256": sha(c["source"]),
                    "cold": cold, "loads": loads, "warm": warm,
                    "warm_inference_s": summary([r["inference_s"] for r in warm]),
                    "warm_request_wall_s": summary([r["request_wall_s"] for r in warm]),
                    "warm_rtf": summary([r["rtf"] for r in warm]),
                    "load_s": summary([r["load_s"] for r in loads])})
        else:
            if any(c["duration_s"] > a.max_segment_seconds for c in cases):
                raise ValueError("Replay requires presegmented audio within max-segment-seconds")
            if any(c["duration_s"] > a.buffer_seconds for c in cases):
                raise ValueError("Each segment must fit pending buffer")
            replays = []
            for _ in range(a.runs):
                with Worker(model, a.threads, a.timeout) as w:
                    score(w.infer(cases[0]["pcm"]), cases[0])  # unmeasured warm-up, model stays resident
                    item = replay(w, cases, a.buffer_seconds)
                    item["load"] = w.load; item["warmup_decodes"] = 1; replays.append(item)
            result["replays"] = replays
            result["replay_fixtures"] = [{"id": c["id"], "category": c["category"],
                                         "duration_s": c["duration_s"], "audio_sha256": sha(c["source"])} for c in cases]
    result["hardware_after"] = hardware()
    if a.confirm_uno_q:
        result["hardware_after"].update(target_status=before["target_status"], target_identity=before["target_identity"])
    out = Path(a.output).resolve(); out.mkdir(parents=True, exist_ok=True)
    (out/"metrics.json").write_text(json.dumps(result, indent=2)+"\n")
    fields = ["case_id", "phase", "repeat", "duration_s", "inference_s", "request_wall_s", "rtf", "cpu_s", "cpu_percent",
              "peak_rss_bytes", "wer", "word_errors", "reference_words", "hallucinated_on_silence", "speech_end_to_final_s"]
    with (out/"metrics.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); writer.writeheader()
        for c in result["cases"]:
            for phase in ("cold", "warm"):
                for i, r in enumerate(c[phase]): writer.writerow(dict(r, case_id=c["id"], phase=phase, repeat=i+1, duration_s=c["duration_s"]))
        for i, replay_result in enumerate(result.get("replays", [])):
            for r in replay_result["rows"]: writer.writerow(dict(r, phase="replay", repeat=i+1))
    print("Aggregate metrics written. Recommendation: not yet established.")

def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inventory", action="store_true")
    p.add_argument("--manifest")
    p.add_argument("--model", default="tiny.en", choices=["tiny.en", "base.en", "tiny.en-q5_1", "base.en-q5_1"])
    p.add_argument("--threads", type=int, default=3)
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--timeout", type=float, default=1800)
    p.add_argument("--mode", choices=["files", "replay"], default="files")
    p.add_argument("--buffer-seconds", type=float, default=20)
    p.add_argument("--max-segment-seconds", type=float, default=10)
    p.add_argument("--load-kind", choices=["idle", "synthetic", "application"], default="idle")
    p.add_argument("--synthetic-load-workers", type=int, default=0)
    p.add_argument("--confirm-uno-q", action="store_true")
    p.add_argument("--output", default=str(ROOT/"local/results"))
    a = p.parse_args()
    if a.inventory: print(json.dumps(hardware(), indent=2)); return
    if not a.manifest: p.error("--manifest is required")
    if min(a.threads, a.runs, a.timeout, a.buffer_seconds, a.max_segment_seconds) <= 0 or a.synthetic_load_workers < 0:
        p.error("Counts and time bounds must be positive")
    if (a.load_kind == "synthetic") != (a.synthetic_load_workers > 0):
        p.error("Synthetic workers require load-kind=synthetic and vice versa")
    try: execute(a)
    except Exception:
        # Dependency output and reference/audio filenames can contain private content.
        print("Benchmark failed; check setup, manifest and local fixture formats. No transcript logged.", file=sys.stderr)
        raise SystemExit(1)

if __name__ == "__main__": main()
