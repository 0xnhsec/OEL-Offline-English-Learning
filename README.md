# OEL — Offline English Learning 🗣️

**OEL** adalah web app lokal (localhost) untuk latihan **listening + speaking** dan **belajar grammar**, jalan sepenuhnya **offline tanpa API key**. Dengarkan teks, tirukan dengan suara, kerjakan soal, lalu dapatkan pembahasan — semua diproses di mesin sendiri.

Halaman utama menampilkan dua kartu: **Learn 101** (bank soal + pembahasan) dan **Speaking & Listening** (TTS + STT). Navigasi memakai kartu; setiap halaman fitur punya tombol **← Home**. Tersedia tema **dark** (default, aksen hijau) dan **light**.

## Fitur

| Tab | Isi |
|---|---|
| **Home** | Dua kartu utama: Learn 101 (login → dashboard) dan Speaking & Listening |
| **Listen** | Upload `.txt`/`.md`/`.srt` atau tempel teks → otomatis dipotong jadi shadowing chunks (1–2 kalimat, ±30 kata) **atau centang “baca utuh” untuk membaca seluruh teks tanpa dipotong** → dengarkan per chunk/utuh dengan highlight kata-per-kata, rate 0.5×–1.5×, **pitch 0.85×–1.15×**, engine piper/gtts |
| **Practice** | Rekam suara mic → speech-to-text → bandingkan dengan chunk acuan (diff warna: persis/beda/terlewat/tambahan) → putar ulang rekamanmu + lihat level audio → minta koreksi lokal (Fix / Why / Try) → simpan ke error log |
| **Learn 101** | Halaman khusus `/learn`: login/daftar akun lokal → dashboard berisi progres, modul soal (10 set, 279 soal), leaderboard, dan quick actions |
| **Study** | Upload/tempel practice set **TXT atau JSON** + answer key → kerjakan soal satu per satu → cek jawaban + pembahasan (Why/Trap) → skor, **best score**, dan progres tersimpan. Tombol **Reset** mengosongkan progres set itu. Tersedia tombol “Muat contoh” (12 soal) |
| **Settings** | Pilih engine TTS/STT, pitch & kecepatan baca, input mikrofon, jumlah kalimat/kata per chunk, dump status engine |

## Menjalankan

```bash
git clone https://github.com/0xnhsec/OEL-Offline-English-Learning.git
cd OEL-Offline-English-Learning

./run.sh                 # → http://127.0.0.1:8765
PORT=9000 ./run.sh       # port lain
```

Pertama kali: script membuat `.venv`, install `requirements.txt`, dan mengunduh model (piper voice + whisper `base.en`) secara otomatis.

Butuh `python3`, `venv`, dan `ffmpeg` di `PATH`.

**Tanpa AI cloud:** tidak ada API key, tidak ada panggilan ke OpenRouter/Gemini/model eksternal apa pun. Koreksi grammar dijawab engine aturan lokal (26 pola grammar) di server — 100% offline saat engine `piper` + `faster-whisper` dipakai.

Fokus aplikasi: **Text-to-Speech** (baca teks) dan **Speech-to-Text** (tirukan lewat mic, lalu bandingkan). Rekaman bisa diputar ulang langsung di tab Practice; audio pelan otomatis di-normalisasi sebelum dikirim ke whisper.

## Arsitektur

```
server.py            FastAPI: health, TTS/STT, study, auth, modules, leaderboard, settings
eng/tts.py           TTS: piper (offline) → gtts (online); teks panjang dipecah internal lalu digabung; rate/pitch via ffmpeg
eng/asr.py           STT: ffmpeg → WAV 16 kHz mono → faster-whisper (base.en, int8, CPU)
eng/accounts.py      akun lokal: PBKDF2 hash, sesi token, progres, leaderboard (.users.json)
eng/study.py         parser practice set: TXT (numbered + answer key) dan JSON (questions/options/answer/explanation)
eng/textutil.py      pemotongan chunk, alignment kata, ~26 aturan grammar (mesin koreksi utama)
eng/coach.py         koreksi lokal: feedback dijawab engine aturan grammar (bentuk Fix / Why / Try)
static/              HTML/CSS/JS vanilla — Home + 4 tab, tema dark/light, animasi, highlight playback, diff
static/learn.*       halaman Learn 101: login, dashboard, modul, leaderboard
oel-quiz/            bank soal bawaan (10 JSON: 9 modul + exam campuran, 279 soal)
static/assets/       wallpaper hasil optimasi dari Assets/ (bg, learn, listen)
static/samples/      contoh practice set JSON
Assets/              gambar sumber (bg.jpg, learn.jpg, listen.jpg)
tests/               unit/API test (unittest) + e2e.py (Selenium/Firefox headless)
```

## Soal FFmpeg & speech-to-text

**FFmpeg BUKAN speech-to-text.** FFmpeg hanya *mengkonversi audio* (mis. webm/opus dari MediaRecorder → WAV 16 kHz mono yang bisa dibaca whisper) dan mengatur rate/pitch. Pengenalan suaranya dilakukan oleh `faster-whisper` (model Whisper `base.en`, offline di CPU).

Jadi pipeline-nya: mic → ffmpeg (konversi) → whisper (transkrip) → alignment → koreksi.

## Learn 101 (login + dashboard)

Klik kartu **Learn 101** di Home → halaman `/learn`:

- **Login lokal** (username + password). Akun demo: `User1` / `WeAreHackerone` (nama tampilan: `0xnhsec was here`).
- **Buat akun baru** langsung dari tab “Buat akun” — password di-hash PBKDF2-SHA256 (200k rounds + salt), data di `.users.json`.
- **Dashboard** berisi: poin, akurasi, set dikerjakan, daftar 10 modul (klik → buka di Study), leaderboard, dan quick actions.
- **Avatar user** di rail kiri: hover untuk melihat nama, poin, set, dan tombol keluar.
- Progres dikirim otomatis ke server saat jawaban dicek di Study (butuh login), dan server menyimpan **best score** per set.

Akun & sesi tersimpan lokal; `.users.json` di-ignore git.

## Format soal (Learn 101)

**TXT** — seperti practice set biasa:

```
1. [Subject-verb agreement | easy]
The number of students in the class ___ increasing every year.
   A. is
   B. are
...
ANSWER KEY
1. A
   Why : 'The number of' = singular.
   Trap: 'students' terlihat tepat sebelum verb.
```

**JSON** — field yang didukung:

```json
{
  "title": "Essential English Grammar - Practice Set 1",
  "questions": [
    {
      "id": 1,
      "topic": "Subject-verb agreement",
      "difficulty": "easy",
      "question": "The number of students ___ increasing.",
      "options": {"A": "is", "B": "are"},
      "answer": "A",
      "trap": "...",
      "explanation": "..."
    }
  ]
}
```

`options` juga boleh berupa array (`["is", "are"]` → otomatis A, B). `explanation` dipetakan ke **Why**, `trap` ke **Trap**. Kunci boleh tidak ada.

## Engine suara (TTS)

| Engine | Sumber | Kualitas | RAM | Internet |
|---|---|---|---|---|
| **gtts** | Google Translate TTS | jernih, tapi jeda di tanda baca agak panjang | ~0 | ya (teks dikirim ke Google) |
| **piper** | model neural lokal `en_US-lessac-medium` (61 MB ONNX) | konsisten, netral, cocok untuk latihan listening | ~181 MB sesaat | tidak |

Mode `auto`: server memakai **piper** (offline) lalu **gtts** sebagai cadangan. Teks panjang dipecah per kalimat di server lalu digabung kembali menjadi satu audio, dan diputar dalam **satu request** supaya tidak ada jeda panjang di setiap titik. Pitch (0.85×–1.15×) digeser dengan filter `rubberband` (formant-preserved) agar suara tetap natural dan mudah dipahami.

## Catatan jujur

Angka "kecocokan" berasal dari ASR, **bukan penilaian fonetik**. Selisih bisa karena mik/derau/aksen, bukan salah ucap — pakai sebagai petunjuk, bukan vonis. Intonasi/kelancaran tidak bisa dinilai dari teks transkrip.

## Test

```bash
.venv/bin/python -m unittest discover -s tests   # unit/API test
.venv/bin/python tests/e2e.py                    # end-to-end (butuh Firefox + geckodriver)
```
