"""Explicit opt-in 60s built-in microphone diagnostic. Never imported by the app."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import time
import wave

import numpy as np
import sounddevice as sd


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--consent',action='store_true',help='Participants agreed to this bounded recording')
    args=parser.parse_args()
    if not args.consent:parser.error('Explicit --consent is required')
    devices=sd.query_devices()
    matches=[(i,d) for i,d in enumerate(devices) if d['max_input_channels']>0 and 'MacBook Pro' in d['name']]
    if len(matches)!=1:raise RuntimeError('Cannot uniquely identify MacBook Pro built-in microphone; refusing default-device fallback')
    device,info=matches[0]
    sd.check_input_settings(device=device,channels=1,dtype='int16',samplerate=24000)
    root=Path(__file__).parent/'debug_artifacts'/'live'/datetime.now().strftime('%Y%m%d-%H%M%S')
    root.mkdir(parents=True,mode=0o700)
    frames=[];statuses=[];timings=[];total=0
    def callback(data,count,timing,status):
        nonlocal total
        frames.append(bytes(data));total+=count
        timings.append(float(timing.inputBufferAdcTime))
        if status:statuses.append(str(status))
    started=time.monotonic()
    with sd.RawInputStream(device=device,channels=1,samplerate=24000,dtype='int16',blocksize=2400,callback=callback):
        print(f'RECORDING STARTED: {info["name"]}; 60 seconds; {root}',flush=True)
        deadline=time.monotonic()+60
        next_report=time.monotonic()+10
        while time.monotonic()<deadline and total<24000*60:
            time.sleep(.05)
            if time.monotonic()>=next_report:
                print(f'Captured {total/24000:.1f}s',flush=True);next_report+=10
    pcm=b''.join(frames)[:24000*60*2]
    path=root/'microphone.wav'
    with wave.open(str(path),'wb') as recording:
        recording.setparams((1,2,24000,0,'NONE','not compressed'));recording.writeframes(pcm)
    os.chmod(path,0o600)
    samples=np.frombuffer(pcm,dtype='<i2').astype(float)/32768
    blocks=[samples[i:i+2400] for i in range(0,len(samples),2400)]
    rms=[float(np.sqrt(np.mean(b*b))) for b in blocks if len(b)]
    report={'device':info['name'],'seconds':len(pcm)/48000,'wall_seconds':round(time.monotonic()-started,2),
            'input_statuses':statuses,'peak':float(np.max(np.abs(samples))) if samples.size else 0,
            'rms_percentiles':dict(zip(['p10','p50','p90','p99'],map(float,np.percentile(rms,[10,50,90,99])))) if rms else {},
            'below_old_threshold_seconds':sum(v<.002 for v in rms)*.1,
            'adc_gap_max_seconds':float(max(np.diff(timings))) if len(timings)>1 else None,
            'file':str(path)}
    (root/'capture-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('RECORDING STOPPED',flush=True);print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
