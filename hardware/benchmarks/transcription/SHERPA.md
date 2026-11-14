# Lighter CPU models through sherpa-onnx (Zipformer and Moonshine)

Outcome: **both models run on the UNO Q on one CPU thread at about a third of one
core, with about 91% word accuracy on the 5-minute session.** whisper.cpp tiny.en
needed three threads for similar accuracy. The GPU stays unused (see
`GPU_OFFDEVICE.md` and `GPU_NEWBACKEND.md`); these results remove the reason for
needing it. The backend uses Moonshine (`backend/aac/transcription.py`).

## What ran

Actual UNO Q 4GB over USB ADB, Debian 13, Python 3.13.5, CPU only, one thread.
sherpa-onnx 2.0.1 (ONNX Runtime). Nothing was installed system-wide: the two ARM64
wheels were downloaded on the Mac and unpacked into ignored `local/sherpa/python`.

| Engine | Model | How it is fed |
|---|---|---|
| `zipformer` | streaming Zipformer transducer EN 20M, int8 encoder/joiner (2023-02-17) | 100 ms chunks as audio arrives, greedy search |
| `moonshine` | Moonshine tiny EN, int8 | the WebRTC VAD segments from experiment 2 (mode 2, 10 s maximum) |

Same fixtures, reference normalization and WER code as experiment 2. Three repeats
on short clips, two on the 5-minute session, after one excluded warm-up. No
microphone. Transcripts are not saved. Checksums for wheels and model files are in
ignored `local/sherpa/setup.json`.

## Results

| Case | Metric | Zipformer | Moonshine + VAD |
|---|---|---:|---:|
| `natural_long` (291 s) | Word errors | 80/889 = 9.0% | 83/889 = 9.3% |
| | Decode RTF | 0.35 | 0.39 |
| | Average cores busy at real-time pace | 0.35 | 0.38 |
| | Lag, median / p95 / max | 0.01 / 0.11 / 0.14 s | 3.9 / 4.4 / 4.4 s |
| | Peak process memory | 140 MiB | 312 MiB |
| `read_short` (5.9 s) | Word errors | 2/17 | 1/17 |
| | Decode RTF | 0.36 | 0.32 |
| | Lag | 0.11 s | 1.9 s |
| `reply_short` (2.3 s) | Word errors | 1/2 | 1/2 |
| | Lag | 0.11 s | 0.5 s |
| 30 s digital silence | Words produced | 0 (3/3 runs) | 0 (3/3 runs) |
| Model load | | 4.5 s | 5.2 s |

For comparison, experiment 2's best whisper.cpp setup (q5_1, three threads, VAD)
had 10.1% errors on the same session, a median 8.3 s delay and about three cores busy.

Reading the numbers:

- **Lag** is the time from a unit's audio ending to its decode finishing. For
  Zipformer the unit is a 100 ms chunk, so it does not include the model's own
  look-ahead before a word is emitted. For Moonshine the unit is a VAD segment, so
  it starts when the segment closes (after the 500 ms hangover) and grows with
  segment length: 31 segments covered the session, most near the 10 s maximum.
- **Timeline** is simulated from measured decode times by default. One Zipformer
  run of the session fed at real-time pace (`--realtime`) agreed: RTF 0.37, p95 lag
  0.12 s, the same 80 errors.
- **Moonshine without VAD** also produced no text on silence, but decoding 30 s of
  it took 10 s and 491 MiB. Keep the VAD in front.
- Zipformer dropped the first two words of `read_short`. Its output is upper case
  without punctuation; Moonshine's is cased and punctuated.
- Both miss the same word in `reply_short`, a proper name. Two words is not a
  measurement of short-reply accuracy.

## Not measured

Real microphone and room noise, child speech, transcription running beside Django
and the frontend, and more than one thread. All audio was clean read speech.

## Backend check

The backend was installed on the board in a venv, and `manage.py transcribe_file`
(the `moonshine` loader in `backend/aac/transcription.py`) returned the correct
`read_short` text: 5.9 s of audio in 2.08 s. The server was not run there. Board
setup is described in `docs/transcription-handoff.md`.

## Reproduce

On the online Mac, from this folder:

```sh
python3 setup_sherpa.py     # wheels + both models into local/sherpa/ (about 180 MB)
adb push local/sherpa/wheels local/sherpa/models local/sherpa/setup.json \
  /home/arduino/hardware/benchmarks/transcription/local/sherpa/
adb push sherpa_bench.py test_sherpa.py /home/arduino/hardware/benchmarks/transcription/
```

On the board, with new output names for each attempt:

```sh
python3 -m unittest test_sherpa
python3 sherpa_bench.py --engine zipformer --case natural_long --runs 2 --output local/sherpa/results/zipformer-new
python3 sherpa_bench.py --engine moonshine --case natural_long --runs 2 --output local/sherpa/results/moonshine-new
python3 sherpa_bench.py --engine moonshine --policy file --case silence --output local/sherpa/results/moonshine-silence-new
```

`--threads`, `--realtime` and `--show-text` (terminal only) are optional. Each run
writes `metrics.json` to its output folder.
