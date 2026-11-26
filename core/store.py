"""Penyimpanan metadata media, transkrip, dan daftar hasil render."""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from pathlib import Path

from . import config
from .utils import human_size, now_iso, slugify

ID_RE = re.compile(r"^[a-f0-9]{8,32}$")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def valid_id(value: str) -> bool:
    return bool(value and ID_RE.match(value))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- media
def save_media(meta: dict) -> dict:
    folder = config.MEDIA_DIR / meta["id"]
    folder.mkdir(parents=True, exist_ok=True)
    _write_json(folder / "meta.json", meta)
    return meta


def get_media(media_id: str) -> dict | None:
    if not valid_id(media_id):
        return None
    meta = _read_json(config.MEDIA_DIR / media_id / "meta.json")
    if not meta:
        return None
    if not media_abs(meta).exists():
        return None
    return meta


def list_media() -> list[dict]:
    items = []
    if not config.MEDIA_DIR.exists():
        return items
    for entry in config.MEDIA_DIR.iterdir():
        if not entry.is_dir():
            continue
        meta = _read_json(entry / "meta.json")
        if meta and media_abs(meta).exists():
            items.append(meta)
    items.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return items


def media_abs(meta: dict) -> Path:
    return (config.DATA_DIR / meta["path"]).resolve()


def thumb_abs(meta: dict) -> Path | None:
    rel = meta.get("thumb")
    if not rel:
        return None
    path = (config.DATA_DIR / rel).resolve()
    return path if path.exists() else None


def public_media(meta: dict) -> dict:
    return {
        "id": meta["id"],
        "name": meta.get("name", "media"),
        "duration": meta.get("duration", 0),
        "size": meta.get("size", 0),
        "size_label": human_size(meta.get("size", 0)),
        "has_video": bool(meta.get("has_video")),
        "has_audio": bool(meta.get("has_audio")),
        "width": meta.get("width", 0),
        "height": meta.get("height", 0),
        "fps": meta.get("fps"),
        "video_codec": meta.get("video_codec"),
        "audio_codec": meta.get("audio_codec"),
        "created_at": meta.get("created_at"),
        "file_url": f"/api/media/{meta['id']}/file",
        "thumb_url": f"/api/media/{meta['id']}/thumb" if thumb_abs(meta) else None,
    }


def delete_media(media_id: str) -> bool:
    if not valid_id(media_id):
        return False
    folder = config.MEDIA_DIR / media_id
    if not folder.exists():
        return False
    shutil.rmtree(folder, ignore_errors=True)
    return True


# ------------------------------------------------------------ transcripts
def save_transcript(transcript: dict) -> dict:
    transcript["updated_at"] = now_iso()
    _write_json(config.TRANSCRIPT_DIR / f"{transcript['id']}.json", transcript)
    return transcript


def get_transcript(transcript_id: str) -> dict | None:
    if not valid_id(transcript_id):
        return None
    return _read_json(config.TRANSCRIPT_DIR / f"{transcript_id}.json")


def list_transcripts() -> list[dict]:
    items = []
    if not config.TRANSCRIPT_DIR.exists():
        return items
    for entry in config.TRANSCRIPT_DIR.glob("*.json"):
        data = _read_json(entry)
        if not data:
            continue
        items.append(
            {
                "id": data.get("id"),
                "media_id": data.get("media_id"),
                "media_name": data.get("media_name"),
                "engine": data.get("engine"),
                "model": data.get("model"),
                "language": data.get("language"),
                "segment_count": len(data.get("segments") or []),
                "duration": data.get("duration", 0),
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
            }
        )
    items.sort(key=lambda t: t.get("updated_at") or t.get("created_at") or "", reverse=True)
    return items


def delete_transcript(transcript_id: str) -> bool:
    if not valid_id(transcript_id):
        return False
    path = config.TRANSCRIPT_DIR / f"{transcript_id}.json"
    if not path.exists():
        return False
    path.unlink(missing_ok=True)
    return True


# ---------------------------------------------------------------- outputs
OUTPUT_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".mp3", ".wav", ".m4a", ".srt", ".vtt"}


def unique_output_path(name: str, suffix: str, ext: str) -> Path:
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = now_iso().replace("-", "").replace(":", "").replace("+", "")[:15]
    base = f"{slugify(name)}-{suffix}-{stamp}"
    candidate = config.OUTPUT_DIR / f"{base}{ext}"
    counter = 2
    while candidate.exists():
        candidate = config.OUTPUT_DIR / f"{base}-{counter}{ext}"
        counter += 1
    return candidate


def list_outputs() -> list[dict]:
    items = []
    if not config.OUTPUT_DIR.exists():
        return items
    for entry in config.OUTPUT_DIR.iterdir():
        if not entry.is_file() or entry.name.startswith("."):
            continue
        if entry.suffix.lower() not in OUTPUT_EXTS:
            continue
        stat = entry.stat()
        items.append(
            {
                "name": entry.name,
                "size": stat.st_size,
                "size_label": human_size(stat.st_size),
                "created_at": stat.st_mtime,
                "kind": entry.suffix.lower().lstrip("."),
                "download_url": f"/api/outputs/{entry.name}",
            }
        )
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items
