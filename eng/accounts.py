"""Local accounts, sessions, progress and leaderboard for Learn 101.

Everything is stored in ``.users.json`` next to the app. Passwords are hashed
with PBKDF2-SHA256 (200k rounds + per-user salt); tokens are random and kept
server-side. Each account may upload its own profile picture; files land in
``.avatars/`` and are served from ``/avatars/<username>.<ext>``.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
USERS_PATH = ROOT / ".users.json"
AVATAR_DIR = ROOT / ".avatars"

_USERNAME = re.compile(r"^[A-Za-z0-9_.-]{3,24}$")
_SAFE = re.compile(r"[^A-Za-z0-9_.-]")
_lock = threading.Lock()

# Default account shipped with OEL — username and password are both "user".
DEFAULT_USER = {
    "username": "user",
    "name": "user",
    "password": "user",
}

# Pinned legendary profile: always rank 1, by design. Not a real account —
# it cannot be logged into and its picture is fixed to Assets/ayang.png.
FEATURED: dict[str, Any] = {
    "username": "noshiro",
    "name": "Noshiro",
    "points": 2790,
    "sets": 10,
    "accuracy": 1.0,
    "avatar": "/static/assets/ayang.png",
    "featured": True,
    "lockedAvatar": True,
    "bio": {
        "Name": "Ayanagi Noshiro (noun)",
        "Gender": "She",
        "Address": "Akita, Japan.",
    },
}

MAX_AVATAR_BYTES = 4 * 1024 * 1024
_IMAGE_EXT = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


def _empty() -> dict[str, Any]:
    return {"users": {}, "sessions": {}, "created": time.time()}


def _read() -> dict[str, Any]:
    if not USERS_PATH.exists():
        data = _empty()
        _seed(data)
        _write(data)
        return data
    try:
        data = json.loads(USERS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty()
    data.setdefault("users", {})
    data.setdefault("sessions", {})
    if _ensure_default(data):
        _write(data)
    return data


def _write(data: dict[str, Any]) -> None:
    tmp = USERS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(USERS_PATH)


def _make_user(username: str, name: str, password: str) -> dict[str, Any]:
    salt = secrets.token_hex(16)
    return {
        "username": username,
        "name": name,
        "salt": salt,
        "hash": _hash(password, salt),
        "created": time.time(),
        "progress": {},
    }


def _seed(data: dict[str, Any]) -> None:
    data["users"][DEFAULT_USER["username"].lower()] = _make_user(
        DEFAULT_USER["username"], DEFAULT_USER["name"], DEFAULT_USER["password"],
    )


def _ensure_default(data: dict[str, Any]) -> bool:
    """Keep the default ``user``/``user`` account available on older databases."""
    key = DEFAULT_USER["username"].lower()
    if key in data["users"]:
        return False
    data["users"][key] = _make_user(
        DEFAULT_USER["username"], DEFAULT_USER["name"], DEFAULT_USER["password"],
    )
    return True


def _public(user: dict[str, Any]) -> dict[str, Any]:
    progress = user.get("progress", {})
    best_total = sum(int(item.get("best", 0)) for item in progress.values())
    question_total = sum(int(item.get("total", 0)) for item in progress.values())
    return {
        "username": user["username"],
        "name": user.get("name") or user["username"],
        "points": best_total,
        "sets": len(progress),
        "accuracy": round(best_total / question_total, 3) if question_total else 0.0,
        "progress": progress,
        "avatar": user.get("avatar") or "",
        "bio": dict(user.get("bio") or {}),
        "featured": bool(user.get("featured")),
        "lockedAvatar": bool(user.get("lockedAvatar")),
    }


def register(username: str, name: str, password: str) -> dict[str, Any]:
    username = (username or "").strip()
    name = (name or "").strip() or username
    if not _USERNAME.match(username):
        raise ValueError("username 3–24 karakter: huruf, angka, titik, garis bawah, atau strip")
    if len(name) > 40:
        raise ValueError("nama maksimal 40 karakter")
    if len(password or "") < 6:
        raise ValueError("password minimal 6 karakter")

    with _lock:
        data = _read()
        if username.lower() in data["users"]:
            raise ValueError("username sudah dipakai")
        data["users"][username.lower()] = _make_user(username, name, password)
        token = _new_session(data, username.lower())
        _write(data)
        return {"token": token, "user": _public(data["users"][username.lower()])}


def login(username: str, password: str) -> dict[str, Any]:
    username = (username or "").strip().lower()
    if username == FEATURED["username"]:
        raise ValueError("profil legenda — tidak bisa login")
    with _lock:
        data = _read()
        user = data["users"].get(username)
        if not user or _hash(password or "", user["salt"]) != user["hash"]:
            raise ValueError("username atau password salah")
        token = _new_session(data, username)
        _write(data)
        return {"token": token, "user": _public(user)}


def _new_session(data: dict[str, Any], username: str) -> str:
    token = secrets.token_urlsafe(32)
    data["sessions"][token] = {"username": username, "created": time.time()}
    return token


def logout(token: str) -> None:
    with _lock:
        data = _read()
        data["sessions"].pop(token, None)
        _write(data)


def user_for_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    with _lock:
        data = _read()
        session = data["sessions"].get(token)
        if not session:
            return None
        user = data["users"].get(session["username"])
        return _public(user) if user else None


def record_progress(token: str, set_key: str, correct: int, total: int) -> dict[str, Any]:
    """Store the best score for a set (never downgrade)."""
    if not set_key:
        raise ValueError("set kosong")
    correct = max(0, int(correct))
    total = max(correct, int(total))
    with _lock:
        data = _read()
        session = data["sessions"].get(token or "")
        if not session:
            raise PermissionError("session tidak valid")
        user = data["users"].get(session["username"])
        if not user:
            raise PermissionError("session tidak valid")
        progress = user.setdefault("progress", {})
        item = progress.get(set_key, {"best": 0, "total": total, "updated": 0})
        item["best"] = max(int(item.get("best", 0)), correct)
        item["total"] = max(int(item.get("total", 0)), total)
        item["updated"] = time.time()
        progress[set_key] = item
        _write(data)
        return _public(user)


def _image_ext(blob: bytes) -> str:
    for signature, ext in _IMAGE_EXT:
        if blob.startswith(signature):
            return ext
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "webp"
    return ""


def _session_user(data: dict[str, Any], token: str | None) -> dict[str, Any]:
    session = data["sessions"].get(token or "")
    user = data["users"].get(session["username"]) if session else None
    if not user:
        raise PermissionError("session tidak valid")
    return user


def set_avatar(token: str, blob: bytes) -> dict[str, Any]:
    """Store an uploaded profile picture for the logged-in user."""
    if not blob:
        raise ValueError("file kosong")
    if len(blob) > MAX_AVATAR_BYTES:
        raise ValueError("gambar maksimal 4 MB")
    ext = _image_ext(blob)
    if not ext:
        raise ValueError("format gambar harus PNG, JPG, WEBP, atau GIF")
    with _lock:
        data = _read()
        user = _session_user(data, token)
        if user.get("lockedAvatar"):
            raise ValueError("foto profil ini sudah ditetapkan")
        AVATAR_DIR.mkdir(parents=True, exist_ok=True)
        stem = _SAFE.sub("_", str(user["username"]).lower())
        for old in AVATAR_DIR.glob(f"{stem}.*"):
            try:
                old.unlink()
            except OSError:
                pass
        name = f"{stem}.{ext}"
        (AVATAR_DIR / name).write_bytes(blob)
        user["avatar"] = f"/avatars/{name}?v={int(time.time())}"
        _write(data)
        return _public(user)


def clear_avatar(token: str) -> dict[str, Any]:
    """Remove the uploaded picture and fall back to initials."""
    with _lock:
        data = _read()
        user = _session_user(data, token)
        if user.get("lockedAvatar"):
            raise ValueError("foto profil ini sudah ditetapkan")
        stem = _SAFE.sub("_", str(user["username"]).lower())
        for old in AVATAR_DIR.glob(f"{stem}.*"):
            try:
                old.unlink()
            except OSError:
                pass
        user["avatar"] = ""
        _write(data)
        return _public(user)


def leaderboard(limit: int = 20) -> dict[str, Any]:
    with _lock:
        data = _read()
        rows = [_public(user) for user in data["users"].values()]
    rows.sort(key=lambda row: (-row["points"], -row["accuracy"], row["name"].lower()))
    legend = _public(dict(FEATURED))
    legend["username"] = FEATURED["username"]
    legend["name"] = FEATURED["name"]
    legend["points"] = FEATURED["points"]
    legend["sets"] = FEATURED["sets"]
    legend["accuracy"] = FEATURED["accuracy"]
    legend["avatar"] = FEATURED["avatar"]
    legend["bio"] = dict(FEATURED["bio"])
    legend["featured"] = True
    legend["lockedAvatar"] = True
    entries = [legend] + rows
    for index, row in enumerate(entries, start=1):
        row["rank"] = index
    return {"entries": entries[:max(1, limit)], "total": len(entries)}
