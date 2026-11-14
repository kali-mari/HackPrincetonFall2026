#!/usr/bin/env python3
"""Generate local deterministic variants only from the explicitly approved fixtures."""
import array,hashlib,json,math,random,subprocess,sys,tempfile,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parent
STATE=ROOT/'local/experiment2'
def main():
    cases=json.loads((STATE/'fixtures.json').read_text());out=STATE/'derived';out.mkdir(exist_ok=True)
    provenance=[];mapping={x['id']:x for x in cases}
    def save(name,pcm):
        path=out/(name+'.wav')
        if path.exists():raise RuntimeError('Derived fixture already exists; preserve it')
        with wave.open(str(path),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(pcm)
        return 'derived/'+path.name
    def ref(case):return (STATE/case['reference_file']).read_text()
    with tempfile.TemporaryDirectory(prefix='derive-',dir=STATE) as temp:
        audio={}
        for case in cases:
            normalized=Path(temp)/(case['id']+'.wav')
            subprocess.run(['ffmpeg','-nostdin','-v','error','-protocol_whitelist','file,pipe','-i',str(STATE/case['audio']),'-ac','1','-ar','16000','-c:a','pcm_s16le','-y',str(normalized)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            with wave.open(str(normalized),'rb') as f:audio[case['id']]=f.readframes(f.getnframes())
        read=audio['read_short'];reply=audio['reply_short'];natural=audio['natural_long']
        # Keep original natural speech once, then append only known digital silence.
        duration=len(natural)/32000
        if duration>300:raise RuntimeError('Selected natural source exceeds five minutes; require aligned excerpt references')
        cases.append(dict(id='natural_300',audio=save('natural_300',natural+bytes(300*32000-len(natural))),reference_file=mapping['natural_long']['reference_file'],category='continuous',speech_boundaries=None,known_silence_intervals=[[duration,300]],variant='unaltered natural recording + zero padding to exactly 300 s'))
        x=array.array('h');x.frombytes(read)
        if sys.byteorder!='little':x.byteswap()
        quiet=array.array('h',(round(v*.1) for v in x))
        if sys.byteorder!='little':quiet.byteswap()
        cases.append(dict(id='quiet',audio=save('quiet',quiet.tobytes()),reference_file=mapping['read_short']['reference_file'],category='quiet',speech_boundaries=None,variant='read_short attenuated 20 dB; no noise'))
        pause=2.0;combo=read+bytes(int(pause*32000))+reply
        refpath=out/'pauses.txt';refpath.write_text(ref(mapping['read_short']).strip()+' '+ref(mapping['reply_short']).strip()+'\n')
        cases.append(dict(id='pauses_ref',audio=save('pauses_ref',combo),reference_file='derived/pauses.txt',category='pauses',speech_boundaries=None,known_silence_intervals=[[len(read)/32000,len(read)/32000+pause]],variant='two independent reference utterances with exactly 2 s inserted silence'))
        empty=out/'empty.txt';empty.write_text('')
        cases.append(dict(id='silence',audio=save('silence',bytes(11*32000)),reference_file='derived/empty.txt',category='silence',non_speech=True,speech_boundaries=[],annotation_kind='exact synthetic digital silence'))
        rng=random.Random(20261114);rms=math.sqrt(sum(v*v for v in x)/len(x))/math.sqrt(10)
        noise=array.array('h',(max(-32768,min(32767,round(rng.gauss(0,rms)))) for _ in range(11*16000)))
        if sys.byteorder!='little':noise.byteswap()
        cases.append(dict(id='noise_only',audio=save('noise_only',noise.tobytes()),reference_file='derived/empty.txt',category='synthetic_noise',non_speech=True,speech_boundaries=[],annotation_kind='exact synthetic non-speech white Gaussian noise',variant='seed 20261114; RMS based on read_short / sqrt(10); not room noise'))
        cases.append(dict(id='jfk',audio='../fixtures/jfk.wav',category='short',speech_boundaries=None))
    (STATE/'all-fixtures.json').write_text(json.dumps(cases,indent=2)+'\n')
    for case in cases:
        path=STATE/case['audio'];provenance.append(dict(id=case['id'],sha256=hashlib.sha256(path.read_bytes()).hexdigest(),variant=case.get('variant')))
    (STATE/'derived-provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print('Prepared local fixture IDs:',[x['id'] for x in cases])
def append_noisy():
    cases=json.loads((STATE/'all-fixtures.json').read_text())
    if any(x['id']=='noisy_ref' for x in cases):return
    case=next(x for x in cases if x['id']=='read_short')
    with tempfile.TemporaryDirectory(prefix='noisy-',dir=STATE) as temp:
        wav=Path(temp)/'n.wav'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-protocol_whitelist','file,pipe','-i',str(STATE/case['audio']),'-ac','1','-ar','16000','-c:a','pcm_s16le','-y',str(wav)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        with wave.open(str(wav),'rb') as f:data=f.readframes(f.getnframes())
    x=array.array('h');x.frombytes(data)
    if sys.byteorder!='little':x.byteswap()
    rng=random.Random(20261114);rms=math.sqrt(sum(v*v for v in x)/len(x))/math.sqrt(10)
    mixed=[round(v+rng.gauss(0,rms)) for v in x]
    clipped=sum(v<-32768 or v>32767 for v in mixed)
    pcm=array.array('h',(max(-32768,min(32767,v)) for v in mixed))
    if sys.byteorder!='little':pcm.byteswap()
    out=STATE/'derived/noisy_ref.wav'
    with wave.open(str(out),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(pcm.tobytes())
    cases.append(dict(id='noisy_ref',audio='derived/noisy_ref.wav',reference_file=case['reference_file'],category='synthetic_noisy_speech',speech_boundaries=None,variant='read_short plus Gaussian white noise, 10 dB SNR before clipping, seed 20261114',clipped_samples=clipped))
    (STATE/'all-fixtures.json').write_text(json.dumps(cases,indent=2)+'\n')
    print('Added deterministic reference-aligned synthetic noisy speech; clipped samples:',clipped)
if __name__=='__main__':
    main()
    append_noisy()
