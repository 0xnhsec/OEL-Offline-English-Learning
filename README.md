<p align="center">
  <img src="OEL.png" alt="OEL — Offline English Learning" width="132">
</p>

<h1 align="center">OEL — Offline English Learning</h1>

<p align="center"><em>Belajar listening, speaking, dan grammar sepenuhnya offline di localhost.</em></p>

**OEL** adalah web app lokal untuk latihan **listening + speaking** dan **belajar grammar**, jalan sepenuhnya **offline tanpa API key**. Dengarkan teks, tirukan dengan suara, kerjakan soal, lalu dapatkan pembahasan — semua diproses di mesin sendiri. Ikon resmi aplikasi: [`OEL.png`](OEL.png).

Halaman utama menampilkan dua kartu: **Learn 101** (bank soal + pembahasan) dan **Speaking & Listening** (TTS + STT). Navigasi memakai kartu; setiap halaman fitur punya tombol **← Home**. Tersedia tema **dark** (default, aksen hijau) dan **light**.

## Fitur

| Tab | Isi |
|---|---|
| **Home** | Dua kartu utama: Learn 101 (login → dashboard) dan Speaking & Listening |
| **Listen** | Upload `.txt`/`.md`/`.srt` atau tempel teks → otomatis dipotong jadi shadowing chunks (1–2 kalimat, ±30 kata) **atau centang “baca utuh” untuk membaca seluruh teks tanpa dipotong** → dengarkan per chunk/utuh dengan highlight kata-per-kata, rate 0.5×–1.5×, **pitch 0.85×–1.15×**, engine piper/gtts |
| **Practice** | Rekam suara mic → speech-to-text → bandingkan dengan chunk acuan (diff warna: persis/beda/terlewat/tambahan) → putar ulang rekamanmu + lihat level audio → minta koreksi lokal (Fix / Why / Try) → simpan ke error log |
| **Learn 101** | Halaman khusus `/learn`: login/daftar akun lokal → dashboard berisi progres, modul soal (10 set, 279 soal), leaderboard dengan foto profil, dan quick actions |
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

## Kalau perubahan tidak muncul

Kasus paling sering: **server lama masih memegang port 8765**, jadi `./run.sh` yang baru gagal bind (`address already in use`) dan browser tetap membuka proses lama.

```bash
./run.sh                 # sekarang otomatis mematikan instance lama di port itu dulu
PORT=9000 ./run.sh       # kalau port benar-benar dipakai app lain
RELOAD=1 ./run.sh        # auto-reload untuk perubahan server.py / eng/*.py
```

Cek cepat, server ini melayani folder & file yang mana:

```bash
curl -s http://127.0.0.1:8765/api/version
# → {"root": ".../OEL-Offline-English-Learning", "files": {"index.html": {"mtime": ..., "sha1": ...}}}
```

Catatan:

- `static/*.html|css|js` dibaca **langsung dari disk** setiap request dan dikirim dengan `Cache-Control: no-store`, jadi edit → reload browser, tanpa restart.
- Perubahan `server.py` / `eng/*.py` butuh restart (`Ctrl+C` lalu `./run.sh`), atau pakai `RELOAD=1`.
- `/`, `/learn`, `/static/*`, `/avatars/*` tidak pernah di-cache browser; kalau masih aneh, cek `sha1`/`mtime` di `/api/version` vs file di disk.

## Akun & leaderboard

- **Akun default siap pakai:** username `user`, password `user` (dibuat otomatis saat pertama jalan).
- **Rank 1 permanen — `Noshiro`**: entri legenda yang ditanam by design di puncak leaderboard, bukan akun nyata (tidak bisa login) dan fotonya tetap [`static/assets/ayang.png`](static/assets/ayang.png).
- **Klik baris Noshiro di leaderboard** → kartu bio muncul:

  | Field | Isi |
  |---|---|
  | Name | `Ayanagi Noshiro (noun)` |
  | Gender | `She` |
  | Address | `Akita, Japan.` |

- **Foto profil sendiri:** setiap user bisa upload gambar sendiri — hover avatar di rail kiri → **Ganti foto** (PNG/JPG/WEBP/GIF, maks 4 MB) atau **Hapus** untuk kembali ke inisial. Foto tampil di rail, topbar, dan leaderboard.
- Foto disimpan di `.avatars/<username>.<ext>` dan disajikan dari `/avatars/...`; folder ini di-ignore git, jadi tidak ikut ter-commit.

## Arsitektur

```
server.py            FastAPI: health, TTS/STT, study, auth, avatar, modules, leaderboard, settings
eng/tts.py           TTS: piper (offline) → gtts (online); teks panjang dipecah internal lalu digabung; rate/pitch via ffmpeg
eng/asr.py           STT: ffmpeg → WAV 16 kHz mono → faster-whisper (base.en, int8, CPU)
eng/accounts.py      akun lokal: PBKDF2 hash, sesi token, progres, leaderboard, legenda Noshiro, foto profil (.users.json + .avatars/)
eng/study.py         parser practice set: TXT (numbered + answer key) dan JSON (questions/options/answer/explanation)
eng/textutil.py      pemotongan chunk, alignment kata, ~26 aturan grammar (mesin koreksi utama)
eng/coach.py         koreksi lokal: feedback dijawab engine aturan grammar (bentuk Fix / Why / Try)
static/              HTML/CSS/JS vanilla — Home + 4 tab, tema dark/light, animasi, highlight playback, diff
static/learn.*       halaman Learn 101: login, dashboard, modul, leaderboard, bio, foto profil
static/assets/       wallpaper hasil optimasi + ikon OEL.png + avatar legenda ayang.png
oel-quiz/            bank soal bawaan (10 JSON: 9 modul + exam campuran, 279 soal)
Assets/              gambar sumber (bg.jpg, learn.jpg, listen.jpg, ayang.png)
OEL.png              ikon aplikasi 1254×1254 (dipakai di README, favicon & rail logo)
tests/               unit/API test (unittest) + e2e.py (Selenium/Firefox headless)
```

## API singkat

| Endpoint | Fungsi |
|---|---|
| `POST /api/auth/login` · `/register` · `/logout`, `GET /api/auth/me` | sesi lokal (Bearer token) |
| `POST /api/auth/avatar` · `DELETE /api/auth/avatar` | upload / hapus foto profil user |
| `GET /api/leaderboard` | peringkat + entri legenda `Noshiro` (bio & avatar ikut) |
| `POST /api/progress` | simpan best score per set |
| `GET /api/modules` · `/api/modules/{id}` | bank soal dari `oel-quiz/` |
| `POST /api/tts` · `/api/transcribe` · `/api/compare` · `/api/analyze` | TTS, STT, alignment, koreksi lokal |

## Soal FFmpeg & speech-to-text

**FFmpeg BUKAN speech-to-text.** FFmpeg hanya *mengkonversi audio* (mis. webm/opus dari MediaRecorder → WAV 16 kHz mono yang bisa dibaca whisper) dan mengatur rate/pitch. Pengenalan suaranya dilakukan oleh `faster-whisper` (model Whisper `base.en`, offline di CPU).

Jadi pipeline-nya: mic → ffmpeg (konversi) → whisper (transkrip) → alignment → koreksi.

## Learn 101 (login + dashboard)

Klik kartu **Learn 101** di Home → halaman `/learn`:

- **Login lokal** (username + password). Akun default: `user` / `user`.
- **Buat akun baru** langsung dari tab “Buat akun” — password di-hash PBKDF2-SHA256 (200k rounds + salt), data di `.users.json`.
- **Dashboard** berisi: poin, akurasi, set dikerjakan, daftar 10 modul (klik → buka di Study), leaderboard, dan quick actions.
- **Avatar user** di rail kiri: hover untuk melihat nama, poin, set, tombol **Ganti foto / Hapus**, dan tombol keluar.
- Progres dikirim otomatis ke server saat jawaban dicek di Study (butuh login), dan server menyimpan **best score** per set.

Akun & sesi tersimpan lokal; `.users.json` dan `.avatars/` di-ignore git.

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
.venv/bin/python -m unittest discover -s tests   # 71 unit/API test
.venv/bin/python tests/e2e.py                    # end-to-end (butuh Firefox + geckodriver)
```
