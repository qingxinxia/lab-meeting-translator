from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ASR_MODEL = "gpt-live-transcribe"
MEETING_ASR_MODEL = "gpt-live-transcribe"
TEXT_TRANSLATION_MODEL = "gpt-4.1-mini"
ASR_URL = "wss://api.openai.com/v1/realtime?intent=transcription"
TRANSLATION_MODEL = "gpt-realtime-translate"
TRANSLATION_INPUT_MODEL = "gpt-realtime-whisper"
TRANSLATION_CLIENT_SECRET_URL = (
    "https://api.openai.com/v1/realtime/translations/client_secrets"
)
TRANSCRIPTION_CLIENT_SECRET_URL = "https://api.openai.com/v1/realtime/client_secrets"
SAMPLE_RATE = 24_000
CHUNK_MS = 100
ASR_DELAY = "low"
CLIENT_VAD_RMS = 0.003
CLIENT_VAD_PREFIX_MS = 300
CLIENT_VAD_SILENCE_MS = 700
COMPREHENSION_INTERVAL = 10  # Reserved for the next phase.
CONTEXT_SECONDS = 60
LLM_MODEL = None  # Choose only after ASR evaluation.

ASR_PROMPT = """A research meeting about indoor positioning and localization.
Participants speak Japanese and English and may switch languages within a sentence.
Transcribe only speech actually audible, preserving the spoken language and technical
terms. Do not translate, invent content, or turn silence into acknowledgments."""
ASR_KEYWORDS = [
    "indoor positioning", "indoor localization", "Wi-Fi", "Bluetooth", "BLE",
    "UWB", "RSSI", "CSI", "fingerprinting", "beacon", "anchor", "multipath",
    "NLOS", "time of flight", "TDoA", "angle of arrival", "trilateration",
    "IMU", "PDR", "SLAM", "Kalman filter", "particle filter", "localization error",
    "室内測位", "屋内測位", "位置推定", "測位誤差", "電波指紋", "基地局",
]
TEST_SENTENCES = [
    "OpenPack の leave-one-user-out で実験します。",
    "source dataset を追加して fine-tuning します。",
    "Macro-F1 で評価します。",
    "contrastive learning を使っています。",
]
