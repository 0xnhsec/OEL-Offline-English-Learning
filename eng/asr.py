"""Speech-to-text: ffmpeg conversion + faster-whisper (offline).

The browser uploads MediaRecorder output (webm/ogg/mp4); ffmpeg turns it into
16 kHz mono WAV which is what Whisper expects. FFmpeg itself does NOT do
speech recognition - it only prepares and converts audio.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

MODEL_NAME = os.environ.get("ARDX_ASR_MODEL", "base.en")

_model = None
_lock = threading.Lock()
_state: dict[str, Any] = {"ready": False, "loading": False, "error": None, "model": MODEL_NAME}


class ASRUnavailable(RuntimeError):
    """Raised when the server-side recogniser cannot be used."""


def installed() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def available() -> dict[str, Any]:
    return {
        "engine": "faster-whisper",
        "installed": installed(),
        "model": MODEL_NAME,
        "ready": _state["ready"],
        "loading": _state["loading"],
        "error": _state["error"],
        "ffmpeg": bool(shutil.which("ffmpeg")),
    }


def _load():
    global _model
    with _lock:
        if _model is not None:
            return _model
        _state["loading"] = True
        _state["error"] = None
        try:
            from faster_whisper import WhisperModel

            _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
            _state["ready"] = True
            return _model
        except Exception as exc:  # noqa: BLE001
            _state["error"] = str(exc)
            raise
        finally:
            _state["loading"] = False


def prefetch() -> None:
    """Download/load the model once in the background at server start."""
    if not installed():
        return

    def _run() -> None:
        try:
            _load()
        except Exception:  # noqa: BLE001 - surfaced through /api/health
            pass

    threading.Thread(target=_run, daemon=True).start()


def to_wav(src: Path, dst: Path) -> Path:
    ff = shutil.which("ffmpeg")
    if not ff:
        raise ASRUnavailable("ffmpeg tidak ditemukan di PATH")
    proc = subprocess.run(
        [ff, "-y", "-loglevel", "error", "-i", str(src),
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)],
        capture_output=True,
    )
    if proc.returncode != 0 or not dst.exists():
        detail = proc.stderr.decode(errors="replace")[-400:]
        raise ASRUnavailable(f"konversi audio gagal: {detail}")
    return dst


def _read_wav(path: Path):
    """Decode the 16 kHz mono PCM we produced with ffmpeg into a float32 array.

    faster_whisper's own decoder goes through PyAV, whose ``open()`` signature
    changes between major versions (av 19 dropped ``metadata_errors``), so we
    decode ourselves - we already control the WAV format via ffmpeg.
    """
    import wave

    import numpy as np

    try:
        with wave.open(str(path), "rb") as handle:
            if handle.getsampwidth() != 2 or handle.getnchannels() != 1:
                raise ASRUnavailable("format WAV tidak didukung (butuh 16-bit mono)")
            frames = handle.readframes(handle.getnframes())
    except wave.Error as exc:
        raise ASRUnavailable(f"WAV tidak terbaca: {exc}") from exc
    audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if audio.size < 1600:                       # < 0.1 s of audio
        raise ASRUnavailable("rekaman terlalu pendek / hening")
    return audio


def _levels(audio) -> dict[str, float]:
    """Simple loudness diagnostics so the UI can tell silence from a failed ASR."""
    import math

    import numpy as np

    if not audio.size:
        return {"peak_db": -120.0, "rms_db": -120.0}
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(np.square(audio))))

    def db(value: float) -> float:
        return round(20.0 * math.log10(max(value, 1e-9)), 1)

    return {"peak_db": db(peak), "rms_db": db(rms)}


def _normalize(audio):
    """Boost quiet recordings before ASR (keeps silence untouched)."""
    import numpy as np

    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if 1e-4 < peak < 0.2:
        audio = (audio * (0.9 / peak)).astype("float32")
    return audio


def _collect(model, audio, language: str, vad: bool) -> tuple[str, list[dict[str, Any]], Any]:
    segments, info = model.transcribe(
        audio,
        language=language or "en",
        word_timestamps=True,
        vad_filter=vad,
        beam_size=5,
        condition_on_previous_text=False,
        initial_prompt=".",
    )
    words: list[dict[str, Any]] = []
    parts: list[str] = []
    for segment in segments:
        parts.append(segment.text.strip())
        for word in segment.words or []:
            token = word.word.strip()
            if token:
                words.append({
                    "w": token,
                    "s": round(float(word.start), 3),
                    "e": round(float(word.end), 3),
                })
    return " ".join(p for p in parts if p).strip(), words, info


def transcribe(data: bytes, filename: str = "audio", language: str = "en") -> dict[str, Any]:
    """Upload bytes -> WAV -> whisper -> {text, words, engine, model}."""
    if not installed():
        raise ASRUnavailable(
            "faster-whisper belum terpasang. Jalankan: pip install faster-whisper"
        )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        suffix = Path(filename or "audio").suffix or ".webm"
        src = tmp_path / f"input{suffix}"
        src.write_bytes(data)
        wav = to_wav(src, tmp_path / "input.wav")

        try:
            model = _load()
        except Exception as exc:  # noqa: BLE001
            raise ASRUnavailable(f"model ASR gagal dimuat: {exc}") from exc

        try:
            audio = _read_wav(wav)
        except ASRUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ASRUnavailable(f"gagal decode audio: {exc}") from exc

        levels = _levels(audio)
        audio = _normalize(audio)
        text, words, info = _collect(model, audio, language, vad=True)
        if not text:
            # Quiet speech is sometimes dropped by the VAD; retry once without it.
            text, words, info = _collect(model, audio, language, vad=False)
        if text and not any(ch.isalnum() for ch in text):
            # Whisper sometimes hallucinates punctuation on silent/noisy audio.
            text, words = "", []

        return {
            "text": text,
            "words": words,
            "language": info.language,
            "language_probability": round(float(info.language_probability or 0), 3),
            "duration": round(float(info.duration or 0), 3),
            "audio": levels,
            "engine": "faster-whisper",
            "model": MODEL_NAME,
        }
