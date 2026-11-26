"""Utilitas umum: waktu, ffprobe, nama file, dan format subtitle."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(value: str, fallback: str = "media") -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE).strip().lower()
    value = re.sub(r"[\s_-]+", "-", value).strip("-")
    return (value or fallback)[:60]


def parse_time(value) -> float:
    """Terima 12.5, '12,5', '01:23.5', atau '00:01:23,500'."""
    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        text = str(value or "").strip().replace(",", ".")
        if not text:
            raise ValueError("Waktu kosong")
        if ":" in text:
            parts = [float(part) for part in text.split(":")]
            seconds = 0.0
            for part in parts:
                seconds = seconds * 60 + part
        else:
            seconds = float(text)
    if seconds < 0:
        seconds = 0.0
    return seconds


def fmt_srt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def fmt_vtt_time(seconds: float) -> str:
    return fmt_srt_time(seconds).replace(",", ".")


def fmt_clock(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def fmt_duration(seconds) -> str:
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "—"
    if seconds <= 0:
        return "—"
    return fmt_clock(seconds)


def human_size(size) -> str:
    try:
        size = float(size)
    except (TypeError, ValueError):
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return "—"


def parse_fps(value) -> float | None:
    try:
        if not value or value == "0/0":
            return None
        if "/" in str(value):
            num, den = str(value).split("/", 1)
            den = float(den)
            return round(float(num) / den, 3) if den else None
        return round(float(value), 3)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def probe(path: Path) -> dict:
    """Ambil metadata audio/video memakai ffprobe."""
    cmd = [
        FFPROBE,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(
            "File tidak bisa dibaca sebagai audio/video. "
            + (result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "")
        )
    data = json.loads(result.stdout or "{}")
    streams = data.get("streams") or []
    fmt = data.get("format") or {}

    video = next((s for s in streams if s.get("codec_type") == "video"
                  and s.get("disposition", {}).get("attached_pic", 0) != 1), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    width = int(video.get("width") or 0) if video else 0
    height = int(video.get("height") or 0) if video else 0
    rotation = 0
    if video:
        for side in video.get("side_data_list") or []:
            if "rotation" in side:
                try:
                    rotation = int(float(side["rotation"]))
                except (TypeError, ValueError):
                    rotation = 0
        try:
            rotation = int(float((video.get("tags") or {}).get("rotate", rotation)))
        except (TypeError, ValueError):
            pass
    if abs(rotation) % 180 == 90:
        width, height = height, width

    duration = 0.0
    for source in (fmt.get("duration"), video.get("duration") if video else None,
                   audio.get("duration") if audio else None):
        try:
            duration = float(source)
            if duration > 0:
                break
        except (TypeError, ValueError):
            continue

    return {
        "duration": round(duration, 3),
        "size": int(fmt.get("size") or path.stat().st_size),
        "bit_rate": int(fmt.get("bit_rate") or 0),
        "format_name": fmt.get("format_name") or "",
        "has_video": video is not None,
        "has_audio": audio is not None,
        "width": width,
        "height": height,
        "fps": parse_fps(video.get("avg_frame_rate")) if video else None,
        "video_codec": video.get("codec_name") if video else None,
        "audio_codec": audio.get("codec_name") if audio else None,
        "sample_rate": int(audio.get("sample_rate") or 0) if audio else 0,
        "channels": int(audio.get("channels") or 0) if audio else 0,
        "rotation": rotation,
    }
