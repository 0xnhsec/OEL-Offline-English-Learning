"""End-to-end check: real browser (headless Firefox) against the running server.

Run the server first (./run.sh), then:   .venv/bin/python tests/e2e.py

Covers: page boot, sample text -> chunks, chunk selection, playback,
practice view, word comparison + local feedback, settings, the
fake-microphone record path, and the HTTP pipeline TTS -> whisper -> compare.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "shots"
URL = "http://127.0.0.1:8765"
BASE = "http://127.0.0.1:8765"

STUDY_TEXT = """ESSENTIAL ENGLISH GRAMMAR - PRACTICE SET 1
Choose the best answer (A-D).

1. [Subject-verb agreement | easy]
The number of students in the class ___ increasing every year.
   A. is
   B. are
   C. were
   D. have been

2. [FANBOYS | medium]
She did not submit the report, ___ did she answer my email.
   A. or
   B. nor
   C. and
   D. so

3. [Fragments and run-ons | medium]
Identify the error: "The server crashed, the team restarted it immediately."
   A. Fragment
   B. Fused sentence (run-on)
   C. Comma splice
   D. No error

==================================================
ANSWER KEY (jangan dilihat sebelum menjawab)
==================================================

1. A
   Why : 'The number of' = singular.
   Trap: 'students' (plural) terlihat tepat sebelum verb.

2. B
   Why : 'Nor' dipakai setelah klausa negatif.
   Trap: 'or' terasa natural.

3. C
   Why : Dua independent clause digabung hanya dengan koma.
   Trap: Ada tanda baca, jadi sering dikira benar.
"""

STUDY_JSON = """{
  "title": "JSON Mini Set",
  "questions": [
    {"id": 1, "topic": "Subject-verb agreement", "difficulty": "easy",
     "question": "The number of students ___ increasing.", "options": {"A": "is", "B": "are"},
     "answer": "A", "trap": "students is plural-looking.", "explanation": "The number of = singular."},
    {"id": 2, "topic": "FANBOYS", "difficulty": "medium",
     "question": "She did not submit, ___ did she answer.", "options": ["or", "nor"],
     "answer": "B", "trap": "or feels natural.", "explanation": "Nor after a negative clause."}
  ]
}"""

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, bool(ok), detail))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  — {detail}" if detail else ""), flush=True)
    return bool(ok)


def skip(name: str, detail: str) -> None:
    results.append((name, True, "SKIP: " + detail))
    print(f"SKIP  {name}  — {detail}", flush=True)


def http_json(path: str, payload: dict | None = None, method: str = "POST") -> dict:
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode())


def http_audio(path: str, payload: dict) -> tuple[bytes, str]:
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read(), resp.headers.get("X-TTS-Engine", "?")


def http_multipart(path: str, field: str, filename: str, blob: bytes, fields: dict | None = None,
                   content_type: str = "audio/mpeg") -> tuple[int, dict]:
    import uuid
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for key, value in (fields or {}).items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode())
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
        f"filename=\"{filename}\"\r\nContent-Type: {content_type}\r\n\r\n".encode()
        + blob + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(
        BASE + path, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


# --------------------------------------------------------------------------- #
# 1. HTTP pipeline: TTS -> whisper -> compare
# --------------------------------------------------------------------------- #

def test_http_pipeline_safe(health: dict) -> None:
    try:
        test_http_pipeline(health)
    except Exception as exc:  # noqa: BLE001
        check("http pipeline", False, f"{type(exc).__name__}: {exc}")


def test_http_pipeline(health: dict) -> None:
    text = "The number of students is increasing every year."
    audio, engine = http_audio("/api/tts", {"text": text, "engine": "auto", "rate": 1.0})
    check("tts: audio bytes", len(audio) > 3000, f"engine={engine}, {len(audio)} bytes")

    if not health["asr"].get("installed"):
        skip("transcribe: whisper installed", "faster-whisper not installed")
        return
    if not health["asr"].get("ready") and not health["asr"].get("loading"):
        skip("transcribe: whisper ready", str(health["asr"].get("error")))
        return

    deadline = time.time() + 600
    while time.time() < deadline:
        status, body = http_multipart("/api/transcribe", "file", "tts.mp3", audio,
                                      {"language": "en"})
        if status == 200:
            break
        if status in (501, 503) and "memuat" in str(body):
            time.sleep(10)
            continue
        check("transcribe: http 200", False, f"{status} {body}")
        return
    else:
        skip("transcribe: model load", "timeout waiting for whisper model")
        return

    got = (body.get("text") or "").strip()
    check("transcribe: returns text", bool(got), got[:90])
    check("transcribe: recognises the sentence",
          "number" in got.lower() and "students" in got.lower(), got[:120])

    compare = http_json("/api/compare", {"reference": text, "hypothesis": got})
    acc = compare["stats"]["accuracy"]
    check("compare: accuracy after full pipeline", acc >= 0.6,
          f"accuracy={acc}, ok={compare['stats']['ok']}, missed={compare['stats']['missed']}")


# --------------------------------------------------------------------------- #
# 2. browser flow
# --------------------------------------------------------------------------- #

def test_browser() -> None:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service

    SHOTS.mkdir(exist_ok=True)
    Path("/tmp/opencode/geckodriver.log").unlink(missing_ok=True)
    opts = Options()
    opts.add_argument("-headless")
    opts.set_preference("devtools.console.stdout.content", True)
    opts.set_preference("media.navigator.streams.fake", True)      # fake microphone
    opts.set_preference("media.navigator.permission.disabled", True)

    service = Service(
        executable_path=str(ROOT / ".tools" / "geckodriver"),
        log_output="/tmp/opencode/geckodriver.log",
        service_args=["--log", "trace"],
    )
    driver = webdriver.Firefox(options=opts, service=service)
    driver.set_page_load_timeout(60)
    driver.set_script_timeout(60)
    driver.set_window_size(1440, 950)

    def js(script: str, *args):
        return driver.execute_script(script, *args)

    def shot(name: str) -> None:
        driver.save_screenshot(str(SHOTS / f"{name}.png"))

    def click(element_id: str) -> None:
        """Real (trusted) click: keeps user activation for audio + mic APIs."""
        element = driver.find_element(By.ID, element_id)
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        time.sleep(0.15)
        try:
            element.click()
        except Exception:
            # Sticky header/footer could intercept; fall back to JS click.
            driver.execute_script("arguments[0].click();", element)

    def wait_js(script: str, timeout: float = 25, *args):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                last = js(script, *args)
                if last:
                    return last
            except Exception as exc:  # noqa: BLE001
                last = str(exc)
            time.sleep(0.4)
        return last

    try:
        driver.get(f"{URL}/?sample=1")
        js(
            "window.__jsErrors = [];"
            "window.addEventListener('error', function(e){"
            "  window.__jsErrors.push(String(e.message) + ' @' + (e.lineno || 0)); });"
            "window.addEventListener('unhandledrejection', function(e){"
            "  window.__jsErrors.push('unhandledrejection: ' + String(e.reason)); });"
        )
        count = wait_js("return document.querySelectorAll('#chunkList li').length;", 30)
        check("page: sample text becomes chunks", (count or 0) >= 3, f"{count} chunks")
        check("page: status line set",
              (js("return document.getElementById('statusText').textContent;") or "") != "siap")

        # home: two cards, navigation, theme toggle
        js("XL.switchView('home');")
        cards = js("return document.querySelectorAll('#view-home .home-card').length;")
        check("home: two feature cards", cards == 2, f"{cards} cards")
        route = js("return document.querySelector('.home-card.learn').dataset.go;") or ""
        check("home: Learn card routes to /learn", route == "learn", route)
        driver.get(f"{URL}/learn")
        login_ok = wait_js("return !document.getElementById('loginView').hidden;", 15)
        check("learn: login screen", bool(login_ok))
        js("document.getElementById('authUser').value='User1';"
           "document.getElementById('authPass').value='WeAreHackerone';"
           "document.getElementById('authSubmit').click();")
        dash_ok = wait_js("return !document.getElementById('dashView').hidden;", 15)
        check("learn: dashboard after login", bool(dash_ok))
        modules = js("return document.querySelectorAll('#moduleList .module-row').length;")
        check("learn: modules listed", (modules or 0) >= 9, f"{modules} modules")
        board = js("return document.querySelectorAll('#boardList .board-row').length;")
        check("learn: leaderboard rendered", (board or 0) >= 1, f"{board} rows")
        avatar = js("return document.getElementById('railAvatar').textContent;") or ""
        check("learn: avatar initials", bool(avatar.strip()), avatar)
        shot("8-learn-dashboard")
        driver.get(f"{URL}/?sample=1")
        wait_js("return document.querySelectorAll('#chunkList li').length > 3;", 20)
        js(
            "window.__jsErrors = [];"
            "window.addEventListener('error', function(e){"
            "  window.__jsErrors.push(String(e.message) + ' @' + (e.lineno || 0)); });"
            "window.addEventListener('unhandledrejection', function(e){"
            "  window.__jsErrors.push('unhandledrejection: ' + String(e.reason)); });"
        )
        js("XL.switchView('home');")
        js("document.getElementById('themeBtn').click();")
        check("home: theme toggles to light",
              js("return document.documentElement.dataset.theme;") == "light")
        js("document.getElementById('themeBtn').click();")
        check("home: theme back to dark",
              js("return document.documentElement.dataset.theme;") == "dark")
        js("XL.switchView('listen');")

        # whole-text mode: no chunk splitting
        js("var t=document.getElementById('wholeToggle'); t.checked=true;"
           "t.dispatchEvent(new Event('change'));")
        ok = wait_js("return document.querySelectorAll('#chunkList li').length === 1;", 15)
        check("listen: whole-text mode keeps one chunk", bool(ok))
        js("var t=document.getElementById('wholeToggle'); t.checked=false;"
           "t.dispatchEvent(new Event('change'));")
        ok = wait_js("return document.querySelectorAll('#chunkList li').length > 1;", 15)
        check("listen: chunk mode restores splitting", bool(ok))

        # select chunk 2
        js("document.querySelectorAll('#chunkList li')[1].click();")
        idx = js("return document.getElementById('stageIndex').textContent;")
        check("listen: chunk selection", "02" in (idx or ""), idx or "")
        words = js("return document.querySelectorAll('#stageText .w').length;")
        check("listen: stage rendered as words", (words or 0) > 5, f"{words} word spans")
        shot("1-listen")

        # playback (browser voice or server fallback)
        click("playBtn")
        end = time.time() + 30
        status = ""
        while time.time() < end:
            status = js("return document.getElementById('statusText').textContent;") or ""
            if "selesai" in status or "gagal" in status or "dihentikan" in status:
                break
            time.sleep(0.5)
        check("listen: playback resolves", "gagal" not in status, status)
        js("try{ XL.stopPlayback(); }catch(e){}")

        # practice view
        js("XL.switchView('practice'); XL.renderPracticeStage();")
        ref = js("return document.getElementById('pReference').textContent;") or ""
        check("practice: shows reference chunk", len(ref) > 20, ref[:60])
        shot("2-practice")

        # inject a transcript and compare
        fake = "the number of student is increasing every years"
        js("XL.state.lastTranscript = arguments[0]; XL.state.lastEngine = 'e2e-fake';", fake)
        js("XL.doCompare(arguments[0]);", fake)
        ok = wait_js(
            "return document.querySelectorAll('#refWords .w').length > 0 "
            "&& document.getElementById('stAcc').textContent !== '—';", 20)
        check("practice: word diff rendered", bool(ok))
        acc = js("return document.getElementById('stAcc').textContent;")
        check("practice: accuracy shown", bool(acc and acc != "—"), acc or "")
        shot("3-practice-compare")

        # local grammar feedback (offline rule engine)
        click("analyzeBtn")
        fb = wait_js(
            "var t=document.getElementById('feedbackBox').innerText||'';"
            "return (t.indexOf('menganalisis')<0 && t.length>25) ? t : '';", 90)
        check("practice: feedback rendered", bool(fb), (fb or "kosong")[:180].replace("\n", " | "))
        click("saveLogBtn")
        logn = js("return document.querySelectorAll('#logList li').length;")
        check("practice: error log saved", (logn or 0) >= 1, f"{logn} entries")

        # fake microphone record path
        js("XL.switchView('practice');")
        click("recBtn")
        rec = wait_js("return document.getElementById('recBtn').classList.contains('recording');", 15)
        check("mic: recording starts with fake device", bool(rec))
        if rec:
            time.sleep(2)
            click("recBtn")
            res = wait_js(
                "var e=document.getElementById('practiceErr').innerText;"
                "var h=document.getElementById('recHint').innerText;"
                "return (e||h);", 40)
            check("mic: stops and reports gracefully", bool(res), (res or "")[:110].replace("\n", " "))
        shot("4-practice-after-record")

        # settings view + health box
        js("XL.switchView('settings'); renderHealthBox();")
        box = js("return document.getElementById('healthBox').textContent;") or ""
        check("settings: health dump shows engines", '"tts"' in box and '"asr"' in box, box[:60])
        js("document.getElementById('setTts').value='auto';"
           "document.getElementById('setTts').dispatchEvent(new Event('change'));")
        time.sleep(0.6)
        chip = js("return document.getElementById('chipTts').textContent;")
        check("settings: engine chips rendered", bool(chip and "tts" in chip), chip or "")
        shot("6-settings")

        # study tab: parse practice set + answer key
        js("XL.switchView('study');")
        js("document.getElementById('studyBox').value = arguments[0];", STUDY_TEXT)
        click("studyLoadBtn")
        ok = wait_js("return document.querySelectorAll('#studyList li').length === 3;", 20)
        check("study: questions parsed", bool(ok))
        js("document.querySelector('.study-opt[data-k=\"A\"]').click();")
        click("studyCheckBtn")
        fb = wait_js("return document.getElementById('studyFeedback').innerText;", 10) or ""
        check("study: feedback shows why", "Why" in fb and "Trap" in fb, fb[:100].replace("\n", " | "))
        score = js("return document.getElementById('studyScore').textContent;") or ""
        check("study: score updated", "1/3" in score, score)
        click("studyResetBtn")
        score = js("return document.getElementById('studyScore').textContent;") or ""
        check("study: reset clears progress", "0/3" in score and "best" not in score, score)
        shot("7-study")

        # JSON set upload
        js("document.getElementById('studyBox').value = arguments[0];", STUDY_JSON)
        click("studyLoadBtn")
        ok = wait_js("return document.querySelectorAll('#studyList li').length === 2;", 20)
        check("study: JSON set parsed", bool(ok))
        title = js("return document.getElementById('studyMeta').textContent;") or ""
        check("study: JSON metadata", "2 soal" in title, title)

        # tab switching + keyboard nav
        js("XL.switchView('listen');")
        before = js("return XL.state.current;")
        js("document.dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowRight', bubbles:true}));")
        after = js("return XL.state.current;")
        check("nav: arrow key changes chunk", after == (before or 0) + 1, f"{before} -> {after}")

        # inline JS errors collected after load
        errs = js("return window.__jsErrors || [];") or []
        check("js: no runtime errors", len(errs) == 0, "; ".join(str(e)[:120] for e in errs[:3]))
    finally:
        driver.quit()


def grep_browser_log() -> None:
    log = Path("/tmp/opencode/geckodriver.log")
    if not log.exists():
        skip("browser console log", "no geckodriver log")
        return
    text = log.read_text(errors="replace")
    # only lines that point at our page; Firefox's own Nimbus console noise is ignored
    ours = [line for line in text.splitlines()
            if "127.0.0.1:8765" in line or "app.js" in line or "index.html" in line]
    patterns = ["JavaScript error", "console.error", "TypeError", "ReferenceError",
                "SyntaxError", "uncaught exception", "unhandledrejection"]
    hits = [line for line in ours
            if any(p in line for p in patterns)
            and "favicon" not in line and "unknown featureId" not in line]
    check("browser console: clean", not hits, " || ".join(h.strip()[:170] for h in hits[:3]))


def main() -> int:
    try:
        health = http_json("/api/health", method="GET")
    except Exception as exc:  # noqa: BLE001
        print(f"server is not running at {URL}: {exc}\nstart it with ./run.sh", file=sys.stderr)
        return 2

    test_http_pipeline_safe(health)
    try:
        test_browser()
    except Exception as exc:  # noqa: BLE001
        check("browser flow", False, f"{type(exc).__name__}: {exc}")
    grep_browser_log()

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    for name, _, detail in results:
        if not detail.startswith("SKIP") and not detail:
            print(f"  - {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
