#!/usr/bin/env python3
"""Experiment 2: local resident-model comparisons and bounded VAD-paced replay.
Public/user-approved files only. No microphone, API writes or transcript exports.
"""
import argparse,array,csv,datetime,fcntl,hashlib,json,math,os,resource,selectors,subprocess,sys,tempfile,threading,time,wave,zipfile
from collections import deque
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from bench import Worker,hardware,summary,wer,words
from setup_local import sha,COMMIT
from vad_segments import Policy,Segmenter,AudioQueue,coverage_metrics,interval_overlap
ROOT=Path(__file__).resolve().parent
STATE=ROOT/'local/experiment2'

@contextmanager
def session_lock():
    STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (STATE/'benchmark.lock').open('a+') as f:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Another experiment session holds the lock')
        # Old runner does not cooperate with this lock, so reject its live workers too.
        for p in Path('/proc').iterdir():
            if not p.name.isdigit() or int(p.name)==os.getpid():continue
            try:args=(p/'cmdline').read_bytes().split(b'\0')
            except OSError:continue
            if args and Path(os.fsdecode(args[0])).name in ('glslc','cc1','cc1plus'):
                raise RuntimeError('Compiler/shader work is active; finish setup before measuring')
            if args and (Path(os.fsdecode(args[0])).name in ('transcription-worker','transcription-worker2')):
                raise RuntimeError('A transcription worker is already running')
        try:yield
        finally:fcntl.flock(f,fcntl.LOCK_UN)

def clock_state():
    def get(cmd):return subprocess.run(cmd,capture_output=True,text=True).stdout.strip()
    record={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'sync_status':get(['timedatectl','show','-p','NTPSynchronized','-p','NTP','-p','Timezone']),
            'method':'manual correction from verified host; automatic synchronization not established'}
    p=STATE/'clock-current.json'
    if not p.exists():p=STATE/'clock-refined.json'
    if p.exists():
        c=json.loads(p.read_text());record.update(last_verification=c.get('after'),utc_reliable_at_correction=c.get('utc_reliable_after'),reference_sources=[x['source'] for x in c.get('reference_checks',[])])
    else:record.update(utc_reliable_at_correction=False,method='UNVERIFIED')
    return record

def normal_wav(source,dest):
    if not source.is_file():raise ValueError('Missing local fixture')
    subprocess.run(['ffmpeg','-nostdin','-v','error','-protocol_whitelist','file,pipe','-i',str(source),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le','-y',str(dest)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    with wave.open(str(dest),'rb') as f:return f.getnframes()/16000

def load_vad():
    m=json.loads((STATE/'models-vad.json').read_text())['vad'];wheel=STATE/m['wheel']
    if sha(wheel)!=m['sha256']:raise ValueError('VAD wheel checksum mismatch')
    dest=STATE/'python';dest.mkdir(exist_ok=True)
    with zipfile.ZipFile(wheel) as z:
        for name in z.namelist():
            if not (dest/name).resolve().is_relative_to(dest.resolve()):raise ValueError('Invalid wheel member')
        z.extractall(dest)
    sys.path.insert(0,str(dest));import webrtcvad
    return webrtcvad,m

class ExperimentWorker(Worker):
    def __init__(self,model,threads,timeout,backend):
        self.timeout=timeout;self.started=time.monotonic();self.log=tempfile.TemporaryFile(mode='w+t')
        binary=ROOT/'local/build/transcription-worker' if backend=='original-cpu' else STATE/'build-vulkan/transcription-worker2'
        args=[str(binary),str(model),str(threads)]
        if backend!='original-cpu':args+=['vulkan' if backend=='vulkan' else 'cpu']
        env=os.environ.copy()
        if backend!='original-cpu':env['VK_ICD_FILENAMES']='/usr/share/vulkan/icd.d/freedreno_icd.json'
        self.p=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True,bufsize=1,env=env)
        self.selector=selectors.DefaultSelector();self.selector.register(self.p.stdout,selectors.EVENT_READ)
        self.diagnostics=[]
        try:
            self.load=self.read();self.load['startup_to_ready_s']=time.monotonic()-self.started
        except BaseException:
            self.close()
            (STATE/'last-worker-startup-failure.json').write_text(json.dumps({'backend':backend,'diagnostics':self.diagnostics},indent=2))
            raise
    def close(self):
        super().close()
        if not self.log.closed:
            self.log.seek(0)
            # Only backend diagnostics are allowed in aggregate metadata.
            self.diagnostics=[x.strip() for x in self.log.read().splitlines() if any(k in x for k in ['ggml_vulkan:','BENCH_BACKENDS:','whisper_backend_init_gpu:','compute buffer','Vulkan0 total size'])][:200]
            self.log.close()

def raw_float(pcm,path):
    x=array.array('h');x.frombytes(pcm)
    if sys.byteorder!='little':x.byteswap()
    f=array.array('f',(v/32768 for v in x))
    if sys.byteorder!='little':f.byteswap()
    path.write_bytes(f.tobytes())

def frame_segments(wav,policy,kind,detector,stats,stop=None,epoch=None,limit_s=None,truth=None,known_silence=None):
    """Generator holds pre-roll + one bounded active segment; no transcript access."""
    segmenter=Segmenter(policy);n=0;fixed=[];frame_samples=16000*policy.frame_ms//1000
    stats.update(vad_cpu_s=0.,vad_wall_s=0.,positive_frames=0,total_frames=0,source_input_s=0.,producer_lateness_s=[],emitted_intervals_s=[],known_non_speech_frames=0,false_positive_frames_in_known_non_speech=0,annotated_speech_frames=0,false_negative_frames_in_annotated_speech=0)
    with wave.open(str(wav),'rb') as f:
        remaining=min(f.getnframes(),int(limit_s*16000)) if limit_s is not None else f.getnframes()
        if kind=='file':
            data=f.readframes(remaining)
            if data:yield dict(start_frame=0,end_frame=math.ceil(remaining/frame_samples),duration_ms=remaining/16,pcm=data,reason='whole_file',last_vad_voiced_end_frame=None)
            stats['source_input_s']=remaining/16000;return
        while remaining>0 and not (stop and stop.is_set()):
            take=min(frame_samples,remaining);pcm=f.readframes(take);remaining-=take
            if not pcm:break
            stats['source_input_s']+=take/16000
            if len(pcm)<frame_samples*2:pcm+=bytes(frame_samples*2-len(pcm))
            if epoch is not None:
                until=epoch+stats['source_input_s']
                if stop.wait(max(0,until-time.monotonic())):break
                stats['producer_lateness_s'].append(max(0,time.monotonic()-until))
            if kind=='vad':
                t=time.monotonic();c=time.thread_time();voiced=detector.is_speech(pcm,16000)
                stats['vad_cpu_s']+=time.thread_time()-c;stats['vad_wall_s']+=time.monotonic()-t
                stats['positive_frames']+=bool(voiced);stats['total_frames']+=1
                window=(n*policy.frame_ms/1000,(n+1)*policy.frame_ms/1000)
                nonspeech=(truth==[]) or any(a<=window[0] and b>=window[1] for a,b in (known_silence or []))
                annotated=truth is not None and any(interval_overlap(window,t)>0 for t in truth)
                stats['known_non_speech_frames']+=int(nonspeech)
                stats['false_positive_frames_in_known_non_speech']+=int(nonspeech and voiced)
                stats['annotated_speech_frames']+=int(annotated)
                stats['false_negative_frames_in_annotated_speech']+=int(annotated and not voiced)
                emitted=segmenter.feed(pcm,voiced)
            else:
                fixed.append(pcm);emitted=[]
                if len(fixed)*policy.frame_ms>=policy.max_segment_ms:
                    emitted=[dict(start_frame=n+1-len(fixed),end_frame=n+1,duration_ms=len(fixed)*policy.frame_ms,pcm=b''.join(fixed),reason='fixed_boundary',last_vad_voiced_end_frame=None)];fixed=[]
            n+=1
            for item in emitted:yield item
        if kind=='vad':
            stats['rejected_short_activations']=segmenter.rejected
            yield from segmenter.flush()
        elif fixed:yield dict(start_frame=n-len(fixed),end_frame=n,duration_ms=len(fixed)*policy.frame_ms,pcm=b''.join(fixed),reason='end_of_input',last_vad_voiced_end_frame=None)

def sample_drm(pid):
    counters={}
    for p in (Path('/proc')/str(pid)/'fdinfo').glob('*'):
        try:lines=p.read_text().splitlines()
        except OSError:continue
        for line in lines:
            if line.startswith(('drm-engine-','drm-cycles-','drm-total-cycles-')) and ':' in line:
                k,v=line.split(':',1)
                try:counters[p.name+':'+k]=int(v.strip().split()[0])
                except ValueError:pass
    return counters

def monitor(stop,worker,trace,queue=None,epoch=None):
    while not stop.is_set():
        entry={'elapsed_s':time.monotonic()-epoch if epoch else 0,'drm_counters':sample_drm(worker.p.pid)}
        for key,path in [('temperature_millidegrees_c','/sys/class/thermal/thermal_zone0/temp'),('cpu0_frequency_khz','/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq'),('gpu_frequency_hz','/sys/class/devfreq/5900000.gpu/cur_freq')]:
            try:entry[key]=int(Path(path).read_text())
            except (OSError,ValueError):entry[key]=None
        try:
            memory={k:int(v.split()[0])*1024 for k,v in (line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines()) if k in ('MemAvailable','SwapFree')}
            entry.update(memory)
        except OSError:pass
        if queue is not None:
            with queue.condition:entry.update(pending_audio_s=queue.pending_ms/1000,dropped_segments=len(queue.dropped))
        trace.append(entry);stop.wait(.25)

def run_once(worker,wav,case,policy,kind,vad_module,mode,temp,limit_s,stale_s,vad_mode=2):
    stopped=threading.Event();done=threading.Event();stats={};rows=[];texts=[];segments=[];trace=[];errors=[]
    epoch=time.monotonic();wall_offset=time.time()-epoch;cpu0=time.process_time()
    detector=vad_module.Vad(vad_mode) if kind=='vad' else None
    queue=AudioQueue(policy.queue_ms) if mode=='replay' else None
    def produce():
        try:
            for item in frame_segments(wav,policy,kind,detector,stats,stopped,epoch if mode=='replay' else None,limit_s,case.get('speech_boundaries'),case.get('known_silence_intervals')):
                stats['emitted_intervals_s'].append([item['start_frame']*policy.frame_ms/1000,item['end_frame']*policy.frame_ms/1000])
                item['available_s']=time.monotonic()-epoch
                queue.put(item)
        except BaseException as e:errors.append(type(e).__name__)
        finally:queue.close()
    producer=threading.Thread(target=produce,daemon=True) if queue else None
    sampling=threading.Thread(target=monitor,args=(done,worker,trace,queue,epoch),daemon=True);sampling.start()
    if producer:producer.start()
    iterator=None if queue else iter(frame_segments(wav,policy,kind,detector,stats,stopped,None,limit_s,case.get('speech_boundaries'),case.get('known_silence_intervals')))
    try:
        while not stopped.is_set():
            item=queue.get() if queue else next(iterator,None)
            if item is None:break
            if not queue:
                item['available_s']=time.monotonic()-epoch
                stats['emitted_intervals_s'].append([item['start_frame']*policy.frame_ms/1000,item['end_frame']*policy.frame_ms/1000])
            available=item['available_s'];start=time.monotonic()-epoch
            info={k:v for k,v in item.items() if k!='pcm'}
            info.update(start_s=item['start_frame']*policy.frame_ms/1000,end_s=min(item['end_frame']*policy.frame_ms/1000,case['duration_s']))
            segments.append([info['start_s'],info['end_s']])
            if queue and start-available>stale_s:
                queue.dropped.append(dict(start_frame=item['start_frame'],end_frame=item['end_frame'],duration_ms=item['duration_ms'],reason='stale_pending'))
                continue
            raw=Path(temp)/'active.f32';raw_float(item.pop('pcm'),raw)
            before=sample_drm(worker.p.pid)
            try:result=worker.infer(raw)
            finally:raw.unlink(missing_ok=True)
            after=sample_drm(worker.p.pid);final=time.monotonic()-epoch;text=result.pop('text')
            stale=bool(queue and final-available>stale_s)
            if not stale and not stopped.is_set():texts.append(text)
            # Non-speech fixture references are legitimately empty; no text content leaves RAM.
            info.update(result,decoded_words=len(words(text)),nonblank=bool(text.strip()),stale_output_discarded=stale,
                        decode_start_s=start,final_s=final,wait_s=start-available,available_to_final_s=final-available,
                        rtf=result['inference_s']/(item['duration_ms']/1000),
                        cpu_percent=result['cpu_s']/result['inference_s']*100,
                        drm_counter_deltas={k:after[k]-v for k,v in before.items() if k in after})
            last=item['last_vad_voiced_end_frame']
            info['vad_estimated_end_to_final_s']=final-last*policy.frame_ms/1000 if queue and last is not None else None
            rows.append(info);text=None
        if errors:raise RuntimeError('Producer failed: '+errors[0])
    finally:
        stopped.set()
        if queue:queue.close(discard=True)
        if producer:producer.join(timeout=3)
        done.set();sampling.join(timeout=2)
    elapsed=time.monotonic()-epoch
    stats['producer_lateness_s']=summary(stats['producer_lateness_s'])
    stats['detector_evaluated']=kind=='vad'
    stats['false_positive_frame_rate_known_non_speech']=stats['false_positive_frames_in_known_non_speech']/stats['known_non_speech_frames'] if kind=='vad' and stats['known_non_speech_frames'] else None
    stats['false_negative_frame_rate_annotated_speech']=stats['false_negative_frames_in_annotated_speech']/stats['annotated_speech_frames'] if kind=='vad' and stats['annotated_speech_frames'] else None
    reference=case.get('reference')
    if limit_s is not None and limit_s<case['duration_s']:reference=None
    fulltext=' '.join(texts);texts.clear()
    score=wer(reference,fulltext) if reference is not None else {'wer':None,'status':'NOT MEASURED: reference unavailable for this exact audio span'}
    nonblank=bool(fulltext.strip());fulltext=None
    truth=case.get('speech_boundaries')
    qdrops=queue.dropped if queue else []
    unique_input=stats['source_input_s']
    report=dict(audio_s=unique_input,elapsed_s=elapsed,decode_audio_s=sum(r['duration_ms'] for r in rows)/1000,
                total_decode_s=sum(r['inference_s'] for r in rows),decode_rtf_source_audio=sum(r['inference_s'] for r in rows)/unique_input,
                pipeline_rtf=elapsed/unique_input,python_cpu_s=time.process_time()-cpu0,
                worker_cpu_s=sum(r['cpu_s'] for r in rows),worker_peak_rss_bytes=max([worker.load['peak_rss_bytes']]+[r['peak_rss_bytes'] for r in rows]),
                python_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                rows=rows,source_nonblank_output=nonblank if case.get('non_speech') else None,
                accuracy=score,vad=stats,segmentation_coverage=coverage_metrics(stats['emitted_intervals_s'],truth),
                delivered_coverage=coverage_metrics([(r['start_s'],r['end_s']) for r in rows if not r['stale_output_discarded']],truth),
                dropped_segments=len(qdrops),dropped_audio_s=sum(x['duration_ms'] for x in qdrops)/1000,drops=qdrops,
                max_pending_audio_s=queue.maximum_ms/1000 if queue else None,
                final_drain_s=max(0,elapsed-unique_input) if queue else None,
                available_to_final_s=summary([r['available_to_final_s'] for r in rows]),
                speech_end_to_final_s={'status':'NOT MEASURED: no independent speech-end annotations'},
                vad_estimated_end_to_final_s=summary([r['vad_estimated_end_to_final_s'] for r in rows if r['vad_estimated_end_to_final_s'] is not None]),
                wall_clock_step_s=(time.time()-time.monotonic())-wall_offset,monitor_trace=trace)
    if queue and truth is not None:
        latencies=[];missing=0
        for interval in truth:
            delivered=[r for r in rows if not r['stale_output_discarded'] and interval_overlap((r['start_s'],r['end_s']),interval)>0]
            covered=sum(interval_overlap((r['start_s'],r['end_s']),interval) for r in delivered)
            if covered+1e-6 < interval[1]-interval[0]:missing+=1
            elif delivered:latencies.append(max(r['final_s'] for r in delivered)-interval[1])
        report['speech_end_to_final_s']=dict(summary(latencies),missing_or_trimmed_reference_intervals=missing,annotation_kind=case.get('annotation_kind','supplied independent intervals'))
    # Source denominator is unique source duration, not summed overlapping windows.
    if report['decode_audio_s']>unique_input+policy.frame_ms/1000+1e-6:raise RuntimeError('Audio overlap accounting violation')
    report['utc_end']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    return report

def main():
    os.umask(0o077)
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',required=True);p.add_argument('--case',required=True)
    p.add_argument('--model',choices=['tiny.en','tiny.en-q5_1'],default='tiny.en')
    p.add_argument('--threads',type=int,choices=[1,2,3],default=3)
    p.add_argument('--backend',choices=['original-cpu','matched-cpu','vulkan'],default='original-cpu')
    p.add_argument('--policy',choices=['file','fixed','vad'],default='vad')
    p.add_argument('--mode',choices=['offline','replay'],default='offline')
    p.add_argument('--vad-mode',type=int,choices=[0,1,2,3],default=2)
    p.add_argument('--runs',type=int,default=3);p.add_argument('--limit-s',type=float)
    p.add_argument('--max-segment-ms',type=int,default=10000);p.add_argument('--queue-ms',type=int,default=20000)
    p.add_argument('--stale-s',type=float,default=30);p.add_argument('--output',required=True)
    a=p.parse_args()
    import platform
    if sys.platform!='linux' or platform.machine() not in ('aarch64','arm64'):p.error('Target execution requires the actual Linux arm64 UNO Q; laptop runs are not target evidence')
    if a.runs<1 or a.stale_s<=0 or (a.limit_s is not None and a.limit_s<=0):p.error('Invalid run/time bounds')
    if a.mode=='replay' and a.policy=='file':p.error('Replay requires bounded fixed or VAD segments')
    out=Path(a.output).resolve()
    if out.exists():p.error('Output already exists; preserve previous results')
    if not out.is_relative_to(STATE.resolve()):p.error('Keep new outputs inside ignored local/experiment2')
    policy=Policy(max_segment_ms=a.max_segment_ms,queue_ms=a.queue_ms)
    with session_lock():
        lock=json.loads((ROOT/'local/setup.json').read_text())
        if lock['commit']!=COMMIT or sha(ROOT/'local/build/transcription-worker')!=lock['worker_sha256']:raise ValueError('Original build pin/checksum mismatch')
        if sha(ROOT/'worker.cpp')!=lock['worker_source_sha256']:raise ValueError('Original worker source changed')
        if subprocess.check_output(['git','-C',str(ROOT/'local/whisper.cpp'),'rev-parse','HEAD'],text=True).strip()!=COMMIT:raise ValueError('Upstream pin mismatch')
        if subprocess.check_output(['git','-C',str(ROOT/'local/whisper.cpp'),'status','--porcelain','--untracked-files=no'],text=True).strip():raise ValueError('Upstream checkout modified')
        model=ROOT/'local'/lock['models']['tiny.en']['file'];model_sha=lock['models']['tiny.en']['sha256']
        model_vad=json.loads((STATE/'models-vad.json').read_text())
        if a.model!='tiny.en':model=STATE/model_vad['quantized']['file'];model_sha=model_vad['quantized']['sha256']
        if sha(model)!=model_sha:raise ValueError('Model checksum mismatch')
        if a.backend!='original-cpu':
            g=json.loads((STATE/'gpu-build.json').read_text())
            if g.get('commit')!=COMMIT or sha(STATE/'build-vulkan/transcription-worker2')!=g.get('worker_sha256') or sha(ROOT/'native2/worker.cpp')!=g.get('worker_source_sha256'):raise ValueError('GPU build checksum mismatch')
        module,vad_provenance=load_vad()
        manifest=Path(a.manifest).resolve();case=next(x for x in json.loads(manifest.read_text()) if x['id']==a.case)
        if 'reference_file' in case:case['reference']=(manifest.parent/case['reference_file']).read_text()
        source=(manifest.parent/case['audio']).resolve()
        result=dict(schema_version=2,case_id=case['id'],target_status='RUN on operator-verified UNO Q',
                    clock_before=clock_state(),hardware_before=hardware(),configuration=vars(a),policy_settings=asdict(policy),
                    decoding={'language':'en','greedy_best_of':1,'temperature':0,'temperature_inc':0,'no_context':True,'audio_context':'upstream default','overlap_ms':0},
                    source_commit=COMMIT,model_sha256=model_sha,original_setup=lock,vad_dependency=vad_provenance,
                    audio_sha256=sha(source),reference_sha256=sha(manifest.parent/case['reference_file']) if 'reference_file' in case else None,
                    application_headroom='NOT MEASURED',input_responsiveness='NOT MEASURED',runs=[])
        result['backend_build']=g if a.backend!='original-cpu' else lock
        result['model_revision']=model_vad['quantized']['revision'] if a.model!='tiny.en' else lock['models']['tiny.en']['revision']
        result['runner_sha256']=sha(Path(__file__))
        result['segmenter_sha256']=sha(ROOT/'vad_segments.py')
        result['python_version']=sys.version
        result['boot_id']=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        with tempfile.TemporaryDirectory(prefix='session-',dir=STATE) as temp:
            wav=Path(temp)/'normalized.wav';case['duration_s']=normal_wav(source,wav)
            if a.limit_s is not None:a.limit_s=min(a.limit_s,case['duration_s'])
            with ExperimentWorker(model,a.threads,1800,a.backend) as worker:
                result['model_load']=worker.load
                # Warm up only on a segment the selected policy would decode; silence VAD calls zero decodes.
                detector=module.Vad(a.vad_mode) if a.policy=='vad' else None;warm_stats={}
                gen=frame_segments(wav,policy,a.policy,detector,warm_stats,limit_s=a.limit_s)
                first=next(gen,None);gen.close()
                if first is not None:
                    raw=Path(temp)/'warmup.f32';raw_float(first.pop('pcm'),raw)
                    try:warmup=worker.infer(raw);warmup.pop('text',None);result['first_decode_excluded_warmup']=warmup
                    finally:raw.unlink(missing_ok=True)
                else:result['first_decode_excluded_warmup']=None
                for n in range(a.runs):
                    item=run_once(worker,wav,case,policy,a.policy,module,a.mode,temp,a.limit_s,a.stale_s,a.vad_mode)
                    item['repeat']=n+1;result['runs'].append(item)
                    print(json.dumps({'case_id':a.case,'repeat':n+1,'source_rtf':item['decode_rtf_source_audio'],'segments':len(item['rows']),'drops':item['dropped_segments'],'wer':item['accuracy'].get('wer')}),flush=True)
            result['backend_diagnostics']=worker.diagnostics
        result.update(clock_after=clock_state(),hardware_after=hardware())
        result['summaries']={k:summary([r[k] for r in result['runs']]) for k in ['elapsed_s','decode_rtf_source_audio','pipeline_rtf','worker_cpu_s','worker_peak_rss_bytes']}
        result['wall_clock_stable']=all(abs(r['wall_clock_step_s'])<.5 for r in result['runs'])
        out.mkdir(parents=True)
        (out/'metrics.json').write_text(json.dumps(result,indent=2)+'\n')
        fields=['repeat','audio_s','elapsed_s','total_decode_s','decode_rtf_source_audio','pipeline_rtf','python_cpu_s','worker_cpu_s','worker_peak_rss_bytes','python_peak_rss_bytes','dropped_segments','dropped_audio_s','max_pending_audio_s','final_drain_s','source_nonblank_output','wer','word_errors','reference_words']
        with (out/'metrics.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader()
            for r in result['runs']:w.writerow(dict(r,**{k:r['accuracy'].get(k) for k in ['wer','word_errors','reference_words']}))
        print('Aggregate experiment metrics saved; no transcript content exported.',flush=True)

if __name__=='__main__':main()
