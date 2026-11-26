# Subtitle Studio

Aplikasi web lokal untuk mengubah **audio/video menjadi subtitle**, mengedit timing & teks, lalu mengolah videonya — semuanya berjalan di Termux/Android.

![status](https://img.shields.io/badge/offline-whisper.cpp-6f8cff) ![status](https://img.shields.io/badge/online-Groq%20%7C%20OpenAI-2dd4bf)

## Fitur

- **Transkripsi offline** dengan `whisper.cpp` (tanpa internet, tanpa API key).
- **Transkripsi online** dengan Groq (`whisper-large-v3-turbo`) atau OpenAI (`whisper-1`).
- Deteksi bahasa otomatis atau pilih manual (Indonesia, Inggris, Jawa, Sunda, dll.).
- **Editor subtitle**: ubah teks, atur waktu mulai/akhir, geser semua segmen, split, gabung, tambah/hapus segmen.
- Pemutar video/audio terintegrasi; klik segmen untuk melompat ke waktunya.
- Ekspor **SRT, VTT, TXT**.
- **Edit video** dengan FFmpeg:
  - potong/trim klip (akurat atau cepat tanpa encode),
  - tempel/burn subtitle permanen dengan pengaturan font, warna, posisi, outline,
  - gabung beberapa video (otomatis disamakan resolusi/FPS/audio),
  - kompres & resize (CRF, preset, FPS),
  - ekstrak audio (MP3/WAV/M4A).
- Pustaka media dengan thumbnail, preview, dan unduhan hasil render.
- Antrean job dengan progress dan tombol batal.

## Aplikasi Android (APK)

Selain diakses via browser web, Subtitle Studio juga tersedia dalam bentuk aplikasi **APK Android**:
- Tampilan aplikasi mandiri dan layar penuh tanpa bilah URL browser.
- Dialog pemilihan berkas bawaan Android (video, audio, subtitle).
- Pengunduh terintegrasi langsung ke folder **Download** perangkat.
- Deteksi status koneksi server otomatis (dengan tombol *Coba Lagi* dan opsi ubah URL server).

### Pasang APK
1. Unduh **`Subtitle-Studio.apk`** dari tab [Releases](../../releases).
2. Buka berkas APK dan izinkan instalasi dari sumber tidak dikenal bila diminta.
3. Pastikan server Subtitle Studio di Termux sudah berjalan (`./run.sh`), lalu buka aplikasi.

### Bangun APK sendiri di Termux
APK dapat dibangun langsung di Termux tanpa Android Studio atau Gradle:
```bash
./android/build-termux.sh
```
Berkas APK bertanda tangan rilis akan tersimpan di `android/build/Subtitle-Studio-1.0.0.apk`.

## Pasang dari nol (opsional)

Jika memindahkan folder ini ke Termux baru:

```bash
cd ~/subtitle-studio
./setup.sh
```

Skrip memasang FFmpeg, CMake, Flask, membangun `whisper.cpp`, mengunduh model `base`, dan font subtitle. Butuh koneksi internet dan ruang ±500 MB.

## Menjalankan

```bash
cd ~/subtitle-studio
./run.sh
```

Buka di browser HP:

```
http://127.0.0.1:8765
```

Hentikan server dengan `Ctrl+C` di terminal, atau:

```bash
./stop.sh
```

Jika port dipakai aplikasi lain:

```bash
SS_PORT=9000 ./run.sh
```

Untuk diakses dari perangkat lain di Wi-Fi yang sama:

```bash
SS_HOST=0.0.0.0 ./run.sh
# lalu buka http://IP-HP:8765 dari perangkat lain
```

> Aplikasi ini tidak punya login. Hanya gunakan `SS_HOST=0.0.0.0` di jaringan yang kamu percaya.

## Cara pakai singkat

1. **Media** → unggah audio/video (maks. 4 GB).
2. **Transkripsi** → pilih media, mesin, bahasa → **Mulai transkripsi**.
3. Setelah selesai, **Editor Subtitle** terbuka otomatis:
   - putar video, klik segmen untuk melompat,
   - gunakan `[` dan `]` untuk mengambil waktu mulai/akhir dari pemutar,
   - `✂` untuk split, `⇅` untuk gabung dengan segmen berikutnya,
   - geser semua timing dengan tombol ±0,1 s / ±1 s,
   - **Simpan**, lalu ekspor SRT/VTT/TXT.
4. **Edit Video** → pilih tool: Potong, Subtitle (burn), Gabung, Kompres, atau Audio.
5. Hasil render muncul di bagian **Hasil render** dan bisa diunduh.

## Transkripsi offline

Aplikasi memakai build `whisper.cpp` di:

```
~/whisper.cpp/build/bin/whisper-cli
~/whisper.cpp/models/ggml-base.bin   # model default
```

Model lain bisa diunduh langsung dari halaman **Pengaturan**:

| Model | Ukuran | Catatan |
|---|---|---|
| tiny | 75 MB | paling cepat, akurasi rendah |
| base | 142 MB | seimbang untuk HP (default) |
| small | 466 MB | akurasi lebih baik |
| medium | 1,5 GB | akurasi tinggi, lambat |
| large-v3-turbo | 1,6 GB | terbaik, butuh RAM besar |

Perkiraan kecepatan di HP: sekitar **1–3× durasi audio** untuk model `base`, tergantung CPU dan panjang audio. Model `tiny` lebih cepat; `small` ke atas lebih lambat.

Jika lokasi whisper.cpp berbeda, jalankan dengan environment variable:

```bash
WHISPER_DIR=/path/ke/whisper.cpp ./run.sh
```

## Transkripsi online

Buka **Pengaturan → API key online**, isi salah satu:

- **Groq** — https://console.groq.com/keys (ada kuota gratis)
- **OpenAI** — https://platform.openai.com/api-keys

Kunci disimpan lokal di `data/settings.json` dengan permission `600` dan hanya dikirim ke penyedia API saat kamu memilih mesin online. File audio **tidak** dikirim ke mana pun saat memakai mesin offline.

Catatan: Groq membatasi ukuran unggahan (biasanya 25 MB). Aplikasi otomatis mengekstrak audio ke MP3 mono 48 kbps, jadi rekaman ±1–1,5 jam masih muat.

## Penyimpanan

Semua data ada di `~/subtitle-studio/data/`:

```
data/media/<id>/source.*    # file asli
data/media/<id>/thumb.jpg   # thumbnail video
data/media/<id>/meta.json
data/transcripts/<id>.json  # segmen subtitle
data/outputs/               # hasil trim/burn/gabung/kompres/audio
data/settings.json          # setelan + API key
data/tmp/                   # file sementara job
```

Hapus media lewat UI. Transkrip tetap tersimpan walau media sumbernya dihapus, sehingga teks masih bisa diedit/diekspor.

## Catatan teknis

- Server: Flask (Python 3) + antrean job satu worker agar CPU tidak jenuh.
- Video: FFmpeg/FFprobe. Burn subtitle memakai `libass` + font **DejaVu Sans** di `assets/fonts/`.
- Subtitle burn dibuat sebagai ASS dengan `PlayRes` sesuai resolusi video, sehingga ukuran font dalam piksel konsisten.
- File yang diunggah dibatasi ke ekstensi audio/video yang dikenal (mencegah file HTML dieksekusi dari origin yang sama).
- Format output video: MP4 (H.264/AAC). Trim mode "cepat" memakai stream copy dan bisa tidak presisi di awal klip.

## Troubleshooting

**`whisper-cli tidak ditemukan`** — pastikan build ada:

```bash
cd ~/whisper.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release -DWHISPER_BUILD_TESTS=OFF
cmake --build build -j4
```

**Model belum ada** — unduh dari halaman Pengaturan, atau:

```bash
curl -L -o ~/whisper.cpp/models/ggml-base.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin
```

**FFmpeg tidak ditemukan** — `pkg install ffmpeg`.

**Transkripsi terasa lambat** — pakai model `tiny`/`base`, kurangi thread di Pengaturan, atau pakai Groq.

**Subtitle tidak muncul saat burn** — pastikan transkrip sudah disimpan dan memiliki teks. Cek juga file hasil di `data/outputs/`.

**API error 401** — kunci salah/kedaluwarsa. Isi ulang di Pengaturan.

**Tidak bisa diakses dari HP lain** — jalankan dengan `SS_HOST=0.0.0.0` dan pastikan port 8765 tidak diblokir.
