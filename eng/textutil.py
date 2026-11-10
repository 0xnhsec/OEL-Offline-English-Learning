"""Text utilities for OEL.

- cleaning + abbreviation-aware sentence splitting
- shadowing chunking (1-2 sentences per chunk, per references/voice-pipeline.md)
- word-level alignment between a reference text and what the learner said
- offline rule-based grammar checking (Indonesian-interference patterns)

No third-party imports, no network: safe as a fallback everywhere.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Callable

# --------------------------------------------------------------------------- #
# cleaning + sentence splitting
# --------------------------------------------------------------------------- #

_ABBREV = {
    "mr", "mrs", "ms", "dr", "prof", "st", "jr", "sr", "vs", "etc",
    "e.g", "i.e", "inc", "ltd", "dept", "approx", "no", "fig", "ca",
    "u.s", "u.k", "a.m", "p.m", "ph.d", "b.a", "m.a", "b.sc", "m.sc",
    "obs", "est", "min", "max", "vol", "pp", "ed", "rev", "co", "univ",
}

_SPLIT_RE = re.compile(r"([.!?]+[\"')\]]*(?:\s+|$))")
_WORD_RE = re.compile(r"[a-z0-9']+")


def clean_text(raw: str) -> str:
    """Normalize an uploaded text file: kill CR, smart quotes, stray markup."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\ufeff", "")
    text = re.sub(r"[\u2018\u2019]", "'", text)
    text = re.sub(r"[\u201c\u201d]", '"', text)
    text = re.sub(r"[\u2013\u2014]", " - ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def strip_subtitles(text: str) -> str:
    """Drop SRT/VTT timestamps, indices and styling tags."""
    lines = []
    for line in text.split("\n"):
        if re.match(r"^\s*\d+\s*$", line):
            continue
        if re.match(r"^\s*(WEBVTT|NOTE\b|STYLE\b|REGION\b)", line, re.I):
            continue
        if re.search(r"-->\s*\d{2}:\d{2}", line):
            continue
        line = re.sub(r"</?(c|i|b|u|lang|v)(\.[^>]*)?>", "", line, flags=re.I)
        line = re.sub(r"<[^>]+>", "", line)
        lines.append(line)
    return "\n".join(lines)


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _looks_like_abbrev(sentence: str) -> bool:
    """True when this sentence should NOT break here (it ends with an abbreviation)."""
    m = re.search(r"([A-Za-z.]+)\.?$", sentence.rstrip())
    if not m:
        return False
    word = m.group(1).rstrip(".").lower()
    if word in _ABBREV:
        return True
    return bool(re.fullmatch(r"(?:[a-z]\.){1,4}", word))


def split_sentences(text: str) -> list[str]:
    """Abbreviation-aware sentence splitter; paragraphs survive as breaks.

    A punctuation mark inside quotes does not break the sentence when the text
    continues in lower case (``"Stop!" he said``) - that is an attribution,
    not a new sentence.
    """
    sentences: list[str] = []
    for para in split_paragraphs(text):
        parts = _SPLIT_RE.split(para)
        buf = ""
        for idx, part in enumerate(parts):
            buf += part
            if idx % 2 == 1:
                candidate = buf.strip()
                nxt = parts[idx + 1] if idx + 1 < len(parts) else ""
                in_quotes = part.strip()[-1:] in {'"', "'", ")", "]", "}", "\u201d", "\u2019"}
                continues = bool(nxt) and nxt[0].islower() and in_quotes
                if candidate and not _looks_like_abbrev(candidate) and not continues:
                    sentences.append(candidate)
                    buf = ""
        rest = buf.strip()
        if rest:
            if sentences and not re.search(r"[.!?]$", sentences[-1]):
                sentences[-1] = sentences[-1] + " " + rest
            else:
                sentences.append(rest)
    return [s for s in (s.strip() for s in sentences) if s]


# --------------------------------------------------------------------------- #
# chunking for shadowing
# --------------------------------------------------------------------------- #

_CLAUSE_SPLIT_RE = re.compile(
    r",\s+(?:(?:and|but|or|because|so|which|when|while|if|although|though|after|before)\s+)",
    flags=re.I,
)


def tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _split_long_sentence(sentence: str, max_words: int) -> list[str]:
    """Break one over-long sentence into speakable pieces (clause first, then hard cut)."""
    if len(sentence.split()) <= max_words:
        return [sentence]

    pieces: list[str] = []
    rest = sentence
    while len(rest.split()) > int(max_words * 1.5):
        window = " ".join(rest.split()[: max_words + 10])
        last: re.Match | None = None
        for last in _CLAUSE_SPLIT_RE.finditer(window):
            pass
        if last is None or last.end() < max_words * 0.5:
            head = rest.split()[:max_words]
            pieces.append(" ".join(head).rstrip(",;:") + ",")
            rest = " ".join(rest.split()[max_words:])
        else:
            pieces.append(rest[: last.end()].strip())
            rest = rest[last.end():].strip()
    if rest:
        pieces.append(rest)
    return [p for p in pieces if p]


def chunk_text(
    text: str,
    max_sentences: int = 2,
    max_words: int = 30,
) -> list[dict[str, Any]]:
    """Group sentences into shadowing chunks.

    Returns [{"index", "text", "sentences", "words"}]. A blank line separates
    chunks on export - the format defined in references/voice-pipeline.md.
    """
    sentences: list[str] = []
    for sentence in split_sentences(text):
        sentences.extend(_split_long_sentence(sentence, max_words))

    chunks: list[dict[str, Any]] = []
    current: list[str] = []

    def flush() -> None:
        if not current:
            return
        joined = " ".join(current)
        chunks.append(
            {
                "index": len(chunks),
                "text": joined,
                "sentences": list(current),
                "words": len(tokenize(joined)),
            }
        )
        current.clear()

    for sentence in sentences:
        if current and (
            len(current) + 1 > max_sentences
            or len(tokenize(" ".join(current + [sentence]))) > max_words
        ):
            flush()
        current.append(sentence)
    flush()
    return chunks


def chunks_to_text(chunks: list[dict[str, Any]]) -> str:
    """Blank line between chunks - what the read-aloud file looks like."""
    return "\n\n".join(c["text"] for c in chunks)


# --------------------------------------------------------------------------- #
# alignment: what did the learner actually say?
# --------------------------------------------------------------------------- #

OK, WRONG, MISSED, EXTRA = "ok", "wrong", "missed", "extra"


def align(reference: str, hypothesis: str) -> dict[str, Any]:
    """Token-level alignment between the reference and the spoken transcript.

    status:
      ok     - word recognised exactly as written
      wrong  - word present in both but different (a slip, or an ASR miss)
      missed - written in the reference, not heard
      extra  - heard, not in the reference (filler or invented word)
    """
    ref = tokenize(reference)
    hyp = tokenize(hypothesis)

    pairs: list[dict[str, Any]] = []
    for op, a1, a2, b1, b2 in SequenceMatcher(None, ref, hyp, autojunk=False).get_opcodes():
        if op == "equal":
            for i in range(a2 - a1):
                pairs.append({"ref": ref[a1 + i], "hyp": hyp[b1 + i], "status": OK})
        elif op == "replace":
            span = max(a2 - a1, b2 - b1)
            for k in range(span):
                r = ref[a1 + k] if a1 + k < a2 else None
                h = hyp[b1 + k] if b1 + k < b2 else None
                if h is None:
                    pairs.append({"ref": r, "hyp": None, "status": MISSED})
                elif r is None:
                    pairs.append({"ref": None, "hyp": h, "status": EXTRA})
                else:
                    pairs.append({"ref": r, "hyp": h, "status": WRONG})
        elif op == "delete":
            for i in range(a1, a2):
                pairs.append({"ref": ref[i], "hyp": None, "status": MISSED})
        else:
            for i in range(b1, b2):
                pairs.append({"ref": None, "hyp": hyp[i], "status": EXTRA})

    counts = {OK: 0, WRONG: 0, MISSED: 0, EXTRA: 0}
    for p in pairs:
        counts[p["status"]] += 1

    total = len(ref) or 1
    accuracy = round((counts[OK] + 0.5 * counts[WRONG]) / total, 3) if ref else 0.0

    return {
        "reference": [{"w": p["ref"], "status": p["status"]} for p in pairs if p["ref"]],
        "hypothesis": [{"w": p["hyp"], "status": p["status"]} for p in pairs if p["hyp"]],
        "pairs": pairs,
        "stats": {
            "ref_words": len(ref),
            "heard_words": len(hyp),
            "ok": counts[OK],
            "wrong": counts[WRONG],
            "missed": counts[MISSED],
            "extra": counts[EXTRA],
            "accuracy": accuracy,
        },
    }


# --------------------------------------------------------------------------- #
# offline grammar rules (the app's only correction engine)
# --------------------------------------------------------------------------- #

_PAST_MAP = {
    "went": "go", "ate": "eat", "saw": "see", "came": "come", "took": "take",
    "made": "make", "got": "get", "had": "have", "said": "say", "told": "tell",
    "wrote": "write", "thought": "think", "knew": "know", "felt": "feel",
    "began": "begin", "chose": "choose", "gave": "give", "found": "find",
    "left": "leave", "met": "meet", "paid": "pay", "ran": "run", "sent": "send",
    "spent": "spend", "stood": "stand", "spoke": "speak", "taught": "teach",
    "understood": "understand", "brought": "bring", "built": "build",
    "bought": "buy", "caught": "catch", "drove": "drive", "held": "hold",
    "heard": "hear", "lost": "lose", "sold": "sell", "slept": "sleep",
    "won": "win", "broke": "break", "put": "put", "set": "set",
}

# base verbs used to validate regular -ed -> base reductions
_BASE_VERBS = set(
    """
    act add agree allow answer apply ask assume avoid be become believe belong
    break bring build buy call care change check choose close come compare
    complete consider continue cook create cut decide describe design develop
    depend differ discuss do draw drink drive earn eat end enjoy enter expect
    explain fail exist fall feel find finish follow forget get give go grow
    happen hate hear help hold hope identify improve include increase intend
    invite join keep know learn leave let like live look lose love make manage
    mean meet miss move need note notice offer open order pass pay perform pick
    play prefer prepare present produce provide publish put reach read receive
    recognize reduce refer refuse relate remain remember remove repeat reply
    report require research respond rest return review run say see seem send
    share show sleep solve speak spend stand start state stay stop study suggest
    take talk teach tell test think train travel try turn understand use visit
    wait walk want warn wash watch win wish wonder work write
    """.split()
)

# base verbs that also behave like nouns - safe only after he/she/it
_BASE_VERBS |= {"matter", "answer", "call", "change", "check"}

_CONSONANT_Y = re.compile(r"[^aeiou]y$")

_UNCOUNTABLE_FIX = {
    "informations": "information", "advices": "advice", "equipments": "equipment",
    "furnitures": "furniture", "softwares": "software", "knowledges": "knowledge",
    "researches": "research", "evidences": "evidence", "feedbacks": "feedback",
    "staffs": "staff", "homeworks": "homework", "peoples": "people",
    "traffics": "traffic",
}

# forms that are already correct after he/she/it - never rewrite them
_NONFINITE = {
    "am", "is", "was", "has", "had", "did", "does", "been", "being", "be",
    "will", "would", "shall", "should", "can", "could", "may", "might",
    "must", "going", "not",
}

# ... but these two after a singular subject ARE the error
_SVA_MAP = {"have": "has", "are": "is", "were": "was", "belong": "belongs"}

# adjective -> (correct preposition, prepositions that are wrong here)
_ADJ_PREP: dict[str, tuple[str, set[str]]] = {
    "interested": ("in", {"on", "about", "of", "with", "from", "at", "to"}),
    "capable": ("of", {"on", "about", "with", "in", "from", "at", "to"}),
    "proud": ("of", {"on", "about", "with", "in", "from", "at", "to"}),
    "afraid": ("of", {"on", "about", "with", "in", "from", "at", "to"}),
    "bored": ("with", {"on", "about", "from", "at", "in"}),
    "tired": ("of", {"on", "about", "with", "in", "from", "at"}),
    "similar": ("to", {"on", "about", "with", "in", "from", "at", "of"}),
    "married": ("to", {"on", "about", "with", "in", "from", "at", "of"}),
    "different": ("from", {"on", "about", "with", "at", "of"}),
}

_QUANTIFIER_FIX = {
    "friend": "friends", "colleague": "colleagues", "student": "students",
    "teacher": "teachers", "child": "children", "person": "people",
    "member": "members", "sibling": "siblings", "classmate": "classmates",
}

_APOSTROPHE_MAP = {
    "dont": "don't", "cant": "can't", "wont": "won't", "isnt": "isn't",
    "arent": "aren't", "didnt": "didn't", "doesnt": "doesn't", "couldnt": "couldn't",
    "shouldnt": "shouldn't", "wouldnt": "wouldn't", "im": "I'm", "youre": "you're",
    "theyre": "they're", "ive": "I've", "weve": "we've", "hes": "he's",
    "shes": "she's", "theres": "there's", "isnt": "isn't",
}

_THIRD_PREPOSITIONAL = {
    "are": "is", "were": "was", "have": "has", "belong": "belongs",
}


def third_person(verb: str) -> str:
    """he/she/it form of a base verb: study -> studies, watch -> watches, have -> has."""
    v = verb.lower()
    if v == "have":
        return "has"
    if v == "do":
        return "does"
    if v == "go":
        return "goes"
    if _CONSONANT_Y.search(v):
        return v[:-1] + "ies"
    if v.endswith(("s", "x", "z", "ch", "sh", "o")):
        return v + "es"
    return v + "s"


def _base_from_s(word: str) -> str:
    """3rd person singular -> base form: studies -> study, watches -> watch."""
    v = word.lower()
    if v.endswith("ies") and len(v) > 4:
        return v[:-3] + "y"
    if v.endswith(("ches", "shes", "sses", "xes", "zzes", "oes")):
        return v[:-2]
    if v.endswith("s") and not v.endswith("ss"):
        return v[:-1]
    return v


def _did_past(m: re.Match) -> str:
    """did/didn't + past -> did/didn't + base form (only when we are sure)."""
    aux, verb = m.group(1), m.group(2).lower()
    if verb in _PAST_MAP:
        base = _PAST_MAP[verb]
    elif verb.endswith("ied"):
        base = verb[:-3] + "y"
    elif verb.endswith("ed") and len(verb) > 4:
        cut = verb[:-2]
        if len(cut) > 2 and cut[-1] == cut[-2]:
            base = cut[:-1]                 # stopped -> stop
        elif cut in _BASE_VERBS:
            base = cut                      # walked -> walk
        elif cut + "e" in _BASE_VERBS:
            base = cut + "e"                # used -> use, hoped -> hope
        else:
            return m.group(0)               # not confident: leave it alone
    else:
        return m.group(0)
    return f"{aux} {base}"


def _rule_sv3(m: re.Match) -> str:
    """he/she/it/everyone + verb -> correct agreement, or the input untouched."""
    subj, verb = m.group(1), m.group(2).lower().strip("'")
    raw = m.group(2).lower()
    if raw.endswith("n't") or raw.startswith("'"):
        return m.group(0)                       # doesn't / don't / isn't ... leave alone
    if verb in _NONFINITE:
        return m.group(0)
    if verb in _SVA_MAP:
        return f"{m.group(1)} {_SVA_MAP[verb]}"
    if verb in _BASE_VERBS:
        return f"{m.group(1)} {third_person(verb)}"
    return m.group(0)


_PLURAL_SUBJ = {"i", "we", "you", "they", "people"}
_AUX_FLIP = {
    "doesn't": "don't", "don't": "doesn't", "isn't": "aren't", "aren't": "isn't",
    "wasn't": "weren't", "weren't": "wasn't", "hasn't": "haven't", "haven't": "hasn't",
}
_AUX_PLURAL = {"don't", "aren't", "weren't", "haven't"}


_SINGULAR_SUBJ = {"he", "she", "it", "everyone", "everybody", "someone", "somebody",
                  "anyone", "anybody", "nobody", "this", "that"}


def _rule_agree(m: re.Match) -> str:
    subj, aux = m.group(1), m.group(2).lower()
    singular = subj.lower() in _SINGULAR_SUBJ
    if aux in {"isn't", "aren't", "am not"}:
        neg = "doesn't" if singular else "don't"
        return f"{subj} {neg} agree"
    if aux in {"wasn't", "weren't"}:
        return f"{subj} didn't agree"
    if aux in {"is", "are", "am"}:
        return f"{subj} {'agrees' if singular else 'agree'}"
    if aux in {"was", "were"}:
        return f"{subj} agreed"
    return m.group(0)


def _rule_aux(m: re.Match) -> str:
    subj, aux = m.group(1).lower(), m.group(2).lower()
    want_plural = subj in _PLURAL_SUBJ
    if want_plural == (aux in _AUX_PLURAL):
        return m.group(0)
    return f"{m.group(1)} {_AUX_FLIP[aux]}"


def _rule_not_third(m: re.Match) -> str:
    return f"{m.group(1)} doesn't {m.group(2)}"


def _rule_quantifier(m: re.Match) -> str:
    noun = m.group(1).lower()
    if noun not in _QUANTIFIER_FIX:
        return m.group(0)
    return f"one of my {_QUANTIFIER_FIX[noun]}"


def _rule_uncountable(m: re.Match) -> str:
    word = m.group(1).lower()
    return _UNCOUNTABLE_FIX.get(word, word)


def _rule_apostrophe(m: re.Match) -> str:
    return _APOSTROPHE_MAP.get(m.group(1).lower(), m.group(1))


Rule = dict  # id / rx / repl / why / term


RULES: list[Rule] = [
    {
        "id": "cap-i",
        "rx": re.compile(r"(?<![\w.])i(?=[\s,.!?]|$)"),
        "repl": "I",
        "why": 'Ganti "i" selalu kapital - "I" adalah satu-satunya pronomina kapital dalam bahasa Inggris.',
        "term": "capitalisation",
    },
    {
        "id": "cap-sentence",
        "rx": re.compile(r"(?:^|[.!?]\s+)([a-z])", re.M),
        "repl": lambda m: m.group(0)[:-1] + m.group(1).upper(),
        "why": "Kalimat baru diawali huruf kapital.",
        "term": "sentence boundary",
        "silent": True,
    },
    {
        "id": "apostrophe",
        "rx": re.compile(
            r"\b(dont|cant|wont|isnt|arent|didnt|doesnt|couldnt|shouldnt|wouldnt|"
            r"im|youre|theyre|ive|weve|hes|shes|theres)\b",
            re.I,
        ),
        "repl": _rule_apostrophe,
        "why": "Bentuk singkat (contraction) selalu pakai apostroph: don't, can't, I'm.",
        "term": "contraction",
    },
    {
        "id": "sva-3rd",
        "rx": re.compile(
            r"\b(he|she|it|everyone|everybody|someone|somebody|anyone|anybody|nobody|each)\s+([a-z']+)",
            re.I,
        ),
        "repl": _rule_sv3,
        "why": "Subjek he/she/it = tunggal, verb sekarang harus -s/-es (subject-verb agreement).",
        "term": "subject-verb agreement",
    },
    {
        "id": "sva-not-3rd",
        "rx": re.compile(r"\b(he|she|it)\s+don't\s+([a-z]+)\b", re.I),
        "repl": _rule_not_third,
        "why": "Negasi subjek tunggal: he/she/it doesn't, bukan don't (subject-verb agreement).",
        "term": "subject-verb agreement",
    },
    {
        "id": "aux-agreement",
        "rx": re.compile(
            r"\b(I|we|you|they|he|she|it|everyone|everybody|someone|somebody|anyone|anybody|nobody|this|that)"
            r"\s+(doesn't|isn't|wasn't|hasn't|don't|aren't|weren't|haven't)\b",
            re.I,
        ),
        "repl": _rule_aux,
        "why": "Auxiliary mengikuti subjek: I/we/you/they + don't; he/she/it + doesn't (subject-verb agreement).",
        "term": "subject-verb agreement",
    },
    {
        "id": "neg-base",
        "rx": re.compile(r"\b(don't|doesn't|didn't|do not|does not|did not)\s+([a-z]+s)\b", re.I),
        "repl": lambda m: f"{m.group(1)} {_base_from_s(m.group(2))}"
        if not m.group(2).lower().endswith("ss")
        else m.group(0),
        "why": "Setelah don't/doesn't/didn't verb memakai bentuk dasar: don't knows -> don't know.",
        "term": "negation",
    },
    {
        "id": "did-past",
        "rx": re.compile(
            r"\b(didn't|did not|did)\s+([a-z]+(?:ed)?|went|ate|saw|came|took|made|got|had)\b",
            re.I,
        ),
        "repl": _did_past,
        "why": "Setelah did/didn't verb kembali ke bentuk dasar: didn't went -> didn't go.",
        "term": "simple past",
    },
    {
        "id": "sva-indefinite",
        "rx": re.compile(
            r"\b(every|everybody|everyone|someone|somebody|anyone|anybody|nobody|no one|"
            r"each of [a-z]+|one of [a-z]+(?: [a-z]+)?)\s+(are|were|have|belong)\b",
            re.I,
        ),
        "repl": lambda m: f"{m.group(1)} {_THIRD_PREPOSITIONAL[m.group(2).lower()]}",
        "why": "Indefinite pronoun (everyone, each, nobody) dianggap tunggal: is/was/has.",
        "term": "subject-verb agreement",
    },
    {
        "id": "the-number",
        "rx": re.compile(r"\b(the number of [a-z]+)\s+(are|were|have)\b", re.I),
        "repl": lambda m: f"{m.group(1)} {'is' if m.group(2).lower() != 'have' else 'has'}",
        "why": '"the number of" + plural noun = singular verb; head subjeknya "number" - bukan "students".',
        "term": "subject-verb agreement",
    },
    {
        "id": "a-number",
        "rx": re.compile(r"\b(a number of [a-z]+)\s+(is|was)\b", re.I),
        "repl": lambda m: f"{m.group(1)} are",
        "why": '"a number of" berarti "many", jadi verb-nya jamak - kontras dengan "the number of".',
        "term": "subject-verb agreement",
    },
    {
        "id": "one-of",
        "rx": re.compile(r"\bone of my ([a-z]+)\b", re.I),
        "repl": _rule_quantifier,
        "why": 'Setelah "one of" noun-nya jamak: one of my friends, one of my children.',
        "term": "quantifier",
    },
    {
        "id": "agree",
        "rx": re.compile(r"\b(I|we|you|they|he|she|it)\s+(am not|isn't|aren't|wasn't|weren't|is|are|am|was|were)\s+agree\b", re.I),
        "repl": _rule_agree,
        "why": '"agree" kerja, bukan adjective: I agree - bukan I am agree; he doesn\'t agree.',
        "term": "verb vs adjective",
    },
    {
        "id": "ed-ing",
        "rx": re.compile(
            r"\b(am|is|are)\s+"
            r"(interesting|boring|tiring|exciting|annoying|confusing|surprising|"
            r"disappointing|satisfying|relaxing|depressing)\s+(with|on|about|of|in|from|at)\b",
            re.I,
        ),
        "repl": lambda m: f"{m.group(1)} {m.group(2)[:-3]}ed {m.group(3)}",
        "why": "-ing mendeskripsikan hal, -ed mendeskripsikan perasaan: I am interested/bored/tired in.",
        "term": "-ed / -ing adjective",
    },
    {
        "id": "adj-prep",
        "rx": re.compile(
            r"\b(interested|capable|proud|afraid|bored|tired|similar|married|different)"
            r"\s+(on|about|of|with|in|from|at|to)\b",
            re.I,
        ),
        "repl": lambda m: (
            f"{m.group(1)} {_ADJ_PREP[m.group(1).lower()][0]}"
            if m.group(2).lower() in _ADJ_PREP[m.group(1).lower()][1]
            else m.group(0)
        ),
        "why": "Preposisi melekat pada adjective: interested in, capable of, married to, different from.",
        "term": "preposition after adjective",
    },
    {
        "id": "about-after-verb",
        "rx": re.compile(r"\b(mention|discuss|explain|describe)\s+about\b", re.I),
        "repl": lambda m: m.group(1),
        "why": 'Verb ini sudah berarti "talk about" - tanpa about (verb + preposition).',
        "term": "verb + preposition",
    },
    {
        "id": "explain-to",
        "rx": re.compile(r"\b(explain|say|suggest)\s+(me|us|him|her|them)\b", re.I),
        "repl": lambda m: f"{m.group(1)} to {m.group(2)}",
        "why": "Explain butuh to sebelum objek orang: explain to me.",
        "term": "verb + preposition",
    },
    {
        "id": "depend",
        "rx": re.compile(r"\b(depends?|depended)\s+(of|from)\b", re.I),
        "repl": lambda m: f"{m.group(1)} on",
        "why": 'Kerja "depend" selalu diikuti on: depends on you.',
        "term": "verb + preposition",
    },
    {
        "id": "uncountable",
        "rx": re.compile(
            r"\b(informations|advices|equipments|furnitures|softwares|knowledges|"
            r"researches|evidences|feedbacks|staffs|homeworks|peoples|traffics)\b",
            re.I,
        ),
        "repl": _rule_uncountable,
        "why": "Uncountable noun tidak di-plural-kan: information, advice, equipment, research.",
        "term": "countable / uncountable noun",
    },
    {
        "id": "myself",
        "rx": re.compile(r"\bmy\s+self\b", re.I),
        "repl": "myself",
        "why": "Reflexive pronoun satu kata: myself, yourself, himself.",
        "term": "reflexive pronoun",
    },
    {
        "id": "go-home",
        "rx": re.compile(
            r"\b(go|goes|going|come|comes|arrive|arrives|get|gets|head|heads|be|been)\s+to\s+(home|here|there)\b",
            re.I,
        ),
        "repl": lambda m: f"{m.group(1)} {m.group(2)}",
        "why": "Home/here/there adverb, jadi tanpa to: go home.",
        "term": "preposition",
    },
    {
        "id": "more-er",
        "rx": re.compile(r"\bmore\s+(easier|better|bigger|harder|faster|higher|lower|worse|greater)\b", re.I),
        "repl": lambda m: m.group(1),
        "why": "Sudah ada -er, tidak ditambah more (comparative).",
        "term": "comparative",
    },
    {
        "id": "since-for",
        "rx": re.compile(
            r"\bsince\s+(\d+|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
            r"(years|months|weeks|days)\b",
            re.I,
        ),
        "repl": lambda m: f"for {m.group(1)} {m.group(2)}",
        "why": "Durasi pakai for (for two years); since untuk titik waktu (since 2020).",
        "term": "since / for",
    },
    {
        "id": "at-time",
        "rx": re.compile(r"\bat\s+(the\s+)?(morning|afternoon|evening)\b", re.I),
        "repl": lambda m: f"in the {m.group(2)}",
        "why": "Keterangan waktu pagi/siang/malam memakai in: in the morning (bukan at).",
        "term": "preposition of time",
    },
    {
        "id": "time-order",
        "rx": re.compile(r"\bin the (morning|afternoon|evening) yesterday\b", re.I),
        "repl": lambda m: f"yesterday {m.group(1)}",
        "why": "Urutan keterangan waktu: yesterday morning - bukan in the morning yesterday.",
        "term": "adverb of time",
    },
    {
        "id": "very-like",
        "rx": re.compile(r"\b(very|so much|too much)\s+(like|love|want|need|enjoy|miss)\b", re.I),
        "repl": lambda m: f"{'really' if m.group(1).lower() == 'very' else m.group(1)} {m.group(2)}",
        "why": "Like/love adalah kerja, tidak bisa diintensif very: I really like it.",
        "term": "adverb + verb",
    },
    {
        "id": "alot",
        "rx": re.compile(r"\balot\b", re.I),
        "repl": lambda m: ("A lot" if m.group(0)[0].isupper() else "a lot"),
        "why": '"a lot" selalu dua kata.',
        "term": "spelling",
    },
    {
        "id": "double-space",
        "rx": re.compile(r"(?<=\S) {2,}(?=\S)"),
        "repl": " ",
        "why": "Cukup satu spasi antar kata.",
        "term": "mechanics",
        "silent": True,
    },
    {
        "id": "space-punct",
        "rx": re.compile(r"\s+([,.;:!?])"),
        "repl": lambda m: m.group(1),
        "why": "Tanda baca tidak didahului spasi.",
        "term": "mechanics",
        "silent": True,
    },
]


def find_grammar_issues(
    text: str,
    limit: int = 6,
    include_mechanics: bool = True,
) -> dict[str, Any]:
    """Run the offline rule set. Returns matches + a corrected copy of the text."""
    working = text
    matches: list[dict[str, str]] = []
    mechanics_fixed = 0

    if include_mechanics and working.strip() and not re.search(r'[.!?]["\')\]]?\s*$', working.strip()):
        sentences = split_sentences(working)
        last = sentences[-1] if sentences else working.strip()
        matches.append(
            {
                "id": "missing-final",
                "original": last[-60:].strip(),
                "corrected": last[-60:].strip() + ".",
                "why": "Setiap kalimat ditutup tanda titik (sentence boundary).",
                "term": "mechanics",
            }
        )

    for rule in RULES:
        if len(matches) >= limit and not rule.get("silent"):
            continue
        found: list[tuple[str, str]] = []

        def _sub(m: re.Match, _rule=rule, _found=found) -> str:
            original = m.group(0)
            repl = _rule["repl"]
            new = repl(m) if callable(repl) else m.expand(repl)
            if new != original:
                _found.append((original, new))
            return new

        updated = rule["rx"].sub(_sub, working)
        if found:
            working = updated
            if rule.get("silent"):
                mechanics_fixed += len(found)
                continue
            original, corrected = found[0]
            matches.append(
                {
                    "id": rule["id"],
                    "original": original.strip(),
                    "corrected": corrected.strip(),
                    "why": rule["why"],
                    "term": rule.get("term", ""),
                }
            )

    return {
        "matches": matches,
        "corrected": working,
        "engine": "rule",
        "mechanics_fixed": mechanics_fixed,
    }


def to_fix_blocks(matches: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Shape offline matches like the skill's Fix / Why / Try block."""
    blocks = []
    for m in matches:
        blocks.append(
            {
                "fix": f'"{m["original"]}"  ->  "{m["corrected"]}"',
                "why": m["why"],
                "try": f"Tulis satu kalimat baru memakai pola: {m['corrected']}.",
            }
        )
    return blocks
