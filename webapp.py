"""Local web server for the meeting-style realtime translation UI."""

import asyncio
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request as WebRequest
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from topics import Glossaries, PROFILES
from evidence import ReviewInput, review_segments, analyze_slide
from summaries import SummaryInput, MaterialInput, summarize, analyze_material

from config import (
    ASR_KEYWORDS,
    ASR_PROMPT,
    MEETING_ASR_MODEL,
    OPENAI_API_KEY,
    TRANSCRIPTION_CLIENT_SECRET_URL,
    TRANSLATION_CLIENT_SECRET_URL,
    TRANSLATION_INPUT_MODEL,
    TRANSLATION_MODEL,
)


STATIC_DIR = Path(__file__).with_name("static")
TARGET_LANGUAGES = {
    "es": "Español",
    "pt": "Português",
    "fr": "Français",
    "ja": "日本語",
    "ru": "Русский",
    "zh": "中文",
    "de": "Deutsch",
    "ko": "한국어",
    "hi": "हिन्दी",
    "id": "Bahasa Indonesia",
    "vi": "Tiếng Việt",
    "it": "Italiano",
    "en": "English",
}


class SessionRequest(BaseModel):
    target_language: str = "zh"


class TranscriptionSessionRequest(BaseModel):
    source_language: str = "auto"


def _safety_identifier() -> str:
    """Use a stable pseudonymous identifier without sending local user details."""
    return hashlib.sha256(b"lab-meeting-translator-local-user").hexdigest()


def _openai_error(payload: bytes, fallback: str) -> str:
    try:
        body = json.loads(payload)
        return body.get("error", {}).get("message") or fallback
    except (json.JSONDecodeError, AttributeError):
        return fallback


def _post_client_secret(url: str, body: dict) -> dict:
    encoded = json.dumps(body).encode("utf-8")
    request = Request(
        url,
        data=encoded,
        method="POST",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
            "OpenAI-Safety-Identifier": _safety_identifier(),
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        detail = _openai_error(exc.read(), f"OpenAI API returned HTTP {exc.code}")
        raise HTTPException(status_code=502, detail=detail) from exc
    except URLError as exc:
        raise HTTPException(status_code=502, detail=f"Cannot reach OpenAI API: {exc.reason}") from exc
    except (TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="Invalid or timed-out OpenAI API response") from exc


def _create_client_secret(target_language: str) -> dict:
    return _post_client_secret(TRANSLATION_CLIENT_SECRET_URL, {
        "session": {
            "model": TRANSLATION_MODEL,
            "audio": {
                "input": {
                    "transcription": {"model": TRANSLATION_INPUT_MODEL},
                    # The normal path is a laptop/conference-room microphone.
                    "noise_reduction": {"type": "far_field"},
                },
                "output": {"language": target_language},
            },
        }
    })


def _source_prompt(source_language: str) -> str:
    if source_language == "auto":
        return ASR_PROMPT
    language_name = TARGET_LANGUAGES[source_language]
    if source_language == "ja":
        return ASR_PROMPT
    return (
        f"This is a research lab meeting spoken in {language_name}. "
        "Transcribe speech faithfully in its original language; do not translate. "
        "The topic is indoor positioning and localization."
    )


def _create_transcription_client_secret(source_language: str) -> dict:
    transcription = {
        "model": MEETING_ASR_MODEL,
        "prompt": _source_prompt(source_language),
        "keywords": ASR_KEYWORDS,
    }
    if source_language != "auto":
        transcription["languages"] = [source_language]
    return _post_client_secret(TRANSCRIPTION_CLIENT_SECRET_URL, {
        "session": {
            "type": "transcription",
            "audio": {
                "input": {
                    "noise_reduction": {"type": "far_field"},
                    "transcription": transcription,
                    # Legacy clients still own explicit audio-turn commits.
                    "turn_detection": None,
                }
            },
        }
    })


app = FastAPI(title="LiveBridge Meeting Translator", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
glossaries = Glossaries()


class TermRequest(BaseModel):
    term: str = Field(min_length=1, max_length=120)
    ja: str = ""
    zh: str = ""
    aliases: list[str] = Field(default_factory=list, max_length=20)
    notes: str = ""
    status: str = "confirmed"


def check_topic(topic):
    if topic not in PROFILES: raise HTTPException(404, "Unknown meeting topic")


def same_origin(request):
    origin=request.headers.get('origin')
    if origin and origin not in {f"http://{request.headers.get('host')}",f"https://{request.headers.get('host')}"}:
        raise HTTPException(403,'Cross-origin writes are not allowed')


class SlideRequest(BaseModel):
    image: str = Field(max_length=8_400_000)
    consent: bool = False
    topic: str = 'indoor'


# Separate bounded pool: long file/summary requests cannot occupy audio translation workers.
from concurrent.futures import ThreadPoolExecutor
analysis_pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='meeting-analysis')
analysis_slots=asyncio.Semaphore(2)


async def analysis_call(function,*args):
    if analysis_slots.locked():raise HTTPException(429,'辅助分析忙，请稍后重试；录音不受影响')
    async with analysis_slots:
        return await asyncio.get_running_loop().run_in_executor(analysis_pool,function,*args)


@app.post('/api/summaries')
async def summary_endpoint(payload: SummaryInput,request: WebRequest):
    same_origin(request);check_topic(payload.topic)
    if payload.target not in TARGET_LANGUAGES:raise HTTPException(400,'Unsupported target language')
    try:return await analysis_call(summarize,payload,glossaries,TARGET_LANGUAGES[payload.target])
    except HTTPException:raise
    except ValueError as error:raise HTTPException(400,str(error)) from error
    except Exception as error:raise HTTPException(502,'总结失败，原文保留：'+str(error)) from error


@app.post('/api/evidence/material')
async def material_endpoint(payload: MaterialInput,request: WebRequest):
    same_origin(request);check_topic(payload.topic)
    if not payload.consent:raise HTTPException(400,'发送材料到 OpenAI 需要明确同意')
    try:
        result=await analysis_call(analyze_material,payload)
        await asyncio.to_thread(glossaries.observe,payload.topic,' '.join(result['terms']),source_kind='material_unverified')
        return result
    except HTTPException:raise
    except ValueError as error:raise HTTPException(400,str(error)) from error
    except Exception as error:raise HTTPException(502,'材料读取失败：'+str(error)) from error


@app.post('/api/evidence/slide')
async def slide_evidence(payload: SlideRequest,request: WebRequest):
    same_origin(request);check_topic(payload.topic)
    if not payload.consent:raise HTTPException(400,'上传照片到 OpenAI 需要明确同意')
    try:
        result=await analysis_call(analyze_slide,payload.image)
        await asyncio.to_thread(glossaries.observe,payload.topic,' '.join(result['terms']),source_kind='slide_unverified')
        return result
    except HTTPException:raise
    except ValueError as error:raise HTTPException(400,str(error)) from error
    except Exception as error:raise HTTPException(502,'照片分析失败，未修改字幕：'+str(error)) from error


@app.post('/api/evidence/review')
async def review_evidence(payload: ReviewInput,request: WebRequest):
    same_origin(request);check_topic(payload.topic)
    if payload.target not in TARGET_LANGUAGES:raise HTTPException(400,'Unsupported target language')
    try:return await analysis_call(review_segments,payload,glossaries,TARGET_LANGUAGES[payload.target])
    except HTTPException:raise
    except ValueError as error:raise HTTPException(400,str(error)) from error
    except Exception as error:raise HTTPException(502,'纠错分析失败，原始记录保留：'+str(error)) from error


@app.get("/api/topics")
async def topics():
    return {"topics": [{"id": key, "name": value["name"]} for key,value in PROFILES.items()]}


@app.get("/api/topics/{topic}/terms")
def terms(topic: str):
    check_topic(topic)
    rows=glossaries.list(topic)
    return {"topic":topic,"terms":rows,"database":f'{topic}.sqlite3',
            "counts":{status:sum(row['status']==status for row in rows) for status in ('confirmed','candidate','archived')}}


@app.put("/api/topics/{topic}/terms")
def save_term(topic: str, payload: TermRequest, request: WebRequest):
    check_topic(topic)
    origin=request.headers.get("origin")
    if origin and origin not in {f"http://{request.headers.get('host')}",f"https://{request.headers.get('host')}"}:
        raise HTTPException(403,"Cross-origin writes are not allowed")
    try: return glossaries.save(topic,**payload.model_dump())
    except ValueError as error: raise HTTPException(400,str(error)) from error


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.websocket("/ws/meeting")
async def meeting_socket(socket: WebSocket):
    from meeting import MeetingSession
    # Browser sessions must originate from this local application.
    origin = socket.headers.get("origin")
    if origin and origin not in {f"http://{socket.headers.get('host')}", f"https://{socket.headers.get('host')}"}:
        await socket.close(code=1008); return
    target = socket.query_params.get("target", "zh")
    topic = socket.query_params.get("topic", "indoor")
    audio_mode=socket.query_params.get('audio_mode','room')
    if target not in TARGET_LANGUAGES or topic not in PROFILES or audio_mode not in {'room','raw','browser','adaptive'}:
        await socket.close(code=1008); return
    await socket.accept()
    try:
        await MeetingSession(socket, TARGET_LANGUAGES[target], topic, glossaries,
                             audio_mode=audio_mode).run()
    except WebSocketDisconnect:
        return
    except Exception as error:
        try:
            await socket.send_json({"type": "error", "message": str(error)})
        except (RuntimeError, WebSocketDisconnect):
            pass
    finally:
        try: await socket.close()
        except (RuntimeError, WebSocketDisconnect): pass


@app.get("/api/debug-fixture")
async def debug_fixture():
    path = Path(__file__).parent / "debug_artifacts" / "mixed.wav"
    if not path.exists():
        raise HTTPException(404, "Run debug_modules.py --generate first")
    return FileResponse(path, media_type="audio/wav")


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "api_key_configured": bool(OPENAI_API_KEY),
        "model": f"{MEETING_ASR_MODEL} → gpt-4.1-mini",
    }


@app.get("/api/languages")
async def languages() -> dict:
    return {"languages": TARGET_LANGUAGES}


@app.post("/api/session")
async def create_session(payload: SessionRequest) -> dict:
    language = payload.target_language.lower()
    if language not in TARGET_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported target language")
    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured in .env",
        )
    return await asyncio.to_thread(_create_client_secret, language)


@app.post("/api/transcription-session")
async def create_transcription_session(payload: TranscriptionSessionRequest) -> dict:
    language = payload.source_language.lower()
    if language != "auto" and language not in TARGET_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported source language")
    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured in .env",
        )
    return await asyncio.to_thread(_create_transcription_client_secret, language)
