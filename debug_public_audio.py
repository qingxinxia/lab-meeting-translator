"""Public CSJ audio A/B test. Never opens a microphone or reads private recordings.

Download source and transcript from NINJAL's public sample page before running.
Artificial noise is reproducible, not a recording of a MacBook/meeting room.
"""
import argparse
import asyncio
import base64
import json
from pathlib import Path
import re
import time
import unicodedata
import wave
import numpy as np
from websockets.asyncio.client import connect
from config import ASR_URL, OPENAI_API_KEY
from meeting import AudioWindow, asr_configuration, translate_text

ROOT=Path(__file__).parent/'debug_artifacts'/'public-csj'


def reference():
    lines=[]
    for line in (ROOT/'aps-smp.txt').read_text().splitlines():
        if '&' not in line:continue
        line=line.split('&')[0]
        line=re.sub(r'\([FD] [^)]*\)','',line)
        lines.append(re.sub(r'<[^>]*>','',line).strip())
    return ''.join(lines)


def normalize(text):
    text=unicodedata.normalize('NFKC',text)
    text=re.sub(r'えー+|あのー?|ええ|まあ','',text)
    return ''.join(c for c in text if not unicodedata.category(c).startswith(('P','Z')) and not c.isspace())


def cer(expected,actual):
    a,b=normalize(expected),normalize(actual);row=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        nxt=[i]
        for j,y in enumerate(b,1):nxt.append(min(nxt[-1]+1,row[j]+1,row[j-1]+(x!=y)))
        row=nxt
    return {'edits':row[-1],'reference_characters':len(a),'cer':round(row[-1]/max(1,len(a)),4)}


def highpass(samples,hz=80):
    alpha=np.exp(-2*np.pi*hz/24000);out=np.empty_like(samples);previous=0.;state=0.
    for i,value in enumerate(samples):state=alpha*(state+value-previous);previous=value;out[i]=state
    return out


def pcm(samples):return (np.clip(samples,-1,1)*32767).astype('<i2').tobytes()


def split(data,adaptive=False):
    window=AudioWindow(adaptive=adaptive);chunks=[]
    for pos in range(0,len(data),4800):
        chunk=window.push(data[pos:pos+4800])
        if chunk:chunks.append(chunk)
    tail=window.flush()
    if tail:chunks.append(tail)
    assert b''.join(chunks)==data
    return chunks


async def probe(chunks,reduction):
    config=asr_configuration()
    audio=config['session']['audio']['input'];audio['noise_reduction']={'type':reduction} if reduction else None
    # Broad source-page context only. Do not leak reference text/terms into ASR.
    audio['transcription']['prompt']='A Japanese academic presentation about phonetics.'
    audio['transcription']['keywords']=[]
    order=[];finals={};started=time.monotonic()
    async with asyncio.timeout(100):
        async with connect(ASR_URL,additional_headers={'Authorization':f'Bearer {OPENAI_API_KEY}'},open_timeout=20,max_size=2**22) as socket:
            await socket.send(json.dumps(config))
            while True:
                e=json.loads(await socket.recv())
                if e['type']=='error':raise RuntimeError(e['error']['message'])
                if e['type']=='session.updated':break
            async def send():
                for chunk in chunks:
                    if len(chunk)<4800:chunk+=bytes(4800-len(chunk))
                    for i in range(0,len(chunk),4800):
                        await socket.send(json.dumps({'type':'input_audio_buffer.append','audio':base64.b64encode(chunk[i:i+4800]).decode()}))
                    await socket.send(json.dumps({'type':'input_audio_buffer.commit'}))
            task=asyncio.create_task(send())
            try:
                while len(finals)<len(chunks):
                    e=json.loads(await socket.recv())
                    if e['type']=='error':raise RuntimeError(e['error']['message'])
                    if e['type']=='input_audio_buffer.committed':order.append(e['item_id'])
                    if e['type']=='conversation.item.input_audio_transcription.failed':raise RuntimeError('ASR failed')
                    if e['type']=='conversation.item.input_audio_transcription.completed':finals[e['item_id']]=e.get('transcript','')
                await task
            finally:task.cancel();await asyncio.gather(task,return_exceptions=True)
    return {'text':''.join(finals[i] for i in order),'segments':[finals[i] for i in order],
            'empty_segments':sum(not finals[i].strip() for i in order),'elapsed_seconds':round(time.monotonic()-started,2)}


async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cases',nargs='+',default=['clean','clean_far','noisy','noisy_far','noisy_hp','noisy_hp_far']);args=parser.parse_args()
    with wave.open(str(ROOT/'clean.wav')) as wav:
        assert (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())==(24000,1,2)
        samples=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype(float)/32768
    t=np.arange(len(samples))/24000;rng=np.random.default_rng(20261008)
    noise=.8*np.sin(2*np.pi*50*t)+.4*np.sin(2*np.pi*100*t)+.25*rng.normal(size=len(t))
    noise*=np.sqrt(np.mean(samples**2))/np.sqrt(np.mean(noise**2)) # 0 dB stress test
    noisy=samples+noise;gain=min(1,.95/max(np.max(np.abs(noisy)),1e-9));noisy*=gain
    variants={'clean':(samples,None),'clean_far':(samples,'far_field'),'noisy':(noisy,None),
              'noisy_far':(noisy,'far_field'),'noisy_hp':(highpass(noisy),None),'noisy_hp_far':(highpass(noisy),'far_field'),
              'clean_adaptive_v2':(samples,None),'noisy_hp_adaptive_v2':(highpass(noisy),None)}
    variants.update(clean_hp=(highpass(samples),None),noisy_repeat=(noisy,None),noisy_hp_repeat=(highpass(noisy),None))
    path=ROOT/'ab-report.json';report=json.loads(path.read_text()) if path.exists() else {}
    report.update(source_url='https://clrd.ninjal.ac.jp/csj/en/sample.html',audio_seconds=len(samples)/24000,
                  noise='Artificial 50/100 Hz hum + broadband noise, 0 dB SNR, seed 20261008; not real room noise',
                  reference_note='Character edit rate, punctuation/filler normalization only; spelling differences count as errors',results=report.get('results',{}))
    for name in args.cases:
        audio,reduction=variants[name];adaptive='adaptive' in name;chunks=split(pcm(audio),adaptive=adaptive)
        try:
            result=await probe(chunks,reduction);result.update(cer(reference(),result['text']))
            result['windows_seconds']=[len(c)/48000 for c in chunks]
            result['configuration']={'highpass_hz':80 if '_hp' in name else 0,'server_noise_reduction':reduction,
                                     'segmentation':'adaptive_v2_min5_pause0.5_floor1.2' if adaptive else 'fixed_rms_min1_pause0.3',
                                     'max_window_seconds':15,'input_samples':len(audio),
                                     'translation_context':'production default indoor topic; not matched to phonetics sample'}
            result['translation']=await asyncio.to_thread(translate_text,result['text'],'中文',[])
        except Exception as error:result={'error':str(error)}
        report['results'][name]=result;path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(name,json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':asyncio.run(main())
