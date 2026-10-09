import asyncio
from collections.abc import AsyncIterator
from contextlib import aclosing
import time
import wave
from pathlib import Path

import numpy as np

from config import CHUNK_MS, SAMPLE_RATE


async def microphone_chunks(device: int | None = None) -> AsyncIterator[bytes]:
    """Yield mono, little-endian PCM16 at 24 kHz; never save audio to disk."""
    import sounddevice as sd

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=30)
    failure = None

    def enqueue(chunk: bytes, status: str) -> None:
        nonlocal failure
        if status:
            failure = RuntimeError(f"Microphone stream: {status}")
        elif queue.full():
            failure = RuntimeError("Audio queue full: transmission cannot keep up.")
        else:
            queue.put_nowait(chunk)

    def callback(data, frames, timing, status) -> None:
        loop.call_soon_threadsafe(enqueue, bytes(data), str(status))

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="int16",
        blocksize=SAMPLE_RATE * CHUNK_MS // 1000,
        device=device, callback=callback,
    ):
        print("[AUDIO] Microphone active: 24000 Hz, mono PCM16", flush=True)
        while True:
            chunk = await asyncio.wait_for(queue.get(), timeout=5)
            if failure:
                raise failure
            yield chunk


async def check_microphone(seconds: float, device: int | None = None) -> None:
    chunks = 0
    byte_count = 0
    peak = 0.0
    started = time.monotonic()
    async with aclosing(microphone_chunks(device)) as audio:
        async for chunk in audio:
            chunks += 1
            byte_count += len(chunk)
            samples = np.frombuffer(chunk, dtype="<i2").astype(np.float32) / 32768
            peak = max(peak, float(np.max(np.abs(samples))))
            if chunks % 10 == 0:
                rms = float(np.sqrt(np.mean(samples ** 2)))
                print(f"[AUDIO] chunks={chunks} rms={rms:.5f} peak={peak:.5f}", flush=True)
            if byte_count / (SAMPLE_RATE * 2) >= seconds:
                break
    print(f"[AUDIO] Captured {byte_count / (SAMPLE_RATE * 2):.1f}s "
          f"in {time.monotonic() - started:.1f}s; chunks={chunks}; peak={peak:.5f}")
    if peak == 0:
        print("[AUDIO] All samples were zero. Check microphone permission/input.")


def inspect_wav(path: Path) -> float:
    """Reject unsupported formats before opening an API session."""
    with wave.open(str(path), "rb") as recording:
        if (recording.getnchannels(), recording.getsampwidth(),
                recording.getframerate(), recording.getcomptype()) != (1, 2, SAMPLE_RATE, "NONE"):
            raise ValueError("WAV must be uncompressed mono PCM16 at 24000 Hz.")
        if recording.getnframes() == 0:
            raise ValueError("WAV contains no audio frames.")
        return recording.getnframes() / SAMPLE_RATE


async def wav_chunks(path: Path) -> AsyncIterator[bytes]:
    inspect_wav(path)
    frames_per_chunk = SAMPLE_RATE * CHUNK_MS // 1000
    sent_frames = 0
    started = time.monotonic()
    with wave.open(str(path), "rb") as recording:
        while chunk := recording.readframes(frames_per_chunk):
            sent_frames += len(chunk) // 2
            # Pace against a fixed clock so processing time does not accumulate.
            await asyncio.sleep(max(0, started + sent_frames / SAMPLE_RATE - time.monotonic()))
            yield chunk
        if sent_frames != recording.getnframes():
            raise ValueError("WAV is truncated: fewer frames than its header declares.")


async def check_wav(path: Path) -> None:
    duration = inspect_wav(path)
    started = time.monotonic()
    chunks = byte_count = 0
    async for chunk in wav_chunks(path):
        chunks += 1
        byte_count += len(chunk)
    print(f"[FILE CHECK] duration={duration:.3f}s chunks={chunks} bytes={byte_count} "
          f"elapsed={time.monotonic() - started:.3f}s; no API or microphone used")
