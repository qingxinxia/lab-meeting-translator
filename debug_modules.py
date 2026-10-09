"""Opt-in, bounded real API probes with synthetic indoor-positioning audio.

No microphone access. Run --generate to build local fixtures, --probe to send
only those fixtures to the configured OpenAI endpoints.
"""
import argparse
import asyncio
import base64
from collections import Counter
import json
from pathlib import Path
import subprocess
import time
import wave

from websockets.asyncio.client import connect
from config import OPENAI_API_KEY, ASR_URL, MEETING_ASR_MODEL, TRANSLATION_MODEL

FIXTURES = Path(__file__).parent / "debug_artifacts"
SENTENCES = [
    ("en", "Samantha", "We are discussing indoor positioning. We use Wi-Fi fingerprinting and Bluetooth beacons to estimate the position. The median localization error is two meters."),
    ("ja", "Kyoko", "室内測位について議論しています。ブルートゥースのビーコンを使って位置を推定します。測位誤差の中央値は二メートルです。"),
]


def generate():
    FIXTURES.mkdir(exist_ok=True)
    chunks = []
    for lang, voice, sentence in SENTENCES:
        path = FIXTURES / f"{lang}.wav"
        subprocess.run(["/usr/bin/say", "-v", voice, "-r", "165", "-o", str(path),
                        "--file-format=WAVE", "--data-format=LEI16@24000", sentence], check=True)
        with wave.open(str(path)) as audio:
            assert audio.getnchannels() == 1 and audio.getsampwidth() == 2
            chunk=audio.readframes(audio.getnframes())
            if len(chunk)<48000 or not any(chunk):
                raise RuntimeError(f"{voice} produced empty/silent audio; fixture not usable")
            chunks.append(chunk)
    with wave.open(str(FIXTURES / "mixed.wav"), "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes(bytes(24000) + bytes(48000).join(chunks) + bytes(96000))
    return FIXTURES / "mixed.wav"


async def probe(kind, path):
    with wave.open(str(path)) as audio:
        pcm = audio.readframes(audio.getnframes())
    translation = kind == "translation"
    url = (f"wss://api.openai.com/v1/realtime/translations?model={TRANSLATION_MODEL}"
           if translation else ASR_URL)
    from webapp import _source_prompt
    config = {"type": "session.update", "session": {"audio": {"input": {
        "noise_reduction": None,
        "transcription": {"model": "gpt-realtime-whisper" if translation else MEETING_ASR_MODEL},
    }}}}
    if translation:
        config["session"]["audio"]["output"] = {"language": "zh"}
    else:
        config["session"]["type"] = "transcription"
        config["session"]["audio"]["input"].update({"format": {"type": "audio/pcm", "rate": 24000}, "turn_detection": None})
        config["session"]["audio"]["input"]["transcription"]["prompt"] = _source_prompt("auto")
    result = {"module": kind, "audio_seconds": len(pcm) / 48000, "events": Counter(), "source": [], "translation": [], "errors": []}
    start = time.monotonic()
    async with connect(url, additional_headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "OpenAI-Safety-Identifier": "indoor-positioning-diagnostic"}, max_size=2**24, open_timeout=20) as socket:
        await socket.send(json.dumps(config))
        async with asyncio.timeout(20):
            while True:
                event = json.loads(await socket.recv())
                if event["type"] == "error":
                    result["errors"].append(event.get("error")); return result
                if event["type"] == "session.updated": break
        async def send():
            for offset in range(0, len(pcm), 4800):
                await socket.send(json.dumps({"type": ("session." if translation else "") + "input_audio_buffer.append", "audio": base64.b64encode(pcm[offset:offset+4800]).decode()}))
                await asyncio.sleep(.1)
            await socket.send(json.dumps({"type": "session.close" if translation else "input_audio_buffer.commit"}))
        sender = asyncio.create_task(send())
        try:
            async with asyncio.timeout(len(pcm) / 48000 + 40):
                async for raw in socket:
                    event = json.loads(raw); kind_name = event["type"]
                    result["events"][kind_name] += 1
                    if kind_name == "error": result["errors"].append(event.get("error"))
                    if kind_name == "session.input_transcript.delta": result["source"].append(event.get("delta", ""))
                    if kind_name == "session.output_transcript.delta": result["translation"].append(event.get("delta", ""))
                    if kind_name == "conversation.item.input_audio_transcription.completed":
                        result["source"].append(event.get("transcript", "")); result["languages"] = event.get("languages"); break
                    if kind_name == "session.closed": break
        except TimeoutError:
            result["errors"].append("Timeout waiting for final output")
        finally:
            sender.cancel(); await asyncio.gather(sender, return_exceptions=True)
    result["elapsed_seconds"] = round(time.monotonic() - start, 2)
    return result


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--probe", choices=["asr", "translation", "both"])
    parser.add_argument("--pipeline", action="store_true", help="Test new PCM → ASR → text translation pipeline")
    parser.add_argument('--audio-file',type=Path,help='Explicit consented WAV instead of synthetic fixture; no microphone access')
    args = parser.parse_args()
    path = args.audio_file or (generate() if args.generate else FIXTURES / "mixed.wav")
    if args.pipeline:
        from meeting import MeetingSession
        from topics import Glossaries
        import tempfile
        with wave.open(str(path)) as wav:
            if (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())!=(24000,1,2):raise ValueError('Expected 24k mono PCM16 WAV')
            pcm=wav.readframes(wav.getnframes())
        class FixtureClient:
            def __init__(self):self.offset=0;self.events=[]
            async def send_json(self,event):
                self.events.append(event)
                if event['type'] in {'source.final','translation.final','segment.error','closed'}:
                    print(json.dumps(event,ensure_ascii=False),flush=True)
            async def receive(self):
                if self.offset>=len(pcm):return {'type':'websocket.receive','text':'{"type":"stop"}'}
                chunk=pcm[self.offset:self.offset+4800];self.offset+=len(chunk)
                await asyncio.sleep(len(chunk)/48000)
                return {'type':'websocket.receive','bytes':chunk}
        client=FixtureClient();start=time.monotonic()
        with tempfile.TemporaryDirectory(prefix='meeting-probe-') as directory:
            try:
                await MeetingSession(client,'中文','indoor',Glossaries(directory)).run()
            finally:
                report={'audio_seconds':len(pcm)/48000,'elapsed_seconds':round(time.monotonic()-start,2),'events':client.events}
                (path.parent/'pipeline-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(f"Report: {path.parent/'pipeline-report.json'}")
    elif args.probe:
        kinds = ["asr", "translation"] if args.probe == "both" else [args.probe]
        results = await asyncio.gather(*(probe(k, path) for k in kinds), return_exceptions=True)
        report = [str(r) if isinstance(r, Exception) else r for r in results]
        (FIXTURES / "protocol-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(path)


if __name__ == "__main__":
    asyncio.run(main())
