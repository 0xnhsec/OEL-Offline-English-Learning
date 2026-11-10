"""Local accounts, sessions, progress and leaderboard for Learn 101.

Everything is stored in ``.users.json`` next to the app. Passwords are hashed
with PBKDF2-SHA256 (200k rounds + per-user salt); tokens are random and kept
server-side. This is a local single-user app, but the basics are done right.
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

_USERNAME = re.compile(r"^[A-Za-z0-9_.-]{3,24}$")
_lock = threading.Lock()

DEFAULT_USER = {
    "username": "User1",
    "name": "0xnhsec was here",
    "password": "WeAreHackerone",
}


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
    if not data["users"]:
        _seed(data)
        _write(data)
    return data


def _write(data: dict[str, Any]) -> None:
    tmp = USERS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(USERS_PATH)


def _seed(data: dict[str, Any]) -> None:
    username = DEFAULT_USER["username"].lower()
    salt = secrets.token_hex(16)
    data["users"][username] = {
        "username": DEFAULT_USER["username"],
        "name": DEFAULT_USER["name"],
        "salt": salt,
        "hash": _hash(DEFAULT_USER["password"], salt),
        "created": time.time(),
        "progress": {},
    }


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
        salt = secrets.token_hex(16)
        data["users"][username.lower()] = {
            "username": username,
            "name": name,
            "salt": salt,
            "hash": _hash(password, salt),
            "created": time.time(),
            "progress": {},
        }
        token = _new_session(data, username.lower())
        _write(data)
        return {"token": token, "user": _public(data["users"][username.lower()])}


def login(username: str, password: str) -> dict[str, Any]:
    username = (username or "").strip().lower()
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


def leaderboard(limit: int = 20) -> dict[str, Any]:
    with _lock:
        data = _read()
        rows = [_public(user) for user in data["users"].values()]
    rows.sort(key=lambda row: (-row["points"], -row["accuracy"], row["name"].lower()))
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return {"entries": rows[:limit], "total": len(rows)}
