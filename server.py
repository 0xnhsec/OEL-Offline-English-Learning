"""OEL — Offline English Learning · local web server.

Run with:  ./run.sh        (http://127.0.0.1:8765)

Endpoints
  GET  /api/health     engine status (tts / asr / ai)
  POST /api/upload     text file  -> shadowing chunks
  POST /api/parse      pasted text -> shadowing chunks
  POST /api/tts        text + rate -> audio bytes
  POST /api/transcribe audio file -> transcript + word timings (whisper)
  POST /api/compare    reference + transcript -> word-level alignment
  POST /api/analyze    writing or transcript -> Fix / Why / Try feedback
  POST /api/study/parse  practice set + answer key -> questions
  POST /api/auth/login /register, GET /api/auth/me, POST /api/auth/logout
  POST /api/auth/avatar  upload foto profil, DELETE = hapus foto
  GET  /api/modules, /api/modules/{id}  bundled question bank
  GET  /api/leaderboard, POST /api/progress
  GET/POST /api/settings  local preferences (engines, chunking)
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from eng import accounts, asr, coach, study, textutil, tts

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
QUIZ_DIR = ROOT / "oel-quiz"
SETTINGS_PATH = ROOT / ".settings.json"

MAX_UPLOAD_BYTES = 512 * 1024          # text files
MAX_AUDIO_BYTES = 12 * 1024 * 1024     # recordings
STARTED_AT = time.time()

DEFAULT_SETTINGS: dict[str, Any] = {
    "ttsEngine": "auto",
    "asrMode": "auto",
    "rate": 1.0,
    "pitch": 1.0,
    "wholeText": False,
    "maxSentences": 2,
    "maxWords": 30,
}


def load_settings() -> dict[str, Any]:
    data = dict(DEFAULT_SETTINGS)
    try:
        if SETTINGS_PATH.exists():
            data.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        pass
    return data


def save_settings(update: dict[str, Any]) -> dict[str, Any]:
    data = load_settings()
    for key, value in update.items():
        if key in DEFAULT_SETTINGS:
            data[key] = value
    try:
        SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"gagal menyimpan settings: {exc}")
    return data


def _settings_view() -> dict[str, Any]:
    return dict(load_settings())


@asynccontextmanager
async def lifespan(_: FastAPI):
    tts.ensure_voice_async()
    asr.prefetch()
    threading.Thread(target=tts.preload, daemon=True).start()
    yield


app = FastAPI(title="OEL — Offline English Learning", version="1.0", lifespan=lifespan)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _build_chunks(text: str, filename: str, max_sentences: int, max_words: int,
                  whole: bool = False) -> dict[str, Any]:
    if not text.strip():
        raise HTTPException(status_code=400, detail="teks kosong")
    if filename.lower().endswith((".srt", ".vtt")):
        text = textutil.strip_subtitles(text)
    text = textutil.clean_text(text)
    if not text:
        raise HTTPException(status_code=400, detail="tidak ada teks yang bisa dibaca di file ini")

    if whole:
        chunks = [{
            "index": 0,
            "text": text,
            "sentences": textutil.split_sentences(text) or [text],
            "words": len(textutil.tokenize(text)),
        }]
    else:
        max_sentences = max(1, min(int(max_sentences), 6))
        max_words = max(8, min(int(max_words), 120))
        chunks = textutil.chunk_text(text, max_sentences=max_sentences, max_words=max_words)
    if not chunks:
        raise HTTPException(status_code=400, detail="teks tidak menghasilkan satu kalimat pun")
    if len(chunks) > 500:
        chunks = chunks[:500]

    return {
        "filename": filename or "temp.txt",
        "text": text,
        "chunks": chunks,
        "stats": {
            "chars": len(text),
            "words": len(textutil.tokenize(text)),
            "sentences": len(textutil.split_sentences(text)),
            "chunks": len(chunks),
        },
    }


# --------------------------------------------------------------------------- #
# static
# --------------------------------------------------------------------------- #

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/learn")
async def learn_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "learn.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "uptime": round(time.time() - STARTED_AT, 1),
        "tts": tts.available(),
        "asr": asr.available(),
        "ai": {
            "provider": "local-rules",
            "model": None,
            "hasKey": False,
            "keySource": "none",
            "note": "engine grammar lokal, tanpa AI cloud",
        },
        "speechApiHint": "browser",
    }


# --------------------------------------------------------------------------- #
# text in
# --------------------------------------------------------------------------- #

@app.post("/api/upload")
async def upload(file: UploadFile = File(...),
                 max_sentences: int = 2, max_words: int = 30,
                 whole: int = 0) -> dict[str, Any]:
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file terlalu besar (maks 512 KB)")
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", errors="replace")
    return _build_chunks(text, file.filename or "upload.txt", max_sentences, max_words,
                         whole=bool(whole))


@app.post("/api/parse")
async def parse(request: Request) -> dict[str, Any]:
    body = await request.json()
    return _build_chunks(
        str(body.get("text") or ""),
        str(body.get("filename") or "pasted.txt"),
        int(body.get("maxSentences") or 2),
        int(body.get("maxWords") or 30),
        whole=bool(body.get("whole") if "whole" in body else load_settings().get("wholeText")),
    )


# --------------------------------------------------------------------------- #
# audio
# --------------------------------------------------------------------------- #

@app.post("/api/tts")
async def api_tts(request: Request) -> Response:
    body = await request.json()
    text = str(body.get("text") or "").strip()
    engine = str(body.get("engine") or "auto")
    rate = float(body.get("rate") or 1.0)
    rate = max(0.5, min(2.0, rate))
    pitch = float(body.get("pitch") or 1.0)
    pitch = max(0.85, min(1.15, pitch))
    if not text:
        return JSONResponse(status_code=400, content={"error": "text kosong"})
    try:
        audio, mime, used = tts.synth(text, engine=engine, rate=rate, pitch=pitch)
    except RuntimeError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})
    return Response(
        content=audio,
        media_type=mime,
        headers={"X-TTS-Engine": used, "Cache-Control": "max-age=86400"},
    )


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...), language: str = "en") -> JSONResponse:
    data = await file.read()
    if len(data) > MAX_AUDIO_BYTES:
        return JSONResponse(status_code=413, content={"error": "rekaman terlalu besar"})
    if not asr.installed():
        return JSONResponse(
            status_code=501,
            content={
                "error": "speech-to-text server belum tersedia",
                "hint": "pip install faster-whisper  (model dimuat otomatis saat pertama kali)",
            },
        )
    try:
        return JSONResponse(content=asr.transcribe(data, file.filename or "audio.webm",
                                                   language=language))
    except asr.ASRUnavailable as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": f"transcribe gagal: {exc}"})


# --------------------------------------------------------------------------- #
# feedback
# --------------------------------------------------------------------------- #

@app.post("/api/compare")
async def compare(request: Request) -> dict[str, Any]:
    body = await request.json()
    reference = str(body.get("reference") or "")
    hypothesis = str(body.get("hypothesis") or "")
    if not reference.strip():
        raise HTTPException(status_code=400, detail="reference kosong")
    result = textutil.align(reference, hypothesis)
    result["referenceText"] = reference
    result["hypothesisText"] = hypothesis
    return result


@app.post("/api/analyze")
async def analyze(request: Request) -> dict[str, Any]:
    body = await request.json()
    kind = str(body.get("kind") or "grammar")
    text = str(body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="teks kosong")
    reference = body.get("reference") or None
    return coach.analyze(kind=kind, text=text, reference=reference)


@app.post("/api/study/parse")
async def study_parse(request: Request) -> dict[str, Any]:
    body = await request.json()
    text = str(body.get("text") or "")
    filename = str(body.get("filename") or "study.txt")
    if not text.strip():
        raise HTTPException(status_code=400, detail="materi kosong")
    try:
        if text.lstrip().startswith(("{", "[")) or filename.lower().endswith(".json"):
            data = study.parse_json_set(text)
        else:
            data = study.parse_practice_set(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"JSON tidak valid: {exc}")
    if not data["questions"]:
        raise HTTPException(
            status_code=400,
            detail="tidak ada soal yang terbaca — cek format TXT ('1. [topik | level]', opsi A-D, ANSWER KEY) atau JSON",
        )
    data["filename"] = filename
    return data


# --------------------------------------------------------------------------- #
# accounts / learn 101
# --------------------------------------------------------------------------- #

def _bearer(request: Request) -> str:
    header = request.headers.get("authorization") or ""
    return header[7:].strip() if header.lower().startswith("bearer ") else ""


def _module_files() -> list[Path]:
    if not QUIZ_DIR.is_dir():
        return []
    return sorted(QUIZ_DIR.glob("*.json"))


def _module_summary(path: Path) -> dict[str, Any]:
    try:
        data = study.parse_json_set(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {"id": path.stem, "title": path.stem, "count": 0, "error": "tidak terbaca"}
    return {
        "id": path.stem,
        "title": data["title"],
        "count": data["count"],
        "difficulty": data["difficulty"],
        "file": path.name,
    }


@app.get("/api/modules")
async def modules() -> dict[str, Any]:
    items = [_module_summary(path) for path in _module_files()]
    return {"modules": items, "total": sum(item.get("count", 0) for item in items)}


@app.get("/api/modules/{module_id}")
async def module_detail(module_id: str) -> dict[str, Any]:
    if not module_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="id modul tidak valid")
    path = QUIZ_DIR / f"{module_id}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="modul tidak ditemukan")
    try:
        data = study.parse_json_set(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"modul tidak terbaca: {exc}")
    data["id"] = module_id
    return data


@app.post("/api/auth/register")
async def auth_register(request: Request) -> dict[str, Any]:
    body = await request.json()
    try:
        result = accounts.register(
            str(body.get("username") or ""),
            str(body.get("name") or ""),
            str(body.get("password") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@app.post("/api/auth/login")
async def auth_login(request: Request) -> dict[str, Any]:
    body = await request.json()
    try:
        return accounts.login(
            str(body.get("username") or ""),
            str(body.get("password") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


@app.get("/api/auth/me")
async def auth_me(request: Request) -> dict[str, Any]:
    user = accounts.user_for_token(_bearer(request))
    if not user:
        raise HTTPException(status_code=401, detail="belum login")
    return {"user": user}


@app.post("/api/auth/logout")
async def auth_logout(request: Request) -> dict[str, Any]:
    accounts.logout(_bearer(request))
    return {"ok": True}


@app.post("/api/auth/avatar")
async def auth_avatar(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
    blob = await file.read(accounts.MAX_AVATAR_BYTES + 1)
    try:
        user = accounts.set_avatar(_bearer(request), blob)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"user": user}


@app.delete("/api/auth/avatar")
async def auth_avatar_clear(request: Request) -> dict[str, Any]:
    try:
        user = accounts.clear_avatar(_bearer(request))
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"user": user}


@app.post("/api/progress")
async def progress(request: Request) -> dict[str, Any]:
    body = await request.json()
    try:
        user = accounts.record_progress(
            _bearer(request),
            str(body.get("set") or ""),
            int(body.get("correct") or 0),
            int(body.get("total") or 0),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"user": user}


@app.get("/api/leaderboard")
async def leaderboard() -> dict[str, Any]:
    return accounts.leaderboard()


# --------------------------------------------------------------------------- #
# settings
# --------------------------------------------------------------------------- #

@app.get("/api/settings")
async def get_settings() -> dict[str, Any]:
    return _settings_view()


@app.post("/api/settings")
async def post_settings(request: Request) -> dict[str, Any]:
    body = await request.json()
    allowed = {k: body[k] for k in
               ("ttsEngine", "asrMode", "rate", "maxSentences", "maxWords") if k in body}
    save_settings(allowed)
    return _settings_view()


accounts.AVATAR_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/avatars", StaticFiles(directory=str(accounts.AVATAR_DIR)), name="avatars")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
