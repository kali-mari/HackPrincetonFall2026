#!/usr/bin/env python3
"""Collect only aggregate/provenance files over USB; never audio or references."""
import argparse,csv,hashlib,json,statistics,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
STATE=ROOT/'local/experiment2'
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--adb',required=True);p.add_argument('--serial',required=True);a=p.parse_args()
    adb=[a.adb,'-s',a.serial]
    remote='/home/arduino/hardware/benchmarks/transcription/local/experiment2'
    names=subprocess.check_output(adb+['shell',"find "+remote+"/results -mindepth 2 -maxdepth 2 -name metrics.json"],text=True).splitlines()
    dest=STATE/'target-results';dest.mkdir(parents=True,exist_ok=True)
    for path in names:
        name=Path(path).parent.name;folder=dest/name;folder.mkdir(exist_ok=True)
        for filename in ['metrics.json','metrics.csv']:
            data=subprocess.check_output(adb+['exec-out','cat',str(Path(path).parent/filename)])
            target=folder/filename
            if target.exists() and target.read_bytes()!=data:raise RuntimeError('Remote aggregate changed; preserve previous copy')
            if not target.exists():target.write_bytes(data)
    evidence=STATE/'target-evidence';evidence.mkdir(exist_ok=True)
    for name in ['gpu-build.json','gpu-cutoff.json','gpu-build.log','gpu-build-resume.log','vulkaninfo.txt','gpu-packages.json','clock.json','clock-refined.json','clock-after-reconnect.json','clock-current.json','fixture-provenance.json','derived-provenance.json','models-vad.json','vad-preflight.json']:
        r=subprocess.run(adb+['exec-out','cat',remote+'/'+name],capture_output=True)
        if r.returncode==0:
            target=evidence/name
            if not target.exists():target.write_bytes(r.stdout)
            elif target.read_bytes()!=r.stdout:raise RuntimeError('Existing evidence changed; use a new evidence snapshot')
    kernel=subprocess.run(adb+['shell','journalctl -b -1 -k --no-pager --grep="Out of memory|oom-kill|cc1plus invoked" -n 8'],capture_output=True,text=True)
    if kernel.returncode==0:(evidence/'gpu-kernel-oom.txt').write_text(kernel.stdout)
    rows=[]
    for path in sorted(dest.glob('*/metrics.json')):
        r=json.loads(path.read_text());runs=r['runs'];cfg=r['configuration']
        for run in runs:
            for item in run['rows']:
                if 'text' in item:raise ValueError('Unexpected transcript field')
        nonblank=[x['source_nonblank_output'] for x in runs if x['source_nonblank_output'] is not None]
        wers=[x['accuracy']['wer'] for x in runs if x['accuracy'].get('wer') is not None]
        traces=[y for x in runs for y in x['monitor_trace']]
        temps=[x['temperature_millidegrees_c']/1000 for x in traces if x.get('temperature_millidegrees_c') is not None]
        avail=[x['MemAvailable'] for x in traces if x.get('MemAvailable') is not None]
        cpu=[x['worker_cpu_s']/x['total_decode_s']*100 for x in runs if x['total_decode_s']]
        rows.append(dict(configuration=path.parent.name,case_id=r['case_id'],model=cfg['model'],threads=cfg['threads'],backend=cfg['backend'],policy=cfg['policy'],mode=cfg['mode'],repeat_n=len(runs),audio_s=runs[0]['audio_s'],median_decode_s=statistics.median(x['total_decode_s'] for x in runs),median_source_rtf=statistics.median(x['decode_rtf_source_audio'] for x in runs),median_worker_cpu_percent=statistics.median(cpu) if cpu else 0,peak_worker_mib=max(x['worker_peak_rss_bytes'] for x in runs)/1048576,median_wer=statistics.median(wers) if wers else None,reference_words=runs[0]['accuracy'].get('reference_words'),nonblank_non_speech_runs=sum(nonblank) if nonblank else None,dropped_segments=sum(x['dropped_segments'] for x in runs),dropped_audio_s=sum(x['dropped_audio_s'] for x in runs),stale_results=sum(y['stale_output_discarded'] for x in runs for y in x['rows']),max_pending_s=max([x['max_pending_audio_s'] for x in runs if x['max_pending_audio_s'] is not None],default=None),max_final_drain_s=max([x['final_drain_s'] for x in runs if x['final_drain_s'] is not None],default=None),max_observed_temperature_c=max(temps,default=None),minimum_sampled_available_mib=min(avail)/1048576 if avail else None,wall_clock_stable=r['wall_clock_stable']))
    (STATE/'summary.json').write_text(json.dumps(rows,indent=2)+'\n')
    with (STATE/'summary.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print('Collected aggregate configurations:',len(rows))
if __name__=='__main__':main()
