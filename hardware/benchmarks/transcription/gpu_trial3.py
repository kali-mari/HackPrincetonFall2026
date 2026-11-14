#!/usr/bin/env python3
"""New isolated off-device-build trial; inference only on the verified UNO Q.
Reuses experiment2 metrics/queue logic without changing its source or results.
"""
import argparse,json,os,platform,selectors,subprocess,tempfile,time,datetime,csv,resource
from bench import Worker as PipeWorker
from pathlib import Path
import vad_bench as base
from setup_local import sha,COMMIT
ROOT=Path(__file__).resolve().parent
STATE=ROOT/'local/experiment3'
class Worker3(base.ExperimentWorker):
    def __init__(self,model,threads,backend,timeout=180):
        self.timeout=timeout;self.started=time.monotonic();self.log=tempfile.TemporaryFile(mode='w+t');self.diagnostics=[]
        env=os.environ.copy();env['VK_ICD_FILENAMES']='/usr/share/vulkan/icd.d/freedreno_icd.json'
        self.p=subprocess.Popen([str(STATE/'transcription-worker2'),str(model),str(threads),'vulkan' if backend=='gpu' else 'cpu'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True,bufsize=1,env=env,preexec_fn=lambda:resource.setrlimit(resource.RLIMIT_CORE,(0,0)))
        self.selector=selectors.DefaultSelector();self.selector.register(self.p.stdout,selectors.EVENT_READ)
        try:
            self.load=self.read();self.load['startup_to_ready_s']=time.monotonic()-self.started
        except BaseException:
            self.close()
            (STATE/('startup-failure-'+backend+'.json')).write_text(json.dumps({'backend':backend,'diagnostics':self.diagnostics},indent=2))
            raise

    def close(self):
        PipeWorker.close(self)
        self.exit_code=self.p.returncode
        if not self.log.closed:
            self.log.seek(0)
            allowed=['ggml_vulkan:','BENCH_BACKENDS:','whisper_backend_init_gpu:','compute buffer','Vulkan0 total size','terminate','what():','Assertion','assertion','Error','error:','failed','vk::','Unsupported','GGML_ASSERT','backend_sched']
            self.diagnostics=[x.strip() for x in self.log.read().splitlines() if any(k in x for k in allowed)][:240]
            self.log.close()

def main():
    os.umask(0o077)
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backend',choices=['cpu','gpu'],required=True)
    p.add_argument('--case',default='jfk');p.add_argument('--model',choices=['tiny.en','tiny.en-q5_1'],default='tiny.en')
    p.add_argument('--threads',type=int,choices=[1,2,3],default=3);p.add_argument('--runs',type=int,default=3)
    p.add_argument('--policy',choices=['file','fixed','vad'],default='file')
    p.add_argument('--worker-timeout',type=float,default=180)
    p.add_argument('--mode',choices=['offline','replay'],default='offline');p.add_argument('--output',required=True)
    a=p.parse_args()
    if platform.system()!='Linux' or platform.machine() not in ['aarch64','arm64']:p.error('Inference must run on the actual Linux ARM64 UNO Q')
    if a.runs<1:p.error('Positive runs required')
    if a.mode=='replay' and a.policy=='file':p.error('Paced replay requires bounded fixed/VAD segments')
    out=Path(a.output).resolve()
    if not out.is_relative_to((STATE/'results').resolve()) or out.exists():p.error('Use a new output under local/experiment3/results')
    provenance=json.loads((STATE/'build-provenance.json').read_text())
    if provenance['source_commit']!=COMMIT or sha(STATE/'transcription-worker2')!=provenance['binary_sha256']:raise ValueError('Binary/source pin mismatch')
    original=json.loads((ROOT/'local/setup.json').read_text())
    if sha(ROOT/'local/build/transcription-worker')!=original['worker_sha256']:raise ValueError('Original CPU worker changed')
    data=ROOT/'local/experiment2';manifest=json.loads((data/'all-fixtures.json').read_text());case=next(x for x in manifest if x['id']==a.case)
    if 'reference_file' in case:case['reference']=(data/case['reference_file']).read_text()
    models=json.loads((data/'models-vad.json').read_text())
    model=ROOT/'local'/original['models']['tiny.en']['file'];expected=original['models']['tiny.en']['sha256']
    if a.model!='tiny.en':model=data/models['quantized']['file'];expected=models['quantized']['sha256']
    if sha(model)!=expected:raise ValueError('Model checksum mismatch')
    module,vad_record=base.load_vad();policy=base.Policy()
    worker=None
    with base.session_lock():
        record={'schema_version':3,'target':'actual UNO Q, Linux ARM64','configuration':vars(a),'build':provenance,'model_sha256':expected,'original_worker_preserved':True,'clock_before':base.clock_state(),'hardware_before':base.hardware(),'policy_settings':base.asdict(policy),'runtime_icd':'/usr/share/vulkan/icd.d/freedreno_icd.json','runtime_overrides':{k:os.environ[k] for k in ['GGML_VK_DISABLE_F16'] if k in os.environ},'runs':[],'runner_sha256':sha(Path(__file__)),'metric_runner_sha256':sha(ROOT/'vad_bench.py'),'application_headroom':'NOT MEASURED'}
        try:
            with tempfile.TemporaryDirectory(prefix='trial-',dir=STATE) as temp:
                wav=Path(temp)/'normalized.wav';case['duration_s']=base.normal_wav((data/case['audio']).resolve(),wav)
                with Worker3(model,a.threads,a.backend,a.worker_timeout) as worker:
                    record['load']=worker.load
                    detector=module.Vad(2) if a.policy=='vad' else None
                    gen=base.frame_segments(wav,policy,a.policy,detector,{})
                    first=next(gen,None);gen.close()
                    if first:
                        raw=Path(temp)/'warmup.f32';base.raw_float(first.pop('pcm'),raw)
                        before=base.sample_drm(worker.p.pid)
                        try:
                            warmup=worker.infer(raw);warmup.pop('text',None)
                        finally:raw.unlink(missing_ok=True)
                        after=base.sample_drm(worker.p.pid)
                        record['first_decode_excluded_warmup']=warmup
                        record['warmup_drm_deltas']={k:after[k]-v for k,v in before.items() if k in after}
                    for i in range(a.runs):
                        r=base.run_once(worker,wav,case,policy,a.policy,module,a.mode,temp,None,30)
                        r['repeat']=i+1;record['runs'].append(r)
                        print(json.dumps({'backend':a.backend,'case_id':a.case,'repeat':i+1,'source_rtf':r['decode_rtf_source_audio'],'wer':r['accuracy'].get('wer'),'drops':r['dropped_segments']}),flush=True)
            record['backend_diagnostics']=worker.diagnostics
            deltas=[v for r in record['runs'] for row in r['rows'] for k,v in row['drm_counter_deltas'].items() if 'drm-engine-' in k or 'drm-cycles-' in k]
            record['hardware_gpu_commands_during_decode']=a.backend=='gpu' and any(x>0 for x in deltas)
            record['hardware_execution_assessment']='positive per-process DRM engine/cycle deltas during successful inference with hardware-only ICD' if record['hardware_gpu_commands_during_decode'] else 'NOT PROVEN: no positive per-process decode engine/cycle evidence'
            record.update(hardware_after=base.hardware(),clock_after=base.clock_state(),status='completed')
        except Exception as e:
            failure=STATE/('startup-failure-'+a.backend+'.json')
            diagnostics=worker.diagnostics if worker else (json.loads(failure.read_text())['diagnostics'] if failure.exists() else [])
            record.update(status='failed',error_type=type(e).__name__,error_message=str(e),backend_diagnostics=diagnostics,hardware_execution_assessment='NOT PROVEN',worker_exit_code=getattr(worker,'exit_code',None))
        out.mkdir(parents=True)
        (out/'metrics.json').write_text(json.dumps(record,indent=2)+'\n')
        fields=['repeat','audio_s','elapsed_s','total_decode_s','decode_rtf_source_audio','python_cpu_s','worker_cpu_s','worker_peak_rss_bytes','dropped_segments','dropped_audio_s','final_drain_s','wer','word_errors','reference_words']
        with (out/'metrics.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader()
            for r in record['runs']:w.writerow(dict(r,**{k:r['accuracy'].get(k) for k in ['wer','word_errors','reference_words']}))
        print(json.dumps({'status':record['status'],'assessment':record['hardware_execution_assessment'],'diagnostics':record.get('backend_diagnostics',[])},indent=2),flush=True)
        if record['status']!='completed':raise SystemExit(1)
if __name__=='__main__':main()
