"""Pure bounded segmentation/queue logic. WebRTC VAD supplies per-frame decisions.
Segments never overlap: pre-roll is clamped to the previous consumed endpoint.
"""
from collections import deque
from dataclasses import dataclass
import threading

@dataclass(frozen=True)
class Policy:
    frame_ms: int = 20
    pre_roll_ms: int = 200
    start_window_ms: int = 100
    start_votes: int = 3
    min_speech_ms: int = 100
    hangover_ms: int = 500
    max_segment_ms: int = 10000
    queue_ms: int = 20000
    def __post_init__(self):
        if self.frame_ms not in (10,20,30):raise ValueError('WebRTC frame must be 10, 20 or 30 ms')
        for key in ['pre_roll_ms','start_window_ms','min_speech_ms','hangover_ms','max_segment_ms','queue_ms']:
            value=getattr(self,key)
            if value<=0 or value%self.frame_ms:raise ValueError('Policy bounds must be positive whole frames')
        if not 1<=self.start_votes<=self.start_window_ms//self.frame_ms:raise ValueError('Invalid speech vote threshold')
        if self.pre_roll_ms<self.start_window_ms:raise ValueError('Pre-roll must cover speech trigger window')
        if self.queue_ms<self.max_segment_ms:raise ValueError('Queue must hold at least one maximum segment')

class Segmenter:
    def __init__(self,policy):
        self.p=policy;self.index=0;self.consumed_end=0;self.active=None;self.rejected=0
        self.ring=deque(maxlen=policy.pre_roll_ms//policy.frame_ms)
        self.votes=deque(maxlen=policy.start_window_ms//policy.frame_ms)
    def feed(self,pcm,voiced):
        i=self.index;self.index+=1
        if self.active is None:
            self.ring.append((i,pcm,voiced));self.votes.append(voiced)
            if sum(self.votes)<self.p.start_votes:return []
            frames=[x for x in self.ring if x[0]>=self.consumed_end]
            self.active=frames
            self.ring.clear();self.votes.clear()
        else:self.active.append((i,pcm,voiced))
        active=self.active
        last=next((x[0] for x in reversed(active) if x[2]),None)
        if len(active)>=self.p.max_segment_ms//self.p.frame_ms:return self._finish('max_duration')
        if last is not None and i-last>=self.p.hangover_ms//self.p.frame_ms:return self._finish('hangover')
        return []
    def _finish(self,reason):
        frames=self.active;self.active=None
        self.consumed_end=frames[-1][0]+1
        self.ring.clear();self.votes.clear()
        voiced=sum(x[2] for x in frames)
        if voiced*self.p.frame_ms<self.p.min_speech_ms:
            self.rejected+=1;return []
        return [dict(start_frame=frames[0][0],end_frame=frames[-1][0]+1,
                     last_vad_voiced_end_frame=max(x[0]+1 for x in frames if x[2]),
                     reason=reason,voiced_frames=voiced,pcm=b''.join(x[1] for x in frames),
                     duration_ms=len(frames)*self.p.frame_ms)]
    def flush(self):
        return self._finish('end_of_input') if self.active else []

class AudioQueue:
    def __init__(self,budget_ms):
        if budget_ms<=0:raise ValueError('Queue budget must be positive')
        self.budget=budget_ms;self.pending=deque();self.pending_ms=0;self.maximum_ms=0
        self.dropped=[];self.closed=False;self.condition=threading.Condition()
    def put(self,item):
        with self.condition:
            if self.closed:
                self.dropped.append(dict(start_frame=item['start_frame'],end_frame=item['end_frame'],duration_ms=item['duration_ms'],reason='stopped'))
                return
            self.pending.append(item);self.pending_ms+=item['duration_ms']
            while self.pending_ms>self.budget:
                x=self.pending.popleft();self.pending_ms-=x['duration_ms']
                self.dropped.append(dict(start_frame=x['start_frame'],end_frame=x['end_frame'],duration_ms=x['duration_ms'],reason='overflow'))
            self.maximum_ms=max(self.maximum_ms,self.pending_ms);self.condition.notify()
    def get(self):
        with self.condition:
            while not self.pending and not self.closed:self.condition.wait(.1)
            if not self.pending:return None
            item=self.pending.popleft();self.pending_ms-=item['duration_ms'];return item
    def close(self,discard=False):
        with self.condition:
            if discard:
                while self.pending:
                    x=self.pending.popleft()
                    self.dropped.append(dict(start_frame=x['start_frame'],end_frame=x['end_frame'],duration_ms=x['duration_ms'],reason='stopped'))
                self.pending_ms=0
            self.closed=True;self.condition.notify_all()

def interval_overlap(a,b):return max(0,min(a[1],b[1])-max(a[0],b[0]))
def coverage_metrics(segments,truth):
    """Requires supplied independent speech intervals; never infer truth from VAD."""
    if truth is None:return {'status':'NOT MEASURED: no independent speech-boundary annotations'}
    # Caller supplies disjoint intervals, e.g. independently annotated utterance envelopes.
    for i,x in enumerate(truth):
        if x[0]>=x[1] or (i and x[0]<truth[i-1][1]):raise ValueError('Truth intervals must be sorted/disjoint')
    truth_s=sum(b-a for a,b in truth)
    covered=sum(interval_overlap(s,t) for s in segments for t in truth)
    false=sum(not any(interval_overlap(s,t)>0 for t in truth) for s in segments)
    clipped=sum(not any(a<=s and b>=e for a,b in segments) for s,e in truth)
    # An annotated interval crossing a max-duration split is still fully covered.
    def uncovered(t):return (t[1]-t[0])-sum(interval_overlap(s,t) for s in segments)
    clipped=sum(uncovered(t)>1e-8 for t in truth)
    return {'status':'annotated interval coverage; annotation granularity applies','reference_speech_s':truth_s,
            'missed_annotated_speech_s':max(0,truth_s-covered),'false_activation_segments':false,
            'clipped_reference_intervals':clipped}
