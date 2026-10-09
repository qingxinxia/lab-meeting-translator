"""Bounded synthetic live-ASR probe; no microphone or private recording input."""
import asyncio
import json
from pathlib import Path
import tempfile
import time
import wave

from meeting import MeetingSession
from topics import Glossaries


async def main():
    fixture = Path(__file__).parent / 'debug_artifacts' / 'mixed.wav'
    with wave.open(str(fixture)) as wav:
        assert (wav.getframerate(),wav.getnchannels(),wav.getsampwidth()) == (24000,1,2)
        pcm = wav.readframes(wav.getnframes())
    started = time.monotonic()

    class Client:
        offset = 0
        events = []

        async def receive(self):
            if self.offset >= len(pcm):
                return {'type':'websocket.receive','text':json.dumps({'type':'stop','sent_bytes':self.offset})}
            frame = pcm[self.offset:self.offset+4800]
            self.offset += len(frame)
            await asyncio.sleep(len(frame)/48000)
            return {'type':'websocket.receive','bytes':frame}

        async def send_json(self, event):
            event = dict(event, wall_seconds=round(time.monotonic()-started,3),
                         audio_seconds=round(self.offset/48000,3))
            self.events.append(event)
            if event['type'] not in {'diagnostics','source.delta'}:
                print(json.dumps(event,ensure_ascii=False),flush=True)

    client = Client()
    with tempfile.TemporaryDirectory(prefix='live-transcript-probe-') as directory:
        await asyncio.wait_for(MeetingSession(client,'中文','indoor',Glossaries(directory)).run(),100)
    report = {'fixture':'synthetic indoor positioning Japanese/English',
              'duration':len(pcm)/48000,'events':client.events}
    output = fixture.parent/'streaming-report.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('Report:',output)


if __name__ == '__main__':
    asyncio.run(main())
