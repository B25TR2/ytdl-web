# 📥 YT Downloader Web

Website downloader YouTube: download video utuh beserta suara (MP4), potong
beberapa klip menit tertentu jadi video-video pendek, atau ambil audio saja (MP3).

## Deploy gratis ke Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/B25TR2/ytdl-web)

1. Klik tombol di atas (atau buka linknya).
2. Login / bikin akun Render gratis (bisa pakai akun GitHub).
3. Klik **Deploy** — tunggu build selesai ±5 menit.
4. Buka URL-nya, mis. `https://ytdl-web.onrender.com`.

Password website dibuat otomatis (lihat di dashboard Render → service ini →
**Environment** → `YTDL_PASSWORD`). Browser cuma minta sekali.

## Catatan

- Paket gratis Render tidur setelah 15 menit tidak dipakai — bukaan pertama
  agak lama (±1 menit), berikutnya normal.
- File hasil download tersimpan sementara di server dan hilang saat service
  restart — langsung download hasilnya setelah selesai.
- YouTube membatasi IP server: kualitas video mentok 360p dari hosting gratis.
  Butuh 1080p? Jalankan versi portable di laptop sendiri.
- Pakai buat pribadi — menghormati hak cipta kreator.
