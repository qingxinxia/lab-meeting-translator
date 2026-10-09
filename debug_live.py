"""Compare recorded, consented microphone audio against the original VAD path.

Explicit filename required. No microphone access. Sends this file to OpenAI.
"""
import argparse
import asyncio
import base64
import json
from pathlib import Path
import time
import wave
from websockets.asyncio.client import connect
from config import ASR_URL, OPENAI_API_KEY
from meeting import AudioWindow, asr_configuration
from topics import Glossaries


async def transcribe(windows):
    events=[];started=time.monotonic()
    async with connect(ASR_URL,additional_headers={'Authorization':f'Bearer {OPENAI_API_KEY}'},max_size=2**22,open_timeout=20) as socket:
        await socket.send(json.dumps(asr_configuration('indoor',Glossaries())))
        while True:
            event=json.loads(await socket.recv())
            if event['type']=='error':raise RuntimeError(event['error']['message'])
            if event['type']=='session.updated':break
        async def send():
            for pcm in windows:
                if len(pcm)<4800:pcm+=bytes(4800-len(pcm))
                for i in range(0,len(pcm),4800):
                    await socket.send(json.dumps({'type':'input_audio_buffer.append','audio':base64.b64encode(pcm[i:i+4800]).decode()}))
                await socket.send(json.dumps({'type':'input_audio_buffer.commit'}))
        sender=asyncio.create_task(send());completed=0
        try:
            async with asyncio.timeout(120):
                while completed<len(windows):
                    event=json.loads(await socket.recv())
                    if event['type']=='error':raise RuntimeError(event['error']['message'])
                    if event['type'] in ('input_audio_buffer.committed','conversation.item.input_audio_transcription.completed','conversation.item.input_audio_transcription.failed'):
                        events.append(event)
                    if event['type'].endswith(('.completed','.failed')):completed+=1
            await sender
        finally:sender.cancel();await asyncio.gather(sender,return_exceptions=True)
    return {'elapsed_seconds':round(time.monotonic()-started,2),'events':events}


async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--file',type=Path,required=True);args=parser.parse_args()
    with wave.open(str(args.file)) as wav:
        if (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())!=(24000,1,2):raise ValueError('Expected 24k mono PCM16')
        pcm=wav.readframes(wav.getnframes())
    window=AudioWindow(discard_silence=True);windows=[];intervals=[]
    for i in range(0,len(pcm),4800):
        data=window.push(pcm[i:i+4800])
        if data:windows.append(data);intervals.append([max(0,(i+4800-len(data))/48000),min((i+4800)/48000,len(pcm)/48000)])
    tail=window.flush()
    if tail:windows.append(tail);intervals.append([(len(pcm)-len(tail))/48000,len(pcm)/48000])
    report={'input_seconds':len(pcm)/48000,'legacy_sent_seconds':sum(map(len,windows))/48000,'legacy_intervals':intervals}
    for name,chunks in [('full_recording',[pcm]),('legacy_segments',windows)]:
        try:report[name]=await transcribe(chunks)
        except Exception as error:report[name]={'error':str(error)}
        print(name,json.dumps(report[name],ensure_ascii=False),flush=True)
        (args.file.parent/'recognition-comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in {'full_recording','legacy_segments'}},ensure_ascii=False))


if __name__=='__main__':asyncio.run(main())
