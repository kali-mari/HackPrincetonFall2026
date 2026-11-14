import json
import argparse
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from collections import deque
import bench

class MetricsTest(unittest.TestCase):
    def test_rtf(self):
        self.assertEqual(bench.rtf(3, 12), .25)
        for d in (0, -1):
            with self.assertRaises(ValueError): bench.rtf(1, d)

    def test_word_errors(self):
        self.assertEqual(bench.wer("one two three", "one four three five"),
                         {"word_errors": 2, "reference_words": 3, "wer": 2/3})
        self.assertEqual(bench.wer("one two", "one")["word_errors"], 1)
        self.assertEqual(bench.wer("", "hallucination")["word_errors"], 1)
        self.assertIsNone(bench.wer("", "hallucination")["wer"])
        self.assertEqual(bench.wer("", "")["word_errors"], 0)

    def test_normalization(self):
        self.assertEqual(bench.words("Ｈｅｌｌｏ, WORLD! 42. Don't"), ["hello", "world", "42", "don", "t"])
        self.assertEqual(bench.wer("Hello, WORLD!", "hello world")["wer"], 0)

    def test_tail_and_count(self):
        self.assertEqual(bench.summary([5, 1, 4, 2, 3]), {"n": 5, "median": 3, "p95": 5, "max": 5})
        self.assertEqual(bench.percentile(list(range(1, 101))), 95)
        self.assertIsNone(bench.summary([])["median"])

    def test_no_transcript_in_metrics_and_silence(self):
        result = bench.score({"text": "PRIVATE decoded words", "inference_s": 2, "cpu_s": 3},
                             {"duration_s": 4, "silence": True, "reference": ""})
        self.assertNotIn("text", result)
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertTrue(result["hallucinated_on_silence"])
        self.assertEqual(result["cpu_percent"], 150)
        self.assertEqual(result["rtf"], .5)
        self.assertIsNone(result["wer"])

    def test_drop_oldest_and_capacity(self):
        q = deque([0, 1])
        self.assertEqual(bench.admit(q, 2, [1, 1, 1], 2), [0])
        self.assertEqual(list(q), [1, 2])
        q = deque()
        for i in range(3): self.assertEqual(bench.admit(q, i, [.1]*3, .3), [])

    def test_replay_real_time_arrivals_overload(self):
        class Clock:
            now = 0
            def monotonic(self): return self.now
            def sleep(self, seconds): self.now += seconds
        clock = Clock()
        class FakeWorker:
            def infer(self, path):
                clock.now += 4
                return {"text": "hello", "inference_s": 4, "request_wall_s": 4, "cpu_s": 2}
        cases = [{"id": str(i), "duration_s": 1, "speech_end_s": .75, "pcm": "unused"} for i in range(8)]
        with patch.object(bench.time, "monotonic", clock.monotonic), patch.object(bench.time, "sleep", clock.sleep):
            result = bench.replay(FakeWorker(), cases, 2)
        self.assertEqual(result["dropped_segments"], 4)
        self.assertEqual(result["dropped_audio_s"], 4)
        self.assertLessEqual(result["max_pending_audio_s"], 2)
        self.assertEqual(result["rows"][0]["speech_end_to_final_s"], 4.25)
        self.assertEqual(result["final_latency_s"]["n"], 4)
        self.assertNotIn('"text"', json.dumps(result))

    def test_worker_persistent_protocol(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); build = root/"local/build"; build.mkdir(parents=True)
            executable = build/"transcription-worker"
            executable.write_text('#!/usr/bin/env python3\nimport json,sys\n'
                'print(json.dumps({"load_s": .1}), flush=True)\n'
                'for line in sys.stdin:\n'
                ' print(json.dumps({"text": "private", "inference_s": .2}), flush=True)\n')
            executable.chmod(0o700)
            with patch.object(bench, "ROOT", root):
                with bench.Worker("unused", 2, 5) as w:
                    pid = w.p.pid
                    self.assertEqual(w.infer("first")["text"], "private")
                    self.assertEqual(w.infer("second")["inference_s"], .2)
                    self.assertEqual(w.p.pid, pid)
                self.assertIsNotNone(w.p.returncode)

    def test_file_export_without_private_content(self):
        class FakeWorker:
            load = {"load_s": .1, "startup_to_ready_s": .2}
            def __init__(self, *args): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def infer(self, path):
                return {"text": "SECRET transcript", "inference_s": .5, "request_wall_s": .6,
                        "cpu_s": .8, "peak_rss_bytes": 12345}
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); state = root/"local"; state.mkdir()
            for name in ("worker.cpp", "CMakeLists.txt"): (root/name).write_text("stub")
            (state/"build").mkdir(); (state/"build/transcription-worker").write_text("stub")
            (state/"model.bin").write_text("stub")
            checksum = bench.sha(state/"model.bin")
            lock = {"commit": bench.COMMIT, "options": bench.OPTIONS,
                    "worker_sha256": checksum, "worker_source_sha256": checksum,
                    "cmake_source_sha256": checksum,
                    "models": {"tiny.en": {"file": "model.bin", "sha256": checksum}}}
            (state/"setup.json").write_text(json.dumps(lock))
            (state/"private.wav").touch()
            (state/"private.txt").write_text("SECRET transcript")
            manifest = state/"files.json"
            manifest.write_text(json.dumps([{"id": "c01", "category": "short", "audio": "private.wav",
                                             "reference_file": "private.txt"}]))
            a = argparse.Namespace(model="tiny.en", manifest=str(manifest), confirm_uno_q=False,
                threads=2, runs=2, timeout=5, load_kind="idle", synthetic_load_workers=0,
                mode="files", output=str(state/"results"))
            def fake_capture(*args): return bench.COMMIT if "rev-parse" in args else ""
            with patch.object(bench, "ROOT", root), patch.object(bench, "Worker", FakeWorker), \
                 patch.object(bench, "hardware", return_value={"target_status": "NOT RUN"}), \
                 patch.object(bench, "capture", fake_capture), \
                 patch.object(bench, "normalize", return_value=2):
                bench.execute(a)
            metrics = (state/"results/metrics.json").read_text()
            exported = (state/"results/metrics.csv").read_text()
            self.assertNotIn("SECRET", metrics+exported)
            self.assertNotIn("private.txt", metrics+exported)
            parsed = json.loads(metrics)
            self.assertEqual(parsed["cases"][0]["warm_inference_s"]["n"], 2)
            self.assertEqual(parsed["cases"][0]["warm_rtf"]["median"], .25)
            self.assertEqual(len(exported.splitlines()), 5)

    def test_manifest_rejects_implicit_silence(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d); (path/"a.wav").touch()
            with self.assertRaises(ValueError):
                bench.validate_manifest([{"id": "c01", "category": "silence", "audio": "a.wav"}], path)

if __name__ == "__main__": unittest.main()
