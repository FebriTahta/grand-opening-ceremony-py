   # Grand Opening Ceremony

Aplikasi desktop (full Python) untuk acara peresmian / grand opening yang dikendalikan dengan gesture tangan.

```
IDLE ──🙌 hi-five 2 tangan──► LISTENING ──👏 clap ×2──► COUNTDOWN ──► VIDEO ──► SELESAI
  ▲                               │ timeout                                      │
  └───────────────────────────────┴──────────── ✊ batu (reset) ◄────────────────┘
```

- **Hi-five dua tangan**: kedua telapak terbuka menghadap kamera, jari ke atas, ditahan ±0,8 detik → masuk mode mendengarkan.
- **Clap 2×**: dihitung dari kamera (tangan mendekat → bersentuhan → menjauh), opsional dikonfirmasi mikrofon. Setelah 2 tepukan → countdown.
- **Countdown → video**: video aktif dari pengaturan diputar fullscreen, lalu layar akhir (bisa diatur).
- **Tangan batu ✊** ditahan ±2 detik → reset ke awal (tahap yang mengizinkan reset bisa diatur).
- Operator **selalu** bisa mengambil alih dengan keyboard: `Space` lanjut, `Esc` reset.

Stack: PySide6 (Qt) · MediaPipe Hand Landmarker · OpenCV · sounddevice · numpy. Semua berjalan **offline**
(model MediaPipe disertakan di `models/`).

---

## 1. Instalasi

Aplikasi berjalan di **macOS** (Apple Silicon/Intel) dan **Windows 10/11 64-bit**. Butuh
[uv](https://docs.astral.sh/uv/); uv akan mengunduh Python 3.12 dan semua dependensi sendiri.

**macOS** (uv sudah terpasang di mesin ini):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # hanya jika uv belum ada
cd grand-opening-ceremony
uv sync
```

**Windows** (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"   # hanya jika uv belum ada
cd grand-opening-ceremony
uv sync
```

Salin folder project **tanpa** `.venv` ke laptop lain, lalu jalankan `uv sync` di sana (butuh internet
sekali, ±600 MB). Setelah itu aplikasi berjalan sepenuhnya offline.

## 2. Menjalankan

### 2.1 Mulai cepat

| | macOS | Windows |
|---|---|---|
| **Dobel-klik** | `start-mac.command` | `start-windows.bat` |
| **Terminal** | `uv run ceremony` | `uv run ceremony` |

Perintah terminal dijalankan dari dalam folder `grand-opening-ceremony`. Setelah dijalankan akan muncul
dua jendela: **Operator** (di layar laptop) dan **Stage** (fullscreen di layar terakhir, biasanya proyektor).

> **Dobel-klik pertama kali diblokir?**
> macOS: klik kanan `start-mac.command` › **Open** › **Open**.
> Windows: jika muncul *"Windows protected your PC"*, klik **More info** › **Run anyway**.

### 2.2 Opsi perintah

| Perintah | Kegunaan |
|---|---|
| `uv run ceremony` | Mode acara: Operator + Stage fullscreen |
| `uv run ceremony --windowed` | Stage sebagai jendela biasa — untuk mencoba di laptop tanpa proyektor |
| `uv run ceremony --no-camera` | Tanpa kamera & mic; alur dijalankan dengan keyboard (`H`, `C`, `B`, `Space`) |
| `uv run ceremony --data-dir <folder>` | Pakai folder data lain (mis. di flashdisk) untuk pengaturan, video, logo |
| `uv run ceremony --help` | Menampilkan semua opsi |

Opsi bisa digabung, misalnya `uv run ceremony --windowed --no-camera`. Folder data juga bisa diatur
lewat environment variable `CEREMONY_DATA_DIR`. Opsi juga bisa diberikan ke launcher dobel-klik dari
terminal: `start-windows.bat --windowed` atau `./start-mac.command --windowed`.

### 2.3 Menjalankan pertama kali

1. **Jalankan dalam mode jendela** supaya mudah dicoba di satu layar:
   ```bash
   uv run ceremony --windowed
   ```
2. **Berikan izin kamera & mikrofon** (lihat *Izin kamera & mikrofon* di bawah). Di jendela Operator,
   status harus menunjukkan 🟢 *Kamera #0 aktif* dan angka FPS sekitar 30.
3. **Isi teks acara**: klik **⚙ Pengaturan › Teks**, isi nama acara, judul (nama perusahaan/gedung),
   subjudul, dan teks penutup. Klik **Simpan**.
4. **Tambahkan video**: **⚙ Pengaturan › Video › ➕ Tambah video…**, pilih file MP4. Video pertama otomatis
   menjadi video aktif (★). Klik **Simpan**. Status *Video:* di Operator berubah menjadi 🟢.
5. **(Opsional) Logo & warna**: **⚙ Pengaturan › Tampilan**.
6. **Coba alurnya**:
   - Berdiri di depan kamera, angkat **kedua telapak tangan** (jari ke atas) dan tahan sampai lingkaran
     di Stage penuh → layar berganti ke *Tepuk tangan 2x*.
   - **Tepuk tangan 2×** → titik indikator terisi satu per satu → countdown → video diputar.
   - Setelah selesai, **kepalkan tangan (batu ✊)** dan tahan ±2 detik → kembali ke awal.
7. Jika gesture belum terbaca, jalankan alur dengan keyboard dulu (`H` → `C` `C` → tunggu → `B`) untuk
   memastikan teks & video sudah benar, lalu setel deteksi sesuai **4. Checklist gladi di venue**.

### 2.4 Mencoba tanpa kamera

```bash
uv run ceremony --windowed --no-camera
```

| Tombol | Mensimulasikan |
|---|---|
| `H` | Hi-five dua tangan (mulai mendengarkan) |
| `C` | Satu tepukan (tekan 2× untuk mulai countdown) |
| `B` | Tangan batu (reset) |
| `Space` / `Esc` | Lanjut / reset seperti operator |

Cocok untuk menyiapkan teks, tampilan, dan video di laptop mana pun sebelum ke venue.

### 2.5 Alur di hari acara

**Sebelum tamu datang**

1. Sambungkan proyektor/TV, kamera (jika eksternal), mic, dan charger. Matikan mode sleep & notifikasi.
2. Jalankan `start-mac.command` / `start-windows.bat` (atau `uv run ceremony`).
3. Pastikan Stage tampil fullscreen di proyektor. Jika di layar yang salah: **⚙ Pengaturan › Perangkat ›
   Tampilkan di**, atau tekan `F` untuk keluar fullscreen, seret jendela ke proyektor, tekan `F` lagi.
4. Cek tiga status di jendela Operator: **Kamera** 🟢 (±30 FPS), **Mic** 🟢, **Video** 🟢.
5. Lakukan satu kali uji coba penuh (lihat checklist gladi), lalu tekan `Esc` untuk kembali ke awal.
   Stage kini menampilkan judul acara dan petunjuk *Angkat kedua telapak tangan*.

**Saat peresmian**

| VIP melakukan | Stage menampilkan | Operator memantau |
|---|---|---|
| — | Judul acara + petunjuk hi-five | Fase **MENUNGGU HI-FIVE** |
| 🙌 Angkat kedua telapak & tahan | Lingkaran progres penuh, bunyi konfirmasi | Bar *Hi-five* penuh → fase **MENDENGARKAN** |
| 👏 Tepuk tangan 2× | Titik indikator terisi ●○ → ●● | Log: `✓ DIHITUNG` per tepukan |
| — | Countdown 5 → 1, teks akhir, confetti | Fase **COUNTDOWN** |
| — | Video diputar fullscreen | Fase **MEMUTAR VIDEO** |
| — | Frame terakhir / layar penutup | Fase **SELESAI** |

**Jika ada masalah saat live** — operator tidak perlu menunggu gesture:

- Gesture tidak terbaca → tekan `Space` untuk maju satu tahap (hi-five → countdown → video → selesai).
- Salah mulai / perlu ulang → tekan `Esc`.
- Video tidak mulai dalam 5 detik → aplikasi otomatis lanjut ke layar penutup.
- Kamera atau mic terputus → aplikasi mencoba menyambung ulang otomatis; mic yang gagal otomatis
  dialihkan ke mode *Kamera saja*. `Space`/`Esc` tetap berfungsi.

Klik jendela Operator lebih dulu agar shortcut keyboard diterima (shortcut berlaku di jendela Operator
maupun Stage).

**Setelah acara**: tekan `Esc` untuk kembali ke awal bila ingin mengulang (mis. untuk sesi foto), atau
tutup aplikasi.

### 2.6 Menghentikan aplikasi

- Tutup jendela **Operator** (tombol ✕ atau `⌘Q` / `Alt+F4`) lalu konfirmasi **Yes**. Jendela Stage ikut tertutup.
- Jika dijalankan dari terminal: tekan `Ctrl+C`.
- Menutup jendela Stage saja tidak menghentikan aplikasi; tekan `F` di jendela Operator untuk menampilkannya lagi.

### 2.7 Izin kamera & mikrofon

- **macOS**: saat pertama kali dijalankan, macOS meminta izin **Kamera** dan **Mikrofon** untuk Terminal
  (atau iTerm/VS Code). Izinkan, lalu jalankan ulang. Jika terlanjur ditolak:
  *System Settings › Privacy & Security › Camera / Microphone*.
- **Windows**: pastikan *Settings › Privacy & security › Camera* dan *Microphone* → **"Let desktop apps
  access your camera/microphone"** aktif. Tutup aplikasi lain yang memakai kamera (Zoom, Teams, OBS),
  karena di Windows kamera hanya bisa dipakai satu aplikasi sekaligus.

### 2.8 Dua jendela

| Jendela | Isi |
|---|---|
| **Stage** | Tampilan untuk penonton/proyektor: judul, petunjuk gesture, indikator tepukan, countdown, video. Kursor disembunyikan saat fullscreen. |
| **Operator** | Preview kamera + kerangka tangan (hijau = tangan VIP yang dipakai, abu-abu = diabaikan), grafik jarak telapak, level mic, progress hi-five/reset, hitungan tepukan, log, tombol kontrol, pengaturan. |

### 2.9 Shortcut keyboard (berlaku di kedua jendela)

| Tombol | Fungsi |
|---|---|
| `Space` | Lanjut ke tahap berikutnya (cadangan jika gesture gagal) |
| `Esc` | Reset ke awal |
| `H` / `C` / `B` | Simulasi hi-five / clap / batu |
| `F` | Fullscreen stage on/off |
| `Ctrl+,` (`⌘,` di macOS) | Buka pengaturan (dari jendela Operator) |

## 3. Pengaturan

Klik **⚙ Pengaturan** di jendela operator. Perubahan baru berlaku setelah **Simpan**.

| Tab | Isi |
|---|---|
| **Teks** | Nama acara, judul, subjudul, instruksi tiap tahap (`{count}` = jumlah tepukan), label & teks akhir countdown, teks penutup. |
| **Tampilan** | Warna latar/teks/aksen, jenis huruf, logo, gambar latar. |
| **Video** | Tambah/hapus video, pilih video aktif (★), pratinjau, volume, perilaku setelah video: diam di frame terakhir / layar penutup / kembali ke awal / ulang terus; kembali otomatis setelah N detik. |
| **Gesture** | Lama tahan hi-five & batu, batu 1 atau 2 tangan, di tahap mana batu boleh reset, timeout menunggu tepukan, ambang deteksi MediaPipe, **area deteksi** (ROI). |
| **Clap & Audio** | Jumlah tepukan (default 2), jeda maks/min antar tepukan, ambang kontak/lepas, mode konfirmasi suara, pilihan mikrofon, sensitivitas, toleransi & selisih latensi. |
| **Countdown** | **Gaya tampilan** (6 pilihan, dengan pratinjau langsung), durasi, lama teks akhir, efek suara & volumenya. |
| **Perangkat** | Nomor kamera, resolusi, FPS, cermin preview, layar untuk stage, fullscreen. |

Semua data disimpan di folder data (ditampilkan di bawah jendela operator):

- macOS: `~/Library/Application Support/GrandOpeningCeremony/`
- Windows: `%APPDATA%\GrandOpeningCeremony\`

```
settings.json   ← semua pengaturan (boleh dicadangkan / disalin ke laptop lain)
videos/         ← video yang diunggah
assets/         ← logo & gambar latar
sounds/         ← efek suara (dibuat otomatis)
logs/           ← ceremony.log: catatan setiap gesture, tepukan, perpindahan fase, dan pemutaran video
```

Jika sesuatu tidak berjalan sesuai harapan (mis. kembali ke awal tanpa sebab, video tidak diputar),
buka `logs/ceremony.log`. Setiap perpindahan fase mencatat penyebabnya, contoh:

```
INFO    FASE → COUNTDOWN (oleh: gesture)
INFO    RESET (oleh: gesture) dari fase countdown     ← reset karena gesture batu
INFO    FASE → IDLE (oleh: timeout)                    ← tidak ada tepukan dalam batas waktu
INFO    video setelah countdown: TIDAK ADA             ← belum ada video di pustaka
ERROR   video error: ...                               ← file video bermasalah
```

Untuk membawa konfigurasi lengkap ke laptop acara, salin seluruh folder tersebut, atau jalankan
dengan `--data-dir` ke folder di flashdisk.

### Gaya countdown

Pilih di **⚙ Pengaturan › Countdown › Gaya countdown**. Pratinjau di bawah pilihan langsung memutar
hitungan 3-2-1 dengan gaya tersebut, persis seperti di layar Stage. Semua gaya memakai warna aksen & teks
dari tab Tampilan (kecuali *Serat optik*, yang memakai palet biru-ungu sendiri).

| Gaya | Tampilan |
|---|---|
| **Cincin klasik** (default) | Angka besar dengan cincin yang berkurang setiap detik |
| **Kartu flip** | Kartu angka seperti papan jadwal bandara, berganti dengan animasi lipat; bar progres di bawahnya |
| **Neon** | Angka bercahaya seperti tabung neon dengan cincin neon; berkedip saat angka berganti |
| **Minimalis** | Angka tipis berukuran raksasa yang meluncur naik, garis progres tipis di bawah |
| **Gelombang kejut** | Angka menghentak masuk diiringi gelombang cincin dan kilatan cahaya — paling dramatis |
| **Segmen stadion** | Lingkaran segmen (satu per detik, maks. 60) yang padam satu per satu, seperti papan skor |
| **Serat optik** | Latar ratusan serat optik biru-ungu yang melambai dengan denyut cahaya berjalan; angka tampil sebagai kabel bercahaya dengan cincin kabel yang menyusut. Teks akhir meledak menjadi pancaran serat dari tengah layar |

Teks di atas angka (*Label di atas angka*) dan teks akhir (*DIBUKA!*) diatur di tab **Teks**.

### Mode konfirmasi tepukan

Kamera **selalu wajib**. Suara saja tidak pernah menghitung tepukan, jadi tepuk tangan penonton,
musik, atau MC di luar frame tidak bisa memicu countdown.

| Mode | Aturan | Cocok untuk |
|---|---|---|
| **Seimbang** (default) | Kontak jelas di kamera cukup; kontak ragu (tangan hilang saat bersentuhan) butuh bunyi tepukan | Venue umum dengan musik |
| **Ketat** | Selalu butuh kamera **dan** bunyi tepukan | Venue tenang, paling anti salah-picu |
| **Kamera saja** | Mic tidak dipakai | Mic bermasalah / venue sangat bising |

Jika mic gagal atau dicabut, aplikasi otomatis memakai *Kamera saja* dan menampilkan peringatan
di jendela operator.

## 4. Checklist gladi di venue

1. **Kamera**: pasang menghadap posisi VIP, setinggi dada–kepala, jarak 1,5–3 m. Pastikan wajah &
   kedua tangan VIP masuk frame dengan cahaya cukup (lampu sorot dari belakang VIP membuat deteksi buruk).
2. **Layar**: sambungkan proyektor, buka *Pengaturan › Perangkat › Tampilkan di* dan pilih layarnya.
3. **Area deteksi**: jika banyak orang dalam frame, persempit *Gesture › Area deteksi* hingga hanya
   posisi VIP (kotak emas di preview). Tangan VIP harus berwarna **hijau** di preview.
4. **Mic**: gunakan mic dekat podium (bukan mic laptop di dekat speaker). Pilih di *Clap & Audio › Mikrofon*.
5. **Kalibrasi audio**: klik **🎯 Kalibrasi audio**, lalu tepuk tangan 6× di depan kamera dengan jeda ±1 detik.
   Hasil disimpan otomatis.
6. **Uji alur lengkap** beberapa kali: hi-five → clap 2× → countdown → video → batu (reset).
   Perhatikan log tepukan: tiap tepukan menampilkan 👁 (kamera) dan 🔊 (suara).
7. **Setel ambang** jika perlu, dengan melihat grafik jarak di operator:
   - tepukan tidak terhitung → naikkan *Ambang kontak* (mis. 0,9) atau turunkan *Ambang lepas*;
   - satu tepukan terhitung dua → naikkan *Jeda minimal* atau *Ambang lepas*.
8. **Video**: gunakan MP4 H.264 + AAC. Putar sekali sampai habis saat gladi untuk memastikan lancar.
9. Matikan notifikasi/sleep laptop, sambungkan charger.

Jika video tidak mulai dalam 5 detik setelah countdown, aplikasi otomatis lanjut ke layar penutup
supaya panggung tidak macet.

## 5. Membuat aplikasi standalone (opsional)

Build harus dilakukan di OS tujuan (build Windows di Windows, build macOS di Mac).

macOS:

```bash
uv add --dev pyinstaller
uv run pyinstaller --noconfirm --windowed --name "Grand Opening" \
  --add-data "models:models" --collect-all mediapipe run_ceremony.py
```

Windows (PowerShell — perhatikan `;` pada `--add-data`):

```powershell
uv add --dev pyinstaller
uv run pyinstaller --noconfirm --windowed --name "Grand Opening" `
  --add-data "models;models" --collect-all mediapipe run_ceremony.py
```

Hasilnya `dist/Grand Opening.app` (macOS) atau `dist\Grand Opening\Grand Opening.exe` (Windows; bawa
seluruh folder `dist\Grand Opening`). Pada macOS, aplikasi hasil build meminta izin kamera/mic atas
namanya sendiri.

## Troubleshooting Windows

| Gejala | Solusi |
|---|---|
| `ImportError: DLL load failed` saat memuat mediapipe/cv2 | Pasang [Microsoft Visual C++ Redistributable x64](https://aka.ms/vs/17/release/vc_redist.x64.exe) |
| "Kamera #0 tidak bisa dibuka" | Tutup Zoom/Teams/OBS; cek izin kamera; coba nomor kamera 1 atau 2 di *Pengaturan › Perangkat* |
| FPS kamera rendah (≤15) | Turunkan resolusi ke 1280×720; sebagian webcam hanya 30 FPS di 720p |
| Mikrofon muncul beberapa kali di daftar | Sudah digabung otomatis; pilih nama mic yang sesuai |
| Video tidak bisa dihapus | Tutup jendela pratinjau (pemutar Windows) terlebih dahulu |
| Stage muncul di layar yang salah | *Pengaturan › Perangkat › Tampilkan di*, atau tekan `F` lalu seret jendela |

## 6. Pengembangan

```bash
uv run pytest           # unit test logika: deteksi clap, fusi kamera+suara, state machine, onset audio
```

```
ceremony/
├── app.py               entry point, shortcut, wiring jendela
├── config.py            pengaturan (dataclass ↔ settings.json), folder data
├── controller.py        menghubungkan kamera, mic, detektor, dan state machine
├── sounds.py            efek suara (disintesis)
├── engine/
│   ├── state.py         state machine IDLE → LISTENING → COUNTDOWN → VIDEO → FINISHED
│   └── fusion.py        konfirmasi clap kamera + suara, kalibrasi latensi
├── vision/
│   ├── camera.py        thread kamera + MediaPipe
│   ├── hands.py         geometri tangan, pemilihan tangan VIP
│   ├── classify.py      telapak terbuka / batu / tangan terangkat
│   ├── gestures.py      deteksi "ditahan selama N ms"
│   └── clap.py          deteksi tepukan visual (hysteresis + tracking loss)
├── audio/
│   ├── onset.py         deteksi bunyi tepukan (spectral flux adaptif)
│   └── mic.py           input mikrofon
└── ui/
    ├── stage.py         layar penonton + pemutar video
    ├── countdown_styles.py  6 gaya countdown (dipakai stage & pratinjau pengaturan)
    ├── operator.py      konsol operator
    └── settings_dialog.py
```
