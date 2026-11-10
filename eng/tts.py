"""Text-to-speech for OEL.

Three engines:
  browser  - the client uses speechSynthesis (best: word-boundary events)
  gtts     - Google Translate TTS, needs network, always available
  piper    - fully offline neural voice, downloads one model on first run

Playback rate is applied server-side with ffmpeg ``atempo`` so every engine
can be slowed down for shadowing (100-120 wpm) or sped up.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "tts"
PIPER_DIR = ROOT / ".cache" / "piper"
PIPER_VOICE = "en_US-lessac-medium"
_HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/"

_download_lock = threading.Lock()
_voice_state = {"ready": False, "downloading": False, "error": None}


def ffmpeg_bin() -> str | None:
    return shutil.which("ffmpeg")


def piper_bin() -> str | None:
    candidate = Path(sys.executable).with_name("piper")
    if candidate.exists():
        return str(candidate)
    return shutil.which("piper")


def voice_paths() -> tuple[Path, Path]:
    return PIPER_DIR / f"{PIPER_VOICE}.onnx", PIPER_DIR / f"{PIPER_VOICE}.onnx.json"


def available() -> dict[str, Any]:
    onnx, cfg = voice_paths()
    return {
        "gtts": True,
        "piper": piper_bin() is not None,
        "piper_voice": bool(onnx.exists() and cfg.exists()),
        "piper_voice_state": dict(_voice_state),
        "ffmpeg": bool(ffmpeg_bin()),
    }


def _download_voice() -> None:
    with _download_lock:
        if _voice_state["ready"] or _voice_state["downloading"]:
            return
        _voice_state["downloading"] = True
        _voice_state["error"] = None
    PIPER_DIR.mkdir(parents=True, exist_ok=True)
    onnx, cfg = voice_paths()
    try:
        for url, dest in ((_HF + f"{PIPER_VOICE}.onnx", onnx),
                          (_HF + f"{PIPER_VOICE}.onnx.json", cfg)):
            if dest.exists() and dest.stat().st_size > 1024:
                continue
            req = urllib.request.Request(url, headers={"User-Agent": "english-lab-local/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as fh:
                shutil.copyfileobj(resp, fh)
        _voice_state["ready"] = True
    except Exception as exc:  # noqa: BLE001 - reported through /api/health
        _voice_state["error"] = str(exc)
    finally:
        _voice_state["downloading"] = False


def ensure_voice_async() -> None:
    """Kick off the one-time piper voice download in the background."""
    if piper_bin() is None:
        return
    onnx, cfg = voice_paths()
    if onnx.exists() and cfg.exists():
        _voice_state["ready"] = True
        return
    threading.Thread(target=_download_voice, daemon=True).start()


def ensure_voice_sync() -> None:
    onnx, cfg = voice_paths()
    if onnx.exists() and cfg.exists():
        _voice_state["ready"] = True
        return
    _download_voice()


def _synth_gtts(text: str) -> tuple[bytes, str]:
    from gtts import gTTS

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "speech.mp3"
        gTTS(text=text, lang="en", tld="com").save(str(out))
        return out.read_bytes(), "audio/mpeg"


def _synth_piper(text: str) -> tuple[bytes, str]:
    ensure_voice_sync()
    onnx, cfg = voice_paths()
    binary = piper_bin()
    if not binary or not onnx.exists():
        raise RuntimeError("piper voice model is not ready")

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.txt"
        out = Path(tmp) / "out.wav"
        src.write_text(text + "\n", encoding="utf-8")
        cmd = [binary, "-m", str(onnx), "-c", str(cfg), "-i", str(src), "-f", str(out)]
        proc = subprocess.run(cmd, capture_output=True, timeout=120)
        if proc.returncode != 0 or not out.exists() or out.stat().st_size < 128:
            raise RuntimeError(proc.stderr.decode(errors="replace")[-400:] or "piper failed")
        return out.read_bytes(), "audio/wav"


def _atempo_chain(value: float) -> str:
    """ffmpeg atempo only accepts 0.5-2.0 per instance; split if needed."""
    value = max(0.25, min(4.0, value))
    factors: list[float] = []
    while value < 0.5:
        factors.append(0.5)
        value /= 0.5
    while value > 2.0:
        factors.append(2.0)
        value /= 2.0
    factors.append(value)
    return ",".join(f"atempo={factor:.3f}" for factor in factors)


def _probe_sample_rate(src: Path) -> int:
    ff = ffmpeg_bin()
    if not ff:
        return 22050
    proc = subprocess.run(
        [ff.replace("ffmpeg", "ffprobe") if ff.endswith("ffmpeg") else "ffprobe",
         "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate", "-of", "default=nw=1:nk=1", str(src)],
        capture_output=True, text=True,
    )
    try:
        return int(proc.stdout.strip().splitlines()[0])
    except (ValueError, IndexError, AttributeError):
        return 22050


_filter_cache: dict[str, bool] = {}


def _has_filter(name: str) -> bool:
    if name in _filter_cache:
        return _filter_cache[name]
    ff = ffmpeg_bin()
    if not ff:
        _filter_cache[name] = False
        return False
    proc = subprocess.run([ff, "-hide_banner", "-filters"], capture_output=True, text=True)
    found = any(line.split()[1:2] == [name] for line in proc.stdout.splitlines() if line.strip())
    _filter_cache[name] = found
    return found


def _apply_effects(src: Path, dst: Path, rate: float, pitch: float) -> bool:
    """Pitch shift (formant-preserved) + tempo change in one ffmpeg pass."""
    ff = ffmpeg_bin()
    if not ff:
        return False
    needs_tempo = abs(rate - 1.0) >= 0.01
    needs_pitch = abs(pitch - 1.0) >= 0.01
    if not needs_tempo and not needs_pitch:
        return False
    if _has_filter("rubberband"):
        filters = [f"rubberband=pitch={pitch:.4f}:tempo={rate:.4f}:formant=preserved"]
    else:
        filters = []
        if needs_pitch:
            sample_rate = _probe_sample_rate(src)
            filters.append(f"asetrate={sample_rate}*{pitch:.4f}")
            filters.append(f"aresample={sample_rate}")
            filters.append(_atempo_chain(1.0 / pitch))
        if needs_tempo:
            filters.append(_atempo_chain(rate))
    proc = subprocess.run(
        [ff, "-y", "-loglevel", "error", "-i", str(src),
         "-filter:a", ",".join(filters), "-q:a", "4", str(dst)],
        capture_output=True,
    )
    return proc.returncode == 0 and dst.exists() and dst.stat().st_size > 0


def _cache_key(engine: str, text: str, rate: float, pitch: float = 1.0) -> Path:
    digest = hashlib.sha1(f"v2|{engine}|{rate:.2f}|{pitch:.2f}|{text}".encode()).hexdigest()
    return CACHE / f"{digest}.bin"


def _split_for_tts(text: str, limit: int = 400) -> list[str]:
    """Split long text into sentence-safe pieces (engines have request limits)."""
    from . import textutil

    sentences = textutil.split_sentences(text) or [text]
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit)
            if cut <= 0:
                cut = limit
            piece, sentence = sentence[:cut].strip(), sentence[cut:].strip()
            if piece:
                parts.append(piece)
        if not sentence:
            continue
        if current and len(current) + 1 + len(sentence) > limit:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts or [text]


def _concat_wav(blobs: list[bytes]) -> bytes:
    import io
    import wave

    out = io.BytesIO()
    writer = None
    try:
        for blob in blobs:
            with wave.open(io.BytesIO(blob), "rb") as reader:
                if writer is None:
                    writer = wave.open(out, "wb")
                    writer.setnchannels(reader.getnchannels())
                    writer.setsampwidth(reader.getsampwidth())
                    writer.setframerate(reader.getframerate())
                writer.writeframes(reader.readframes(reader.getnframes()))
    finally:
        if writer is not None:
            writer.close()
    return out.getvalue()


def _concat_audio(blobs: list[bytes]) -> bytes:
    ff = ffmpeg_bin()
    if not ff:
        raise RuntimeError("ffmpeg diperlukan untuk menggabungkan audio")
    with tempfile.TemporaryDirectory() as tmp:
        files = []
        for i, blob in enumerate(blobs):
            path = Path(tmp) / f"{i:04d}.mp3"
            path.write_bytes(blob)
            files.append(path)
        listing = Path(tmp) / "list.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in files), encoding="utf-8")
        out = Path(tmp) / "joined.mp3"
        proc = subprocess.run(
            [ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(listing), "-c:a", "libmp3lame", "-q:a", "4", str(out)],
            capture_output=True,
        )
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError(proc.stderr.decode(errors="replace")[-300:] or "concat gagal")
        return out.read_bytes()


def _synth_text(name: str, text: str) -> tuple[bytes, str]:
    segments = _split_for_tts(text)
    if len(segments) <= 1:
        return _synth_piper(text) if name == "piper" else _synth_gtts(text)
    blobs: list[bytes] = []
    mimes: set[str] = set()
    for segment in segments:
        blob, mime = _synth_piper(segment) if name == "piper" else _synth_gtts(segment)
        blobs.append(blob)
        mimes.add(mime)
    if mimes == {"audio/wav"}:
        return _concat_wav(blobs), "audio/wav"
    return _concat_audio(blobs), "audio/mpeg"


def synth(text: str, engine: str = "auto", rate: float = 1.0,
          pitch: float = 1.0) -> tuple[bytes, str, str]:
    """Returns (audio_bytes, mime, engine_used). Raises RuntimeError on failure."""
    text = (text or "").strip()
    if not text:
        raise RuntimeError("empty text")
    if len(text) > 6000:
        text = text[:6000]

    engines = [engine]
    if engine == "auto":
        engines = ["piper", "gtts"]

    last_error = "no engine"
    for name in engines:
        if name == "browser":
            raise RuntimeError("browser engine removed; use piper or gtts")
        if name == "piper" and piper_bin() is None:
            last_error = "piper not installed"
            continue
        if name not in {"piper", "gtts"}:
            last_error = f"unknown engine {name}"
            continue

        cache = _cache_key(name, text, rate, pitch)
        if cache.exists() and cache.stat().st_size > 0:
            cached = cache.read_bytes()
            return cached, _mime_of(cached), name

        try:
            raw, mime = _synth_text(name, text)
            if ffmpeg_bin() and (abs(rate - 1.0) >= 0.01 or abs(pitch - 1.0) >= 0.01):
                with tempfile.TemporaryDirectory() as tmp:
                    src = Path(tmp) / "a_in"
                    src.write_bytes(raw)
                    dst = Path(tmp) / "a_out.mp3"
                    if _apply_effects(src, dst, rate, pitch):
                        raw, mime = dst.read_bytes(), "audio/mpeg"
            CACHE.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(raw)
            return raw, mime, name
        except Exception as exc:  # noqa: BLE001 - engine falls back to the next one
            last_error = f"{name}: {exc}"

    raise RuntimeError(last_error)


def _mime_of(data: bytes) -> str:
    if data[:3] == b"ID3" or data[:2] == b"\xff\xfb":
        return "audio/mpeg"
    if data[:4] == b"RIFF":
        return "audio/wav"
    if data[:4] == b"OggS":
        return "audio/ogg"
    return "application/octet-stream"


def preload() -> None:
    """Warm the cache with a short phrase so the first click is instant."""
    try:
        synth("Hello, this is your English practice voice.", engine="auto", rate=1.0)
    except Exception:  # noqa: BLE001
        pass
