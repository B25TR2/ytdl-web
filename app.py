#!/usr/bin/env python3
"""YT Downloader Lokal — download video YouTube beserta suaranya,
atau potong beberapa klip menit tertentu jadi video-video pendek.

Jalankan:  python app.py   ->  buka http://127.0.0.1:5000
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid

from flask import Flask, jsonify, render_template, request, send_from_directory

BASE = os.path.dirname(os.path.abspath(__file__))
DL_DIR = os.path.join(BASE, "downloads")
os.makedirs(DL_DIR, exist_ok=True)

app = Flask(__name__)
jobs = {}
YDL = [sys.executable, "-m", "yt_dlp"]
# Player client: coba 'web' dulu (kualitas penuh), kalau kena bot-check
# YouTube otomatis fallback ke 'android' (maks 360p tapi hampir selalu lolos).
YT_ARGS = ["--extractor-args", "youtube:player_client=web,android"]

# Password sederhana (HTTP Basic Auth) kalau diakses lewat tunnel publik.
# Diisi lewat env YTDL_PASSWORD. Kosong = tanpa password (pakai lokal saja).
YTDL_PASSWORD = os.environ.get("YTDL_PASSWORD", "")


def require_auth(view):
    from functools import wraps

    @wraps(view)
    def wrapper(*a, **k):
        if YTDL_PASSWORD:
            auth = request.authorization
            if not auth or auth.password != YTDL_PASSWORD:
                return ("Butuh login dulu.", 401,
                        {"WWW-Authenticate": 'Basic realm="YT Downloader"'})
        return view(*a, **k)
    return wrapper


# ---------- helpers ----------

def parse_ts(s):
    """'1:30' / '01:02:30' / '90' -> detik (int)."""
    s = str(s).strip().replace(",", ".")
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return int(float(s))
    parts = s.split(":")
    if len(parts) > 3 or not all(re.fullmatch(r"\d+(\.\d+)?", p) for p in parts):
        raise ValueError(f"Format waktu salah: '{s}' (contoh benar: 1:30 atau 90)")
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    return int(total)


def fmt_hms(sec):
    h, r = divmod(int(sec), 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_dur(sec):
    if sec is None:
        return "-"
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def file_size(path):
    n = os.path.getsize(path)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024


# ---------- routes ----------

@app.route("/")
@require_auth
def index():
    return render_template("index.html")


@app.route("/api/health")
@require_auth
def health():
    return jsonify({
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "python": sys.version.split()[0],
    })


@app.route("/api/info", methods=["POST"])
@require_auth
def info():
    url = (request.json or {}).get("url", "").strip()
    if not url:
        return jsonify({"ok": False, "error": "URL kosong."}), 400
    try:
        p = subprocess.run(
            YDL + YT_ARGS + ["--dump-single-json", "--no-playlist", "--no-warnings",
                   "--no-check-certificate", url],
            capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "YouTube lama merespons, coba lagi."}), 504
    if p.returncode != 0:
        err = (p.stderr or "").strip().splitlines()
        msg = err[-1] if err else "Gagal membaca info video."
        if "Sign in" in msg or "bot" in msg.lower():
            msg = "YouTube minta verifikasi/login untuk video ini. Coba video lain."
        return jsonify({"ok": False, "error": msg[:300]}), 400
    try:
        d = json.loads(p.stdout)
    except json.JSONDecodeError:
        return jsonify({"ok": False, "error": "Respons YouTube tidak bisa dibaca."}), 400
    return jsonify({"ok": True, "video": {
        "title": d.get("title"),
        "uploader": d.get("uploader") or d.get("channel"),
        "duration": d.get("duration"),
        "duration_str": fmt_dur(d.get("duration")),
        "thumbnail": d.get("thumbnail"),
    }})


@app.route("/api/download", methods=["POST"])
@require_auth
def download():
    body = request.json or {}
    url = body.get("url", "").strip()
    mode = body.get("mode", "full")
    quality = body.get("quality", "best")
    raw_clips = body.get("clips", []) if mode == "clips" else []

    if not url:
        return jsonify({"ok": False, "error": "URL kosong."}), 400
    if shutil.which("ffmpeg") is None:
        return jsonify({"ok": False, "error": "ffmpeg tidak ditemukan. Install dulu (lihat README)."}), 400

    clips = []
    if mode == "clips":
        if not raw_clips:
            return jsonify({"ok": False, "error": "Tambahkan minimal 1 klip dulu."}), 400
        try:
            for c in raw_clips:
                s, e = parse_ts(c.get("start", "")), parse_ts(c.get("end", ""))
                if e <= s:
                    raise ValueError(f"Klip '{c.get('start')}'–'{c.get('end')}': akhir harus lebih besar dari awal.")
                if e - s < 1:
                    raise ValueError("Durasi klip minimal 1 detik.")
                clips.append((s, e))
        except ValueError as ex:
            return jsonify({"ok": False, "error": str(ex)}), 400

    job_id = uuid.uuid4().hex[:8]
    job = {"id": job_id, "status": "running", "progress": 0,
           "note": "Menyiapkan...", "files": [], "error": None, "mode": mode,
           "total": len(clips) if clips else 1, "done": 0}
    jobs[job_id] = job
    threading.Thread(target=run_job, args=(job, url, quality, clips), daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/status/<job_id>")
@require_auth
def status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"ok": False, "error": "Job tidak ditemukan."}), 404
    return jsonify({"ok": True, "job": job})


@app.route("/api/file/<job_id>/<name>")
@require_auth
def get_file(job_id, name):
    job = jobs.get(job_id)
    if not job or "/" in name or "\\" in name:
        return jsonify({"ok": False, "error": "File tidak ditemukan."}), 404
    if name not in [f["name"] for f in job["files"]]:
        return jsonify({"ok": False, "error": "File tidak ditemukan."}), 404
    return send_from_directory(DL_DIR, name, as_attachment=True)


# ---------- worker ----------

def build_cmd(url, quality, clips):
    cmd = YDL + YT_ARGS + ["--no-playlist", "--no-warnings", "--newline",
                 "--no-check-certificate"]
    if quality == "audio":
        cmd += ["-f", "ba/b", "-x", "--audio-format", "mp3",
                "-o", os.path.join(DL_DIR, "%(title).80s.%(ext)s")]
    else:
        cap = {"1080": "1080", "720": "720", "480": "480"}.get(quality)
        fmt = f"bv*[height<={cap}]+ba/b[height<={cap}]/b" if cap else "bv*+ba/b"
        cmd += ["-f", fmt, "--merge-output-format", "mp4"]
        if clips:
            cmd += ["-o", os.path.join(DL_DIR, "%(title).50s__klip%(section_start)s-%(section_end)s.%(ext)s")]
        else:
            cmd += ["-o", os.path.join(DL_DIR, "%(title).80s.%(ext)s")]
    for s, e in clips:
        cmd += ["--download-sections", f"*{fmt_hms(s)}-{fmt_hms(e)}"]
    if clips:
        cmd += ["--force-keyframes-at-cuts"]
    cmd.append(url)
    return cmd


def run_job(job, url, quality, clips):
    before = set(os.listdir(DL_DIR))
    cmd = build_cmd(url, quality, clips)
    job["note"] = "Menghubungi YouTube..."
    log_path = os.path.join(BASE, "downloads", f".job-{job['id']}.log")
    try:
        logf = open(log_path, "w")
        p = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT,
                             text=True, bufsize=1)
    except Exception as ex:  # pragma: no cover
        job.update(status="error", error=str(ex))
        return

    cur_file, last_err = "", ""
    import time
    pos = 0
    while p.poll() is None:
        time.sleep(1)
        logf.flush()
        with open(log_path) as rf:
            rf.seek(pos)
            chunk = rf.read()
            pos = rf.tell()
        for line in chunk.splitlines():
            line = line.strip()
            if not line:
                continue
            last_err = line if len(line) < 300 else last_err
            m = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
            if m:
                job["progress"] = float(m.group(1))
            m2 = re.search(r"\[download\] Destination: (.+)", line)
            if m2:
                cur_file = os.path.basename(m2.group(1))
                job["note"] = f"Download: {cur_file[:60]}"
            if "[Merger]" in line or "[ExtractAudio]" in line:
                job["note"] = "Menggabungkan video + audio..."
            if "has already been downloaded" in line:
                job["done"] += 1
            if re.search(r"\[download\].*100%", line):
                job["done"] = min(job["done"] + 1, job["total"] or 1)
            if clips and job["total"] > 1:
                job["note"] = f"Klip {min(job['done'] + 1, job['total'])} dari {job['total']} — {job['progress']:.0f}%"
    logf.close()
    # baca sisa output + ambil baris error terakhir buat pesan
    with open(log_path, errors="replace") as rf:
        tail = rf.read().splitlines()[-40:]
    for line in tail:
        s = line.strip()
        if s and ("ERROR" in s or "error" in s.lower()):
            last_err = s[:300]

    if p.returncode != 0:
        msg = last_err
        if "Sign in" in msg or "bot" in msg.lower():
            msg = "YouTube minta verifikasi/login untuk video ini. Coba video lain."
        job.update(status="error", error=(msg or "Download gagal.")[:300])
        return

    new_files = sorted(set(os.listdir(DL_DIR)) - before)
    new_files = [f for f in new_files if not f.startswith(".job-")]
    job["files"] = [{"name": f, "size": file_size(os.path.join(DL_DIR, f))}
                    for f in new_files if os.path.isfile(os.path.join(DL_DIR, f))]
    if not job["files"]:
        job.update(status="error", error="Selesai tapi tidak ada file baru. Coba lagi.")
        return
    job.update(status="done", progress=100, done=job["total"],
               note=f"Selesai — {len(job['files'])} file.")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("BIND_HOST", "127.0.0.1")
    print(f"YT Downloader jalan di http://{host}:{port}")
    print(f"Folder hasil: {DL_DIR}")
    if YTDL_PASSWORD:
        print("Login pakai password di file password.txt")
    app.run(host=host, port=port)
