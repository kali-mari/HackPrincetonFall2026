#!/usr/bin/env python3
"""Explicit approved public downloads; no inference, recording or reference logging."""
import argparse, hashlib, json, subprocess, urllib.parse, wave
from pathlib import Path
VAD_VERSION='2.0.14.post1'
VAD_URL='https://files.pythonhosted.org/packages/cf/be/7ae9fa9740e62f2b8d0d62a54f681817d0b6415f805d5d20d987bbd630df/webrtcvad_wheels-2.0.14.post1-cp313-cp313-manylinux2014_aarch64.manylinux_2_17_aarch64.whl'
VAD_SHA='9658d73f8d9aca3070244a359c36ac1c92b87551b4bc1525fbca8dd97fcef459'
def fetch_json(url):
    return json.loads(subprocess.check_output(['curl','--silent','--show-error','--fail','--location','--max-time','60',url]))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def download(url,path):
    if not path.exists():
        temp=path.with_suffix(path.suffix+'.partial')
        subprocess.run(['curl','--silent','--show-error','--fail','--location','--max-time','300','-o',str(temp),url],check=True)
        temp.rename(path)
def rows(dataset,config,split,length):
    meta=fetch_json('https://huggingface.co/api/datasets/'+dataset)
    api='https://datasets-server.huggingface.co/rows?'+urllib.parse.urlencode(dict(dataset=dataset,config=config,split=split,offset=0,length=length))
    return meta,fetch_json(api)['rows'],api
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--download-approved-public-fixtures',action='store_true',required=True);p.parse_args()
    root=Path(__file__).resolve().parent/'local/experiment2';root.mkdir(parents=True,exist_ok=True,mode=0o700)
    fixtures=root/'fixtures';fixtures.mkdir(exist_ok=True,mode=0o700)
    complete=[root/'fixtures.json',root/'fixture-provenance.json',root/'models-vad.json']
    if all(x.exists() for x in complete):
        saved=json.loads(complete[0].read_text());provenance=json.loads(complete[1].read_text());models=json.loads(complete[2].read_text())
        by_id={x['id']:x for x in saved}
        for item in provenance:
            case=by_id[item['id']]
            if sha(root/case['audio'])!=item['audio_sha256'] or sha(root/case['reference_file'])!=item['reference_sha256']:raise RuntimeError('Existing approved fixture bundle changed; refusing overwrite')
        if sha(root/models['vad']['wheel'])!=models['vad']['sha256'] or sha(root/models['quantized']['file'])!=models['quantized']['sha256']:raise RuntimeError('Existing dependency/model checksum mismatch')
        print('Reused complete checksummed approved fixture/dependency bundle; no network or reference overwrite')
        return
    wheel=root/VAD_URL.rsplit('/',1)[1];download(VAD_URL,wheel)
    if sha(wheel)!=VAD_SHA:raise RuntimeError('VAD checksum mismatch')
    manifest=[];provenance=[]
    meta,items,api=rows('hf-internal-testing/librispeech_asr_dummy','clean','validation',100)
    selected=[('read_short',items[0]),('reply_short',min(items,key=lambda x:len(x['row']['text'].split())))]
    def fixture(name,item,meta,api,dataset,license_name,license_url,category):
        row=item['row']
        if 'text' in item.get('truncated_cells',[]):raise RuntimeError('Truncated reference')
        url=row['audio'][0]['src']
        if meta['sha'] not in url:raise RuntimeError('Dataset revision mismatch')
        audio=fixtures/(name+'.wav');ref=fixtures/(name+'.txt')
        download(url,audio);ref.write_text(row['text']+'\n')
        header=audio.read_bytes()[:42]
        if header[:4]==b'fLaC' and (header[4]&127)==0:
            packed=int.from_bytes(header[18:26],'big');duration=(packed&((1<<36)-1))/(packed>>44)
        else:
            with wave.open(str(audio),'rb') as f:duration=f.getnframes()/f.getframerate()
        manifest.append(dict(id=name,audio='fixtures/'+audio.name,reference_file='fixtures/'+ref.name,category=category,speech_boundaries=None,source_duration_s=duration))
        provenance.append(dict(id=name,dataset=dataset,revision=meta['sha'],row_index=item['row_idx'],api=api,license=license_name,license_source=license_url,audio_sha256=sha(audio),reference_sha256=sha(ref)))
    for name,item in selected:
        fixture(name,item,meta,api,'hf-internal-testing/librispeech_asr_dummy','LibriSpeech CC BY 4.0','https://www.openslr.org/12/','short')
    meta,items,api=rows('distil-whisper/tedlium-long-form','default','validation',1)
    fixture('natural_long',items[0],meta,api,'distil-whisper/tedlium-long-form','TED-LIUM CC BY-NC-ND 3.0; local evaluation only; audio/reference not redistributed','https://www.openslr.org/19/','continuous')
    setup_path=root.parent/'target-setup.json'
    if not setup_path.exists():setup_path=root.parent/'setup.json'
    setup=json.loads(setup_path.read_text());revision=setup['models']['tiny.en']['revision']
    meta=fetch_json('https://huggingface.co/api/models/ggerganov/whisper.cpp/revision/'+revision+'?blobs=true')
    filename='ggml-tiny.en-q5_1.bin';item=next(x for x in meta['siblings'] if x['rfilename']==filename)
    model=root/filename;download('https://huggingface.co/ggerganov/whisper.cpp/resolve/'+revision+'/'+filename,model)
    if sha(model)!=item['lfs']['sha256']:raise RuntimeError('Quantized model checksum mismatch')
    (root/'models-vad.json').write_text(json.dumps({'vad':dict(version=VAD_VERSION,url=VAD_URL,sha256=VAD_SHA,wheel=wheel.name,license='MIT'),'quantized':dict(file=filename,revision=revision,sha256=sha(model))},indent=2)+'\n')
    (root/'fixtures.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (root/'fixture-provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print(json.dumps({'fixture_durations_s':{x['id']:x['source_duration_s'] for x in manifest},'vad_version':VAD_VERSION,'quantized_sha256':sha(model)},indent=2))
if __name__=='__main__':main()
