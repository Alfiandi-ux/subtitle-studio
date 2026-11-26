"""Transkripsi offline (whisper.cpp) dan online (Groq/OpenAI)."""
from __future__ import annotations

import json
import mimetypes
import re
import subprocess
import uuid
from pathlib import Path
from urllib import error, request

from . import config, store
from .ffmpeg import extract_audio
from .subtitles import normalize_segments
from .utils import now_iso

PROGRESS_RE = re.compile(r"progress\s*=\s*(\d+)%", re.IGNORECASE)
SILENCE_TEXTS = {"[blank_audio]", "[silence]", "(silence)", "[musik]", "[music]"}

ONLINE_PROVIDERS = {
    "groq": {
        "url": "https://api.groq.com/openai/v1/audio/transcriptions",
        "key_name": "groq_key",
        "model_key": "groq_model",
        "label": "Groq",
    },
    "openai": {
        "url": "https://api.openai.com/v1/audio/transcriptions",
        "key_name": "openai_key",
        "model_key": "openai_model",
        "label": "OpenAI",
    },
}


def _make_transcript(
    media: dict,
    *,
    engine: str,
    model: str,
    language: str,
    segments: list[dict],
    duration: float,
) -> dict:
    transcript = {
        "id": store.new_id(),
        "media_id": media["id"],
        "media_name": media.get("name"),
        "engine": engine,
        "model": model,
        "language": language or "auto",
        "segments": segments,
        "duration": round(float(duration or 0), 3),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    store.save_transcript(transcript)
    return transcript


# --------------------------------------------------------------- offline
def _parse_whisper_json(path: Path) -> tuple[list[dict], str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("transcription") or []
    segments = []
    for item in raw:
        text = str(item.get("text") or "").strip()
        if not text or text.lower() in SILENCE_TEXTS:
            continue
        offsets = item.get("offsets") or {}
        try:
            start = float(offsets.get("from")) / 1000.0
            end = float(offsets.get("to")) / 1000.0
        except (TypeError, ValueError):
            continue
        segments.append({"start": start, "end": end, "text": text})
    language = str((data.get("result") or {}).get("language") or "")
    return segments, language


def offline(job, media: dict, *, language: str, model_name: str, settings: dict) -> dict:
    src = store.media_abs(media)
    model = config.model_path(model_name)
    if not model.exists():
        raise RuntimeError(
            f"Model {model_name} tidak ditemukan di {config.MODELS_DIR}. "
            "Unduh model dari halaman Pengaturan."
        )
    if not config.WHISPER_BIN.exists():
        raise RuntimeError(
            f"whisper-cli tidak ditemukan di {config.WHISPER_BIN}. "
            "Jalankan build whisper.cpp terlebih dahulu."
        )

    wav = job.dir / "audio.wav"
    job.stage = "Mengekstrak audio"
    extract_audio(
        job, src, wav, fmt="wav", duration=media.get("duration"), p0=0, p1=12
    )

    prefix = job.dir / "whisper"
    threads = max(1, min(16, int(settings.get("threads") or 4)))
    cmd = [
        str(config.WHISPER_BIN),
        "-m",
        str(model),
        "-f",
        str(wav),
        "-l",
        language or "auto",
        "-t",
        str(threads),
        "-oj",
        "-of",
        str(prefix),
        "-pp",
        "-np",
    ]

    job.stage = "Mentranskripsi audio (offline)"
    job.progress = None
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    tail: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip()
        if line:
            tail.append(line)
            del tail[:-25]
        match = PROGRESS_RE.search(line)
        if match:
            percent = int(match.group(1))
            job.progress = 12 + (percent / 100.0) * 83
            job.message = f"{percent}%"
        if job.cancel_event.is_set():
            process.kill()
            break
    process.wait()

    if job.cancel_event.is_set():
        raise RuntimeError("Job dibatalkan")
    if process.returncode != 0:
        detail = "\n".join(tail[-8:]) or f"kode keluar {process.returncode}"
        raise RuntimeError(f"Whisper gagal: {detail}")

    json_path = prefix.with_suffix(".json")
    if not json_path.exists():
        raise RuntimeError("Whisper tidak menghasilkan file transkrip JSON.")

    job.stage = "Menyusun subtitle"
    job.progress = 97
    segments, detected_language = _parse_whisper_json(json_path)
    segments = normalize_segments(segments)
    if not segments:
        raise RuntimeError("Tidak ada ucapan yang terdeteksi pada audio ini.")

    transcript = _make_transcript(
        media,
        engine="offline",
        model=model_name,
        language=detected_language or language,
        segments=segments,
        duration=media.get("duration") or 0,
    )
    return {"transcript_id": transcript["id"], "segments": len(segments)}


# ---------------------------------------------------------------- online
def _multipart(fields: dict, file_path: Path) -> tuple[bytes, str]:
    boundary = "----SubtitleStudio" + uuid.uuid4().hex
    body = bytearray()
    for key, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        (
            f'Content-Disposition: form-data; name="file"; '
            f'filename="{file_path.name}"\r\n'
        ).encode()
    )
    body.extend(f"Content-Type: {mime}\r\n\r\n".encode())
    body.extend(file_path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def online(
    job, media: dict, *, engine: str, language: str, settings: dict
) -> dict:
    provider = ONLINE_PROVIDERS.get(engine)
    if not provider:
        raise ValueError(f"Provider online tidak dikenal: {engine}")

    api_key = str(settings.get(provider["key_name"]) or "").strip()
    if not api_key:
        raise RuntimeError(
            f"API key {provider['label']} belum diisi. Buka Pengaturan untuk menambahkannya."
        )
    model = str(settings.get(provider["model_key"]) or "")

    src = store.media_abs(media)
    audio = job.dir / "audio.mp3"
    job.stage = "Mengekstrak audio"
    extract_audio(
        job, src, audio, fmt="mp3", duration=media.get("duration"), p0=0, p1=20
    )

    fields = {"model": model, "response_format": "verbose_json", "temperature": "0"}
    if language and language != "auto":
        fields["language"] = language

    body, content_type = _multipart(fields, audio)
    req = request.Request(
        provider["url"],
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
            "User-Agent": "SubtitleStudio/1.0",
        },
    )

    job.stage = f"Mengunggah ke {provider['label']}"
    job.progress = None
    try:
        with request.urlopen(req, timeout=900) as response:
            payload = response.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        try:
            parsed = json.loads(detail)
            detail = (parsed.get("error") or {}).get("message") or detail
        except ValueError:
            pass
        raise RuntimeError(f"{provider['label']} menolak permintaan: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Gagal menghubungi {provider['label']}: {exc.reason}") from exc

    job.stage = "Menyusun subtitle"
    job.progress = 90
    try:
        data = json.loads(payload.decode("utf-8"))
    except ValueError as exc:
        raise RuntimeError("Respons API bukan JSON yang valid.") from exc

    raw_segments = data.get("segments") or []
    segments = []
    for item in raw_segments:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        try:
            start = float(item.get("start") or 0)
            end = float(item.get("end") or start + 2)
        except (TypeError, ValueError):
            continue
        segments.append({"start": start, "end": end, "text": text})

    if not segments:
        text = str(data.get("text") or "").strip()
        if not text:
            raise RuntimeError("API tidak mengembalikan teks transkrip.")
        duration = float(data.get("duration") or media.get("duration") or 0)
        segments = [{"start": 0, "end": max(1.0, duration), "text": text}]

    segments = normalize_segments(segments)
    transcript = _make_transcript(
        media,
        engine=engine,
        model=model,
        language=str(data.get("language") or language or "auto"),
        segments=segments,
        duration=float(data.get("duration") or media.get("duration") or 0),
    )
    return {"transcript_id": transcript["id"], "segments": len(segments)}
