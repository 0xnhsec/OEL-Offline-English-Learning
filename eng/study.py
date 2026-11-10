"""Study material parser: practice sets with an answer key.

Expected shape (plain text)::

    ESSENTIAL ENGLISH GRAMMAR - PRACTICE SET 1
    Choose the best answer (A-D).

    1. [Subject-verb agreement | easy]
    The number of students in the class ___ increasing every year.
       A. is
       B. are
    ...
    ==================================================
    ANSWER KEY (jangan dilihat sebelum menjawab)
    ==================================================

    1. A
       Why : ...
       Trap: ...

The parser is tolerant: blank lines, dashes, multi-line stems, and an answer
key that is missing or partial all work.
"""

from __future__ import annotations

import json
import re
from typing import Any

_Q_HEAD = re.compile(r"^\s*(\d+)\s*[.)]\s*\[([^|\]]+?)(?:\s*\|\s*([^\]]+?))?\]\s*$")
_OPTION = re.compile(r"^\s*([A-Da-d])\s*[.)]\s+(.+?)\s*$")
_ANSWER = re.compile(r"^\s*(\d+)\s*[.)]\s*([A-Da-d])\b\s*$")
_WHY = re.compile(r"^\s*Why\s*:\s*(.*)$", re.IGNORECASE)
_TRAP = re.compile(r"^\s*Trap\s*:\s*(.*)$", re.IGNORECASE)
_KEY_MARK = re.compile(r"ANSWER\s*KEY", re.IGNORECASE)
_SEPARATOR = re.compile(r"^\s*[=\-_*]{3,}\s*$")


def parse_practice_set(raw: str) -> dict[str, Any]:
    """Parse a practice set + answer key into a serialisable dict."""
    lines = (raw or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")

    key_at = len(lines)
    for i, line in enumerate(lines):
        if _KEY_MARK.search(line):
            key_at = i
            break

    body, key_lines = lines[:key_at], lines[key_at:]

    title = "Practice set"
    for line in body:
        text = line.strip().strip("=").strip()
        if text and not _SEPARATOR.match(line):
            title = text
            break

    questions: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for line in body:
        match = _Q_HEAD.match(line)
        if match:
            if current:
                questions.append(current)
            current = {
                "n": int(match.group(1)),
                "topic": (match.group(2) or "").strip(),
                "difficulty": (match.group(3) or "").strip(),
                "text": "",
                "options": {},
            }
            continue
        if current is None or _SEPARATOR.match(line):
            continue
        option = _OPTION.match(line)
        if option:
            current["options"][option.group(1).upper()] = option.group(2).strip()
            continue
        if not line.strip():
            continue
        if current["options"]:
            # Wrapped option text.
            last = sorted(current["options"])[-1]
            current["options"][last] = f"{current['options'][last]} {line.strip()}".strip()
        else:
            current["text"] = f"{current['text']} {line.strip()}".strip()

    if current:
        questions.append(current)

    answers: dict[int, dict[str, str]] = {}
    current_n: int | None = None
    field: str | None = None
    for line in key_lines:
        if _SEPARATOR.match(line) or _KEY_MARK.search(line):
            continue
        answer = _ANSWER.match(line)
        if answer:
            current_n = int(answer.group(1))
            answers[current_n] = {"answer": answer.group(2).upper(), "why": "", "trap": ""}
            field = None
            continue
        if current_n is None:
            continue
        why = _WHY.match(line)
        if why:
            answers[current_n]["why"] = why.group(1).strip()
            field = "why"
            continue
        trap = _TRAP.match(line)
        if trap:
            answers[current_n]["trap"] = trap.group(1).strip()
            field = "trap"
            continue
        if line.strip() and field:
            answers[current_n][field] = f"{answers[current_n][field]} {line.strip()}".strip()

    for question in questions:
        key = answers.get(question["n"], {"answer": "", "why": "", "trap": ""})
        question.update(key)
        question["answered"] = bool(key["answer"])

    return _finish(title, questions)


def parse_json_set(raw: str) -> dict[str, Any]:
    """Parse the JSON shape: {title, questions:[{id, topic, options, answer, ...}]}."""
    data = json.loads(raw)
    if isinstance(data, list):
        data = {"questions": data}
    if not isinstance(data, dict):
        raise ValueError("JSON harus berupa object atau array soal")

    questions: list[dict[str, Any]] = []
    for index, item in enumerate(data.get("questions") or [], start=1):
        if not isinstance(item, dict):
            continue
        options = item.get("options") or {}
        if isinstance(options, list):
            options = {chr(65 + i): str(value) for i, value in enumerate(options)}
        if not isinstance(options, dict):
            options = {}
        options = {str(key).upper(): str(value) for key, value in options.items()}
        answer = str(item.get("answer") or "").strip().upper()[:1]
        questions.append({
            "n": int(item.get("id") or item.get("n") or index),
            "topic": str(item.get("topic") or "").strip(),
            "difficulty": str(item.get("difficulty") or "").strip(),
            "text": str(item.get("question") or item.get("text") or item.get("stem") or "").strip(),
            "options": options,
            "answer": answer,
            "why": str(item.get("explanation") or item.get("why") or "").strip(),
            "trap": str(item.get("trap") or "").strip(),
            "answered": bool(answer and answer in options),
        })

    title = str(data.get("title") or "Practice set").strip()
    return _finish(title, questions)


def _finish(title: str, questions: list[dict[str, Any]]) -> dict[str, Any]:
    difficulties: dict[str, int] = {}
    for question in questions:
        label = (question.get("difficulty") or "").lower() or "unknown"
        difficulties[label] = difficulties.get(label, 0) + 1
    return {
        "title": title,
        "questions": questions,
        "count": len(questions),
        "difficulty": difficulties,
        "hasKey": any(q.get("answer") for q in questions),
    }
