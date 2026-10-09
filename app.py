"""Terminal ASR and browser-based meeting translation entry point."""
import argparse
import asyncio
from contextlib import aclosing

from pathlib import Path

from audio import check_microphone, microphone_chunks, inspect_wav, wav_chunks, check_wav
from asr import transcribe
from config import OPENAI_API_KEY, TEST_SENTENCES


async def main() -> None:
    parser = argparse.ArgumentParser(description="Lab meeting microphone + raw ASR")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list-devices", action="store_true")
    mode.add_argument("--check-audio", action="store_true")
    mode.add_argument("--test-sentences", action="store_true")
    mode.add_argument("--audio-file", type=Path, help="Stream a mono PCM16 24 kHz WAV")
    mode.add_argument("--web", action="store_true", help="Run the meeting-style web UI")
    parser.add_argument("--dry-run", action="store_true", help="Check WAV locally without API")
    parser.add_argument("--device", type=int, help="Input device index")
    parser.add_argument("--seconds", type=float, default=10, help="Audio check duration")
    parser.add_argument("--host", default="127.0.0.1", help="Web UI bind address")
    parser.add_argument("--port", type=int, default=8000, help="Web UI port")
    args = parser.parse_args()
    if args.dry_run and not args.audio_file:
        parser.error("--dry-run requires --audio-file")
    if args.audio_file and args.device is not None:
        parser.error("--device cannot be used with --audio-file")
    if args.web:
        import uvicorn

        config = uvicorn.Config("webapp:app", host=args.host, port=args.port, log_level="info")
        print(f"[WEB] Open http://{args.host}:{args.port}", flush=True)
        await uvicorn.Server(config).serve()
        return
    if args.list_devices:
        import sounddevice as sd

        print(sd.query_devices())
        return
    if args.test_sentences:
        for number, sentence in enumerate(TEST_SENTENCES, 1):
            print(f"{number}. {sentence}")
        return
    if args.check_audio:
        if args.seconds <= 0:
            parser.error("--seconds must be positive")
        await check_microphone(args.seconds, args.device)
        return
    if args.audio_file:
        duration = inspect_wav(args.audio_file)
        if args.dry_run:
            await check_wav(args.audio_file)
            return
        if duration < 0.1:
            parser.error("ASR file input must contain at least 100 ms of audio")
    if not OPENAI_API_KEY:
        parser.exit(2, "Missing OPENAI_API_KEY. Set it in .env; see .env.example.\n")
    source = wav_chunks(args.audio_file) if args.audio_file else microphone_chunks(args.device)
    async with aclosing(source) as audio:
        await transcribe(audio, OPENAI_API_KEY, file_mode=bool(args.audio_file))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
