#!/usr/bin/env python3
"""Run controlled experiment stages strictly sequentially on the UNO Q.
Each child holds the benchmark lock; suite lock also prevents two coordinators.
"""
import argparse,fcntl,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
STATE=ROOT/'local/experiment2'
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage',required=True,choices=['controlled','accuracy','sustained','gpu'])
    p.add_argument('--shortlist-model',choices=['tiny.en','tiny.en-q5_1'],default='tiny.en')
    p.add_argument('--shortlist-threads',type=int,choices=[1,2,3],default=3)
    p.add_argument('--sustained-runs',type=int,default=1)
    p.add_argument('--policies',nargs='+',choices=['fixed','vad'],default=['fixed','vad'])
    a=p.parse_args()
    plan=[]
    def add(name,case='jfk',threads=3,model='tiny.en',policy='file',mode='offline',runs=3,backend='original-cpu'):
        plan.append((name,[sys.executable,'vad_bench.py','--manifest','local/experiment2/all-fixtures.json','--case',case,'--threads',str(threads),'--model',model,'--policy',policy,'--mode',mode,'--runs',str(runs),'--backend',backend,'--output','local/experiment2/results/'+name]))
    if a.stage=='controlled':
        for threads in [3,2,1]:add('controlled-tiny-t'+str(threads),threads=threads)
        for threads in [3,2]:add('controlled-q5-t'+str(threads),threads=threads,model='tiny.en-q5_1')
        for threads in [3,2]:add('quantized-reference-t'+str(threads),case='read_short',threads=threads,model='tiny.en-q5_1')
    elif a.stage=='accuracy':
        for case in ['read_short','reply_short','quiet','pauses_ref','silence','noise_only','noisy_ref']:
            for policy in ['file','vad']:add('accuracy-'+case+'-'+policy,case=case,policy=policy)
        add('accuracy-read-q5-vad',case='read_short',policy='vad',model='tiny.en-q5_1')
        add('accuracy-reply-q5-vad',case='reply_short',policy='vad',model='tiny.en-q5_1')
    elif a.stage=='sustained':
        for policy in a.policies:
            name='sustained-'+a.shortlist_model+'-t'+str(a.shortlist_threads)+'-'+policy
            add(name,case='natural_300',threads=a.shortlist_threads,model=a.shortlist_model,policy=policy,mode='replay',runs=a.sustained_runs)
    else:
        for backend in ['matched-cpu','vulkan']:
            add('gpu-'+backend+'-jfk',backend=backend)
            add('gpu-'+backend+'-reference',case='read_short',backend=backend)
            add('gpu-'+backend+'-vad',case='read_short',policy='vad',backend=backend)
    STATE.mkdir(exist_ok=True)
    with (STATE/'suite.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Another suite coordinator is active')
        suffix=('-'+a.shortlist_model+'-t'+str(a.shortlist_threads)+'-'+'-'.join(a.policies)) if a.stage=='sustained' else ''
        planpath=STATE/('suite-plan-'+a.stage+suffix+'.json')
        if not planpath.exists():planpath.write_text(json.dumps(plan,indent=2)+'\n')
        for name,cmd in plan:
            output=ROOT/cmd[-1]/'metrics.json'
            if output.exists():
                existing=json.loads(output.read_text())
                if existing['configuration']['case']!=cmd[cmd.index('--case')+1]:raise RuntimeError('Existing result does not match plan')
                print('Preserved completed:',name,flush=True);continue
            print('Starting:',name,flush=True)
            subprocess.run(cmd,cwd=ROOT,check=True)
            r=json.loads(output.read_text())
            print(json.dumps({'completed':name,'median_source_rtf':r['summaries']['decode_rtf_source_audio']['median'],'wer':[x['accuracy'].get('wer') for x in r['runs']],'drops':[x['dropped_segments'] for x in r['runs']]}),flush=True)
    print('Suite stage completed:',a.stage,flush=True)
if __name__=='__main__':main()
