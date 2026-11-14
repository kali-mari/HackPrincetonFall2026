import unittest
from sherpa_bench import RATE, chunk_units, floats, timeline, vad_units

FRAME = b"\x01\x00" * 320  # 20 ms

class SherpaBenchTest(unittest.TestCase):
    def test_chunks_cover_audio_and_end_at_duration(self):
        pcm = bytes(int(0.25 * RATE) * 2)
        units = chunk_units(pcm)
        self.assertEqual(b"".join(u[1] for u in units), pcm)
        self.assertEqual([round(u[0], 3) for u in units], [0.1, 0.2, 0.25])

    def test_floats_scale(self):
        self.assertEqual(floats(b"\x00\x40\x00\xc0"), [0.5, -0.5])

    def test_vad_units_available_when_segment_closes(self):
        speech = set(range(10, 60))  # frames 10..59 voiced
        calls = iter(range(10 ** 6))
        units = vad_units(FRAME * 200, lambda frame: next(calls) in speech)
        self.assertEqual(len(units), 1)
        # last voiced frame 59 + 500 ms hangover = frame 84 closes the segment
        self.assertAlmostEqual(units[0][0], 85 * 0.02)

    def test_silence_gives_no_vad_units(self):
        self.assertEqual(vad_units(bytes(RATE * 2), lambda frame: False), [])

    def test_simulated_lag_accumulates_when_decode_is_slower_than_audio(self):
        clock = iter([0, 0, 0.3, 0.3, 0.6])  # epoch, then start/end of two 0.3 s decodes
        import sherpa_bench
        real, sherpa_bench.time.monotonic = sherpa_bench.time.monotonic, lambda: next(clock)
        try:
            costs, lags = timeline([(0.1, b""), (0.2, b"")], lambda pcm: None)
        finally:
            sherpa_bench.time.monotonic = real
        self.assertEqual([round(c, 3) for c in costs], [0.3, 0.3])
        self.assertEqual([round(x, 3) for x in lags], [0.3, 0.5])

if __name__ == "__main__":
    unittest.main()
