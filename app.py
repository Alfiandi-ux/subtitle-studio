"""Subtitle Studio — server web lokal untuk transkripsi & edit video."""
from __future__ import annotations

import mimetypes
import os
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from flask import Flask, Response, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from core import config, models, store, transcribe
from core.ffmpeg import (
    burn_subtitles,
    concat,
    export_audio,
    ffmpeg_available,
    make_thumbnail,
    transform,
    trim,
)
from core.jobs import JobManager
from core.subtitles import normalize_segments, to_ass, to_srt, to_txt, to_vtt
from core.utils import human_size, now_iso, parse_time, probe, slugify

config.ensure_dirs()

app = Flask(
    __name__,
    static_folder=str(config.STATIC_DIR),
    static_url_path="/static",
)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024**3
app.config["JSON_SORT_KEYS"] = False

manager = JobManager(workers=1)

ALLOWED_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".amr",
    ".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".ts", ".mpg", ".mpeg",
    ".3gp",
}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".ts", ".mpg", ".mpeg", ".3gp"}


def body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def output_result(path: Path) -> dict:
    return {
        "output": path.name,
        "download_url": f"/api/outputs/{quote(path.name)}",
        "size": path.stat().st_size,
        "size_label": human_size(path.stat().st_size),
    }


@app.errorhandler(Exception)
def handle_error(exc):
    if isinstance(exc, RequestEntityTooLarge):
        return jsonify(error="File terlalu besar (maksimal 4 GB)."), 413
    if isinstance(exc, FileNotFoundError):
        return jsonify(error=str(exc) or "Data tidak ditemukan."), 404
    if isinstance(exc, ValueError):
        return jsonify(error=str(exc) or "Permintaan tidak valid."), 400
    if isinstance(exc, HTTPException):
        if request.path.startswith("/api/"):
            return jsonify(error=exc.description), exc.code
        return exc
    app.logger.exception("Terjadi kesalahan")
    return jsonify(error=str(exc) or exc.__class__.__name__), 500


@app.after_request
def no_cache_api(response):
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# ------------------------------------------------------------------ pages
@app.get("/")
def index():
    return send_from_directory(config.STATIC_DIR, "index.html")


@app.get("/favicon.ico")
def favicon():
    return Response(status=204)


# ----------------------------------------------------------------- health
@app.get("/api/health")
def health():
    settings = config.load_settings()
    selected_model = config.model_path(settings["whisper_model"])
    available = models.list_models()
    return jsonify(
        {
            "ok": ffmpeg_available() and config.WHISPER_BIN.exists(),
            "ffmpeg": ffmpeg_available(),
            "whisper": config.WHISPER_BIN.exists(),
            "whisper_bin": str(config.WHISPER_BIN),
            "models_dir": str(config.MODELS_DIR),
            "selected_model": settings["whisper_model"],
            "selected_model_ready": selected_model.exists(),
            "models": available,
            "data_dir": str(config.DATA_DIR),
        }
    )


# --------------------------------------------------------------- settings
@app.get("/api/settings")
def get_settings():
    return jsonify(config.public_settings())


@app.post("/api/settings")
def update_settings():
    data = body()
    updates = {}
    if "engine" in data:
        if data["engine"] not in ("offline", "groq", "openai"):
            raise ValueError("Mesin transkripsi tidak valid.")
        updates["engine"] = data["engine"]
    if "language" in data:
        updates["language"] = str(data["language"])[:12] or "auto"
    if "whisper_model" in data:
        name = Path(str(data["whisper_model"])).name
        if not config.model_path(name).exists():
            raise ValueError("Model Whisper belum tersedia.")
        updates["whisper_model"] = name
    if "threads" in data:
        updates["threads"] = max(1, min(16, int(data["threads"])))
    for key in ("groq_key", "openai_key"):
        if key in data:
            value = str(data[key]).strip()
            if value and not value.startswith("•"):
                updates[key] = value
    if "groq_model" in data:
        updates["groq_model"] = str(data["groq_model"]).strip() or "whisper-large-v3-turbo"
    if "openai_model" in data:
        updates["openai_model"] = str(data["openai_model"]).strip() or "whisper-1"

    config.save_settings(updates)
    return jsonify(config.public_settings())


# ----------------------------------------------------------------- models
@app.get("/api/models")
def get_models():
    installed = {m["name"] for m in models.list_models()}
    downloadable = [
        {
            "name": name,
            "label": label,
            "installed": name in installed,
        }
        for name, label in config.DOWNLOADABLE_MODELS.items()
    ]
    return jsonify({"models": models.list_models(), "downloadable": downloadable})


@app.post("/api/models/download")
def download_model():
    name = Path(str(body().get("name") or "")).name
    if name not in config.DOWNLOADABLE_MODELS:
        raise ValueError("Model tidak tersedia untuk diunduh.")
    job = manager.submit(
        "model",
        f"Unduh model {name}",
        lambda current: models.download(current, name),
    )
    return jsonify(job=job.to_dict())


# ------------------------------------------------------------------ media
@app.get("/api/media")
def get_media_list():
    return jsonify(media=[store.public_media(meta) for meta in store.list_media()])


@app.post("/api/upload")
def upload():
    upload_file = request.files.get("file")
    if not upload_file or not upload_file.filename:
        raise ValueError("Tidak ada file yang diunggah.")

    original = Path(upload_file.filename).name
    ext = Path(original).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            "Format file tidak didukung. Gunakan audio/video seperti MP3, WAV, "
            "M4A, MP4, MKV, MOV, atau WEBM."
        )

    media_id = store.new_id()
    folder = config.MEDIA_DIR / media_id
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"source{ext}"
    upload_file.save(dest)

    try:
        info = probe(dest)
        if not info["has_audio"] and not info["has_video"]:
            raise ValueError("File tidak memiliki stream audio atau video.")
    except Exception:
        dest.unlink(missing_ok=True)
        folder.rmdir()
        raise

    thumb_rel = None
    if info["has_video"]:
        thumb_path = folder / "thumb.jpg"
        if make_thumbnail(dest, thumb_path):
            thumb_rel = str(thumb_path.relative_to(config.DATA_DIR))

    meta = {
        "id": media_id,
        "name": original,
        "path": str(dest.relative_to(config.DATA_DIR)),
        "thumb": thumb_rel,
        "created_at": now_iso(),
        **info,
    }
    store.save_media(meta)
    return jsonify(media=store.public_media(meta))


@app.get("/api/media/<media_id>/file")
def media_file(media_id):
    meta = store.get_media(media_id)
    if not meta:
        raise FileNotFoundError("Media tidak ditemukan.")
    path = store.media_abs(meta)
    mime = mimetypes.guess_type(meta.get("name", ""))[0] or "application/octet-stream"
    return send_file(
        path,
        mimetype=mime,
        as_attachment=False,
        download_name=meta.get("name"),
        conditional=True,
    )


@app.get("/api/media/<media_id>/thumb")
def media_thumb(media_id):
    meta = store.get_media(media_id)
    thumb = store.thumb_abs(meta) if meta else None
    if not thumb:
        raise FileNotFoundError("Thumbnail tidak tersedia.")
    return send_file(thumb, mimetype="image/jpeg", conditional=True)


@app.delete("/api/media/<media_id>")
def remove_media(media_id):
    if not store.delete_media(media_id):
        raise FileNotFoundError("Media tidak ditemukan.")
    return jsonify(ok=True)


# ------------------------------------------------------------- transcripts
@app.get("/api/transcripts")
def transcripts():
    return jsonify(transcripts=store.list_transcripts())


@app.get("/api/transcripts/<transcript_id>")
def transcript_detail(transcript_id):
    transcript = store.get_transcript(transcript_id)
    if not transcript:
        raise FileNotFoundError("Transkrip tidak ditemukan.")
    meta = store.get_media(transcript.get("media_id") or "")
    transcript["media"] = store.public_media(meta) if meta else None
    return jsonify(transcript=transcript)


@app.put("/api/transcripts/<transcript_id>")
def transcript_update(transcript_id):
    transcript = store.get_transcript(transcript_id)
    if not transcript:
        raise FileNotFoundError("Transkrip tidak ditemukan.")
    data = body()
    segments = normalize_segments(data.get("segments") or [])
    if not segments:
        raise ValueError("Transkrip harus memiliki minimal satu segmen berisi teks.")
    transcript["segments"] = segments
    if "language" in data:
        transcript["language"] = str(data["language"])[:12] or transcript.get("language")
    store.save_transcript(transcript)
    meta = store.get_media(transcript.get("media_id") or "")
    transcript["media"] = store.public_media(meta) if meta else None
    return jsonify(transcript=transcript)


@app.delete("/api/transcripts/<transcript_id>")
def transcript_delete(transcript_id):
    if not store.delete_transcript(transcript_id):
        raise FileNotFoundError("Transkrip tidak ditemukan.")
    return jsonify(ok=True)


@app.get("/api/transcripts/<transcript_id>/export")
def transcript_export(transcript_id):
    transcript = store.get_transcript(transcript_id)
    if not transcript:
        raise FileNotFoundError("Transkrip tidak ditemukan.")
    fmt = (request.args.get("format") or "srt").lower()
    segments = normalize_segments(transcript.get("segments") or [])
    base = slugify(transcript.get("media_name") or "transkrip", "transkrip")

    if fmt == "srt":
        payload, ext, mime = to_srt(segments), "srt", "application/x-subrip"
    elif fmt == "vtt":
        payload, ext, mime = to_vtt(segments), "vtt", "text/vtt"
    elif fmt == "txt":
        payload, ext, mime = to_txt(segments), "txt", "text/plain; charset=utf-8"
    elif fmt == "json":
        return jsonify(transcript=transcript)
    else:
        raise ValueError("Format ekspor tidak dikenal.")

    data = payload.encode("utf-8")
    return send_file(
        BytesIO(data),
        mimetype=mime,
        as_attachment=True,
        download_name=f"{base}.{ext}",
    )


# ------------------------------------------------------------ transcription
@app.post("/api/transcribe")
def transcribe_media():
    data = body()
    media = store.get_media(str(data.get("media_id") or ""))
    if not media:
        raise FileNotFoundError("Pilih media yang valid terlebih dahulu.")
    if not media.get("has_audio"):
        raise ValueError("Media ini tidak memiliki audio.")

    engine = str(data.get("engine") or "offline")
    language = str(data.get("language") or "auto")
    settings = config.load_settings()

    if engine == "offline":
        model_name = Path(str(data.get("model") or settings["whisper_model"])).name
        if not config.model_path(model_name).exists():
            raise ValueError("Model Whisper belum tersedia. Unduh di halaman Pengaturan.")
        if not config.WHISPER_BIN.exists():
            raise ValueError("whisper-cli belum dibangun di perangkat ini.")
        label = f"Transkripsi offline · {media['name']}"
        fn = lambda job: transcribe.offline(
            job, media, language=language, model_name=model_name, settings=settings
        )
    elif engine in ("groq", "openai"):
        provider = transcribe.ONLINE_PROVIDERS[engine]
        if not settings.get(provider["key_name"]):
            raise ValueError(
                f"API key {provider['label']} belum diisi. Buka Pengaturan dulu."
            )
        label = f"Transkripsi {provider['label']} · {media['name']}"
        fn = lambda job: transcribe.online(
            job, media, engine=engine, language=language, settings=settings
        )
    else:
        raise ValueError("Mesin transkripsi tidak valid.")

    job = manager.submit("transcribe", label, fn)
    return jsonify(job=job.to_dict())


# ------------------------------------------------------------------- jobs
@app.get("/api/jobs")
def jobs_list():
    return jsonify(jobs=manager.list())


@app.get("/api/jobs/<job_id>")
def job_detail(job_id):
    job = manager.get(job_id)
    if not job:
        raise FileNotFoundError("Job tidak ditemukan.")
    return jsonify(job=job.to_dict())


@app.post("/api/jobs/<job_id>/cancel")
def job_cancel(job_id):
    if not manager.cancel(job_id):
        raise ValueError("Job tidak bisa dibatalkan.")
    return jsonify(ok=True)


# ------------------------------------------------------------- video tools
@app.post("/api/video/trim")
def video_trim():
    data = body()
    media = store.get_media(str(data.get("media_id") or ""))
    if not media:
        raise FileNotFoundError("Media tidak ditemukan.")
    duration = float(media.get("duration") or 0)
    start = parse_time(data.get("start", 0))
    end = parse_time(data.get("end", duration))
    if end <= start:
        raise ValueError("Waktu akhir harus lebih besar dari waktu mulai.")
    if duration and start >= duration:
        raise ValueError("Waktu mulai melewati durasi media.")
    if duration:
        end = min(end, duration)
    if end - start < 0.1:
        raise ValueError("Potongan terlalu pendek (minimal 0,1 detik).")

    mode = "copy" if data.get("mode") == "copy" else "reencode"
    if mode == "copy":
        ext = Path(media["name"]).suffix.lower()
        if ext not in VIDEO_EXTS and ext not in ALLOWED_EXTENSIONS:
            ext = ".mp4"
    else:
        ext = ".mp4" if media.get("has_video") else ".mp3"

    out = store.unique_output_path(media["name"], "potong", ext)
    job = manager.submit(
        "trim",
        f"Potong · {media['name']}",
        lambda current: (
            trim(
                current,
                store.media_abs(media),
                out,
                start=start,
                end=end,
                has_video=bool(media.get("has_video")),
                mode=mode,
                duration=duration,
            ),
            output_result(out),
        )[1],
    )
    return jsonify(job=job.to_dict())


@app.post("/api/video/burn")
def video_burn():
    data = body()
    media = store.get_media(str(data.get("media_id") or ""))
    if not media:
        raise FileNotFoundError("Media tidak ditemukan.")
    if not media.get("has_video"):
        raise ValueError("Burn subtitle hanya bisa untuk file video.")
    transcript = store.get_transcript(str(data.get("transcript_id") or ""))
    if not transcript:
        raise FileNotFoundError("Transkrip tidak ditemukan.")
    segments = normalize_segments(transcript.get("segments") or [])
    if not segments:
        raise ValueError("Transkrip tidak memiliki segmen teks.")

    style = data.get("style") or {}
    try:
        font_size = int(style.get("font_size") or 0)
        outline = int(style.get("outline") or 0)
        margin_v = int(style.get("margin_v") or 0)
    except (TypeError, ValueError):
        raise ValueError("Ukuran font/outline/margin tidak valid.")

    ass_text = to_ass(
        segments,
        int(media.get("width") or 1280),
        int(media.get("height") or 720),
        font_size=font_size,
        color=str(style.get("color") or "white"),
        bold=bool(style.get("bold", True)),
        outline=outline or None,
        position=str(style.get("position") or "bottom"),
        margin_v=margin_v,
    )

    out = store.unique_output_path(media["name"], "subtitle", ".mp4")

    def work(current):
        ass_path = current.dir / "subs.ass"
        ass_path.write_text(ass_text, encoding="utf-8")
        burn_subtitles(
            current,
            store.media_abs(media),
            "subs.ass",
            out,
            duration=media.get("duration"),
            workdir=current.dir,
        )
        return output_result(out)

    job = manager.submit("burn", f"Burn subtitle · {media['name']}", work)
    return jsonify(job=job.to_dict())


@app.post("/api/video/concat")
def video_concat():
    data = body()
    ids = data.get("media_ids") or []
    if not isinstance(ids, list) or len(ids) < 2:
        raise ValueError("Pilih minimal dua video untuk digabung.")
    if len(ids) > 20:
        raise ValueError("Maksimal 20 klip sekali gabung.")

    metas = []
    for media_id in ids:
        meta = store.get_media(str(media_id))
        if not meta:
            raise FileNotFoundError("Salah satu media tidak ditemukan.")
        if not meta.get("has_video"):
            raise ValueError(f"{meta['name']} bukan file video.")
        metas.append(meta)

    try:
        width = int(data.get("width") or metas[0].get("width") or 1280)
        height = int(data.get("height") or metas[0].get("height") or 720)
        fps = int(data.get("fps") or round(float(metas[0].get("fps") or 30)))
    except (TypeError, ValueError):
        raise ValueError("Resolusi/FPS tidak valid.")
    if width < 2 or height < 2:
        width, height = 1280, 720

    out = store.unique_output_path(metas[0]["name"], "gabung", ".mp4")
    clips = [
        {
            "path": str(store.media_abs(meta)),
            "duration": meta.get("duration") or 0,
            "has_audio": bool(meta.get("has_audio")),
        }
        for meta in metas
    ]

    job = manager.submit(
        "concat",
        f"Gabung {len(clips)} video",
        lambda current: (
            concat(current, clips, out, width=width, height=height, fps=fps),
            output_result(out),
        )[1],
    )
    return jsonify(job=job.to_dict())


@app.post("/api/video/transform")
def video_transform():
    data = body()
    media = store.get_media(str(data.get("media_id") or ""))
    if not media:
        raise FileNotFoundError("Media tidak ditemukan.")
    if not media.get("has_video"):
        raise ValueError("Kompres/resize hanya untuk file video.")
    try:
        width = max(0, min(7680, int(data.get("width") or 0)))
        crf = max(16, min(35, int(data.get("crf") or 23)))
        fps = int(data.get("fps") or 0)
    except (TypeError, ValueError):
        raise ValueError("Nilai kompres tidak valid.")

    preset = str(data.get("preset") or "veryfast")
    out = store.unique_output_path(media["name"], "kompres", ".mp4")
    job = manager.submit(
        "transform",
        f"Kompres · {media['name']}",
        lambda current: (
            transform(
                current,
                store.media_abs(media),
                out,
                width=width,
                crf=crf,
                preset=preset,
                fps=fps or None,
                has_video=True,
                duration=media.get("duration"),
            ),
            output_result(out),
        )[1],
    )
    return jsonify(job=job.to_dict())


@app.post("/api/video/extract-audio")
def video_extract_audio():
    data = body()
    media = store.get_media(str(data.get("media_id") or ""))
    if not media:
        raise FileNotFoundError("Media tidak ditemukan.")
    if not media.get("has_audio"):
        raise ValueError("Media ini tidak memiliki audio.")
    fmt = str(data.get("format") or "mp3").lower()
    if fmt not in ("mp3", "wav", "m4a"):
        raise ValueError("Format audio tidak valid.")

    out = store.unique_output_path(media["name"], "audio", f".{fmt}")
    job = manager.submit(
        "audio",
        f"Ekstrak audio · {media['name']}",
        lambda current: (
            export_audio(
                current,
                store.media_abs(media),
                out,
                fmt=fmt,
                duration=media.get("duration"),
            ),
            output_result(out),
        )[1],
    )
    return jsonify(job=job.to_dict())


# ---------------------------------------------------------------- outputs
@app.get("/api/outputs")
def outputs_list():
    return jsonify(outputs=store.list_outputs())


@app.get("/api/outputs/<path:filename>")
def output_download(filename):
    name = Path(filename).name
    path = config.OUTPUT_DIR / name
    if not path.exists() or not path.is_file():
        raise FileNotFoundError("Hasil tidak ditemukan.")
    return send_file(path, as_attachment=True, download_name=name, conditional=True)


@app.delete("/api/outputs/<path:filename>")
def output_delete(filename):
    name = Path(filename).name
    path = config.OUTPUT_DIR / name
    if not path.exists():
        raise FileNotFoundError("Hasil tidak ditemukan.")
    path.unlink(missing_ok=True)
    return jsonify(ok=True)


if __name__ == "__main__":
    host = os.environ.get("SS_HOST", "127.0.0.1")
    port = int(os.environ.get("SS_PORT", "8765"))
    print()
    print("  Subtitle Studio")
    print(f"  Buka di browser: http://{host}:{port}")
    print(f"  Data tersimpan di: {config.DATA_DIR}")
    print()
    app.run(host=host, port=port, threaded=True, debug=False)
