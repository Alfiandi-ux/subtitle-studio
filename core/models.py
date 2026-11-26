"""Daftar dan unduhan model whisper.cpp."""
from __future__ import annotations

import os
from urllib import error, request

from . import config
from .utils import human_size

HF_BASE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"


def list_models() -> list[dict]:
    models = []
    if not config.MODELS_DIR.exists():
        return models
    for entry in sorted(config.MODELS_DIR.glob("ggml-*.bin")):
        try:
            size = entry.stat().st_size
        except OSError:
            continue
        if size < 1_000_000:
            continue
        models.append(
            {
                "name": entry.name,
                "size": size,
                "size_label": human_size(size),
                "downloadable": entry.name in config.DOWNLOADABLE_MODELS,
            }
        )
    return models


def download(job, name: str) -> dict:
    if name not in config.DOWNLOADABLE_MODELS:
        raise ValueError("Model tidak tersedia untuk diunduh.")
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.MODELS_DIR / name
    if dest.exists() and dest.stat().st_size > 1_000_000:
        return {"model": name, "size": dest.stat().st_size, "skipped": True}

    part = dest.with_suffix(dest.suffix + ".part")
    url = f"{HF_BASE}/{name}"
    req = request.Request(url, headers={"User-Agent": "SubtitleStudio/1.0"})
    job.stage = f"Mengunduh {name}"
    job.progress = 0

    try:
        with request.urlopen(req, timeout=120) as response, open(part, "wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if job.cancel_event.is_set():
                    raise RuntimeError("Unduhan dibatalkan")
                chunk = response.read(1024 * 512)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if total:
                    job.progress = min(99.5, done / total * 100)
                    job.message = f"{human_size(done)} / {human_size(total)}"
                else:
                    job.message = human_size(done)
    except error.HTTPError as exc:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"Unduhan gagal (HTTP {exc.code}).") from exc
    except error.URLError as exc:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"Gagal mengunduh model: {exc.reason}") from exc

    os.replace(part, dest)
    return {"model": name, "size": dest.stat().st_size}
