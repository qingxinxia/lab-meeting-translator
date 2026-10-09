import asyncio
import base64
from collections.abc import AsyncIterator
from collections import deque
import json
import time

import numpy as np
from websockets.asyncio.client import connect

from config import (
    ASR_DELAY, ASR_KEYWORDS, ASR_MODEL, ASR_PROMPT, ASR_URL,
    CHUNK_MS, CLIENT_VAD_PREFIX_MS, CLIENT_VAD_RMS,
    CLIENT_VAD_SILENCE_MS, SAMPLE_RATE,
)


def session_update(file_mode: bool = False) -> dict:
    return {
        "type": "session.update",
        "session": {
            "type": "transcription",
            "audio": {"input": {
                "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                "transcription": {
                    "model": ASR_MODEL, "prompt": ASR_PROMPT,
                    "keywords": ASR_KEYWORDS, "languages": ["ja", "en"],
                    "delay": ASR_DELAY,
                },
                # gpt-live-transcribe requires manual commits; server_vad is unsupported.
                "turn_detection": None,
                "noise_reduction": None,
            }},
        },
    }


def check_error(event: dict) -> None:
    if event["type"] in ("error", "conversation.item.input_audio_transcription.failed"):
        raise RuntimeError(f"ASR error: {event.get('error', event)}")


async def append_audio(socket, chunk: bytes) -> None:
    await socket.send(json.dumps({
        "type": "input_audio_buffer.append",
        "audio": base64.b64encode(chunk).decode("ascii"),
    }))


async def commit_audio(socket) -> None:
    await socket.send(json.dumps({"type": "input_audio_buffer.commit"}))


def audio_rms(chunk: bytes) -> float:
    samples = np.frombuffer(chunk, dtype="<i2").astype(np.float32) / 32768
    return float(np.sqrt(np.mean(samples ** 2))) if samples.size else 0.0


async def send_audio(socket, audio: AsyncIterator[bytes], file_mode: bool = False) -> None:
    if file_mode:
        async for chunk in audio:
            await append_audio(socket, chunk)
        await commit_audio(socket)
        return

    # gpt-live-transcribe has no server VAD. Keep a short local pre-roll so the
    # beginning of a word is retained, then commit after sustained silence.
    prefix_chunks = max(1, CLIENT_VAD_PREFIX_MS // CHUNK_MS)
    prefix = deque(maxlen=prefix_chunks)
    speaking = False
    silent_ms = 0

    async for chunk in audio:
        level = audio_rms(chunk)
        if not speaking:
            prefix.append(chunk)
            if level < CLIENT_VAD_RMS:
                continue
            speaking = True
            silent_ms = 0
            print(f"[CLIENT VAD] Speech started (rms={level:.5f})", flush=True)
            for buffered in prefix:
                await append_audio(socket, buffered)
            prefix.clear()
            continue

        await append_audio(socket, chunk)
        if level >= CLIENT_VAD_RMS:
            silent_ms = 0
            continue

        silent_ms += CHUNK_MS
        if silent_ms >= CLIENT_VAD_SILENCE_MS:
            await commit_audio(socket)
            print("[CLIENT VAD] Speech ended; audio committed", flush=True)
            speaking = False
            silent_ms = 0
            prefix.clear()

    if speaking:
        await commit_audio(socket)


async def print_transcripts(socket, file_mode: bool = False) -> None:
    started = time.monotonic()
    stopped = {}
    first_delta = set()
    async for message in socket:
        event = json.loads(message)
        check_error(event)
        kind = event["type"]
        item = event.get("item_id", "")
        now = time.monotonic()
        if kind == "input_audio_buffer.speech_started":
            print(f"[SPEECH START] +{now - started:.2f}s item={item}", flush=True)
        elif kind == "input_audio_buffer.speech_stopped":
            stopped[item] = now
            print(f"[SPEECH END] +{now - started:.2f}s item={item}", flush=True)
        elif kind == "conversation.item.input_audio_transcription.delta":
            label = "FIRST DELTA" if item not in first_delta else "DELTA"
            first_delta.add(item)
            print(f"[RAW ASR {label}] +{now - started:.2f}s item={item} "
                  f"{event['delta']}", flush=True)
        elif kind == "conversation.item.input_audio_transcription.completed":
            print(f"[RAW ASR] +{now - started:.2f}s item={item} "
                  f"{event['transcript']}", flush=True)
            if item in stopped:
                print(f"[TIMING] speech_stopped event → final: "
                      f"{now - stopped.pop(item):.2f}s (not end-to-end latency)", flush=True)
            first_delta.discard(item)
            if file_mode:
                return
    raise RuntimeError("ASR connection closed; audio capture stopped.")


async def transcribe(audio: AsyncIterator[bytes], api_key: str,
                     file_mode: bool = False, final_timeout: float = 30) -> None:
    async with connect(ASR_URL, additional_headers={
        "Authorization": f"Bearer {api_key}",
    }, max_size=2**22, open_timeout=15) as socket:
        await socket.send(json.dumps(session_update(file_mode)))
        async with asyncio.timeout(15):
            while True:
                event = json.loads(await socket.recv())
                check_error(event)
                if event["type"] == "session.updated":
                    break
        print(f"[ASR] Ready: {ASR_MODEL}. Streaming audio; Ctrl+C to stop.", flush=True)
        tasks = [asyncio.create_task(send_audio(socket, audio, file_mode)),
                 asyncio.create_task(print_transcripts(socket, file_mode))]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            if file_mode:
                # One file is one explicit turn; do not close at EOF before its final text.
                async with asyncio.timeout(final_timeout):
                    await tasks[0]
                    await tasks[1]
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
