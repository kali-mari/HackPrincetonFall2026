import unittest
from vad_segments import Policy,Segmenter,AudioQueue,coverage_metrics
class SegmentationTest(unittest.TestCase):
    def test_silence_never_emits(self):
        s=Segmenter(Policy())
        self.assertFalse([y for _ in range(1000) for y in s.feed(b'\0'*640,False)]+s.flush())
    def test_pre_roll_preserves_first_frame(self):
        s=Segmenter(Policy());out=[]
        for flag in [False]*10+[True]*10+[False]*30:out+=s.feed(b'x'*640,flag)
        out+=s.flush();self.assertEqual(len(out),1)
        self.assertLessEqual(out[0]['start_frame'],10)
        self.assertGreaterEqual(out[0]['end_frame'],20)
    def test_continuous_bounded_nonoverlap(self):
        p=Policy(max_segment_ms=1000,queue_ms=2000);s=Segmenter(p);out=[]
        for _ in range(200):out+=s.feed(b'x'*640,True)
        out+=s.flush()
        self.assertEqual(sum(x['duration_ms'] for x in out),4000)
        self.assertTrue(all(x['duration_ms']<=1000 for x in out))
        self.assertTrue(all(a['end_frame']==b['start_frame'] for a,b in zip(out,out[1:])))
    def test_minimum_rejects_brief_activation(self):
        s=Segmenter(Policy());out=[]
        for flag in [True]*3+[False]*30:out+=s.feed(b'x'*640,flag)
        self.assertFalse(out);self.assertEqual(s.rejected,1)
    def test_queue_drops_oldest_and_stop_discards(self):
        q=AudioQueue(2000)
        for i in range(3):q.put(dict(start_frame=i*50,end_frame=(i+1)*50,duration_ms=1000,pcm=b'private'))
        self.assertEqual(len(q.dropped),1);self.assertEqual(q.get()['start_frame'],50)
        q.close(discard=True);self.assertIsNone(q.get());self.assertEqual(q.pending_ms,0)
        self.assertNotIn('pcm',q.dropped[0]);self.assertEqual(len(q.dropped),2)
    def test_coverage_counts_split_without_overlap(self):
        r=coverage_metrics([(0,1),(1,2)],[(.2,1.8)])
        self.assertAlmostEqual(r['missed_annotated_speech_s'],0)
        self.assertEqual(r['clipped_reference_intervals'],0)
        self.assertIn('NOT MEASURED',coverage_metrics([],None)['status'])
        self.assertEqual(coverage_metrics([(0,1)],[])['false_activation_segments'],1)
    def test_policy_rejects_bad_bounds(self):
        with self.assertRaises(ValueError):Policy(frame_ms=25)
        with self.assertRaises(ValueError):Policy(queue_ms=1000)
if __name__=='__main__':unittest.main()

class RunnerTest(unittest.TestCase):
    def test_offline_gating_and_no_text_export(self):
        import tempfile,wave,json
        from pathlib import Path
        from types import SimpleNamespace
        from vad_bench import run_once
        class FakeVad:
            def __init__(self,mode):pass
            def is_speech(self,data,rate):return any(data)
        class FakeWorker:
            p=SimpleNamespace(pid=999999999)
            load={'peak_rss_bytes':100}
            def infer(self,path):return dict(text='PRIVATE reference',inference_s=.1,cpu_s=.1,request_wall_s=.1,peak_rss_bytes=100)
        with tempfile.TemporaryDirectory() as t:
            wav=Path(t)/'silence.wav'
            with wave.open(str(wav),'wb') as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(bytes(32000))
            r=run_once(FakeWorker(),wav,dict(duration_s=1,reference='',non_speech=True,speech_boundaries=[]),Policy(),'vad',SimpleNamespace(Vad=FakeVad),'offline',t,None,30)
            self.assertEqual(r['rows'],[]);self.assertEqual(r['worker_cpu_s'],0)
            self.assertFalse(r['source_nonblank_output']);self.assertEqual(r['accuracy']['word_errors'],0)
            self.assertEqual(r['vad']['known_non_speech_frames'],50)
            self.assertNotIn('PRIVATE',json.dumps(r))
    def test_full_reference_includes_missed_speech(self):
        import tempfile,wave
        from pathlib import Path
        from types import SimpleNamespace
        from vad_bench import run_once
        class AlwaysSilent:
            def __init__(self,mode):pass
            def is_speech(self,data,rate):return False
        with tempfile.TemporaryDirectory() as t:
            wav=Path(t)/'speech.wav'
            with wave.open(str(wav),'wb') as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\1\0'*16000)
            worker=SimpleNamespace(p=SimpleNamespace(pid=99999999),load={'peak_rss_bytes':100})
            r=run_once(worker,wav,dict(duration_s=1,reference='one two',speech_boundaries=[[0,1]]),Policy(),'vad',SimpleNamespace(Vad=AlwaysSilent),'offline',t,None,30)
            self.assertEqual(r['accuracy']['wer'],1)
            self.assertEqual(r['segmentation_coverage']['missed_annotated_speech_s'],1)

    def test_clock_paced_producer_delivers_without_transcript_export(self):
        import tempfile,wave,json
        from pathlib import Path
        from types import SimpleNamespace
        from vad_bench import run_once
        class Speech:
            def __init__(self,mode):pass
            def is_speech(self,data,rate):return True
        class Worker:
            p=SimpleNamespace(pid=99999999)
            load={'peak_rss_bytes':100}
            def infer(self,path):return dict(text='one two',inference_s=.01,cpu_s=.01,request_wall_s=.01,peak_rss_bytes=100)
        with tempfile.TemporaryDirectory() as t:
            wav=Path(t)/'speech.wav'
            with wave.open(str(wav),'wb') as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\1\0'*3200)
            r=run_once(Worker(),wav,dict(duration_s=.2,reference='one two',speech_boundaries=[[0,.2]],annotation_kind='test-only exact synthetic interval'),Policy(),'vad',SimpleNamespace(Vad=Speech),'replay',t,None,30)
            self.assertEqual(r['dropped_segments'],0)
            self.assertAlmostEqual(r['audio_s'],.2)
            self.assertEqual(r['accuracy']['wer'],0)
            self.assertEqual(r['speech_end_to_final_s']['n'],1)
            self.assertNotIn('one two',json.dumps(r))
