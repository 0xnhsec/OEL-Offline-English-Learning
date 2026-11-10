"""The coach: a 100% local, rule-based engine that follows the 0xnhsec-EN skill.

No cloud model, no API key, no external calls. Feedback comes from the grammar
rule engine in textutil (Fix / Why / Try shape), so the app works fully offline.
"""

from __future__ import annotations

from typing import Any

from . import textutil


def offline_analyze(kind: str, text: str, reference: str | None = None) -> dict[str, Any]:
    """Rule-based feedback: the Fix / Why / Try shape."""
    include_mechanics = kind != "transcript"
    report = textutil.find_grammar_issues(text, limit=4, include_mechanics=include_mechanics)
    blocks = textutil.to_fix_blocks(report["matches"])

    notes: list[str] = []
    if kind == "transcript" and reference:
        stats = textutil.align(reference, text)["stats"]
        notes.append(
            f"Terdengar {stats['heard_words']}/{stats['ref_words']} kata dari teks acuan "
            f"({stats['ok']} persis, {stats['wrong']} beda tulisan, {stats['missed']} hilang, "
            f"{stats['extra']} tambahan)."
        )
        notes.append(
            "Angka ini dari pengenalan suara, bukan penilaian fonetik: kesalahan ASR bisa juga "
            "karena mic atau derau, bukan ucapanmu."
        )
    if not blocks:
        notes.append("Tidak ada pola grammar offline yang cocok dengan kalimat ini.")
    elif report["engine"] == "rule":
        notes.append("Mode lokal: koreksi berasal dari 26 pola grammar di server, bukan AI.")

    lines = []
    for block in blocks:
        lines.append(f'Fix:  {block["fix"]}')
        lines.append(f"Why:  {block['why']}")
        lines.append(f"Try:  {block['try']}")
        lines.append("")
    lines.extend(notes)

    return {
        "text": "\n".join(lines).strip(),
        "blocks": blocks,
        "notes": notes,
        "matches": report["matches"],
        "corrected": report["corrected"],
        "engine": "rule",
    }


def analyze(
    kind: str,
    text: str,
    reference: str | None = None,
) -> dict[str, Any]:
    """Feedback on a piece of writing or a speech transcript (local rules only)."""
    result = offline_analyze(kind, text, reference)
    return {**result, "reply": result["text"], "model": None}
