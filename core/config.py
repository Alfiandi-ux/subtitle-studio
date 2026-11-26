"""Konfigurasi dan penyimpanan setelan Subtitle Studio."""
from __future__ import annotations

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.environ.get("SS_DATA_DIR", BASE_DIR / "data"))
MEDIA_DIR = DATA_DIR / "media"
TRANSCRIPT_DIR = DATA_DIR / "transcripts"
OUTPUT_DIR = DATA_DIR / "outputs"
TMP_DIR = DATA_DIR / "tmp"
STATIC_DIR = BASE_DIR / "static"
FONT_DIR = BASE_DIR / "assets" / "fonts"
SETTINGS_FILE = DATA_DIR / "settings.json"

WHISPER_DIR = Path(os.environ.get("WHISPER_DIR", Path.home() / "whisper.cpp"))
WHISPER_BIN = Path(
    os.environ.get("WHISPER_BIN", WHISPER_DIR / "build" / "bin" / "whisper-cli")
)
MODELS_DIR = Path(os.environ.get("WHISPER_MODELS", WHISPER_DIR / "models"))

# Model yang boleh diunduh dari Hugging Face.
DOWNLOADABLE_MODELS = {
    "ggml-tiny.bin": "Tiny · 75 MB · tercepat, akurasi rendah",
    "ggml-base.bin": "Base · 142 MB · seimbang untuk HP",
    "ggml-small.bin": "Small · 466 MB · akurasi lebih baik",
    "ggml-medium.bin": "Medium · 1,5 GB · akurasi tinggi, lambat",
    "ggml-large-v3-turbo.bin": "Large v3 Turbo · 1,6 GB · terbaik, butuh RAM besar",
}

DEFAULT_SETTINGS = {
    "engine": "offline",
    "language": "auto",
    "whisper_model": "ggml-base.bin",
    "threads": min(6, max(2, os.cpu_count() or 4)),
    "groq_key": "",
    "openai_key": "",
    "groq_model": "whisper-large-v3-turbo",
    "openai_model": "whisper-1",
}

ALLOWED_SETTINGS = set(DEFAULT_SETTINGS)


def ensure_dirs() -> None:
    for path in (DATA_DIR, MEDIA_DIR, TRANSCRIPT_DIR, OUTPUT_DIR, TMP_DIR):
        path.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            stored = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                for key in ALLOWED_SETTINGS:
                    if key in stored and stored[key] is not None:
                        settings[key] = stored[key]
        except (OSError, ValueError):
            pass

    # Variabel lingkungan menang atas file, tapi tidak ikut disimpan.
    if os.environ.get("GROQ_API_KEY"):
        settings["groq_key"] = os.environ["GROQ_API_KEY"]
    if os.environ.get("OPENAI_API_KEY"):
        settings["openai_key"] = os.environ["OPENAI_API_KEY"]
    return settings


def save_settings(updates: dict) -> dict:
    current = load_settings()
    for key, value in updates.items():
        if key in ALLOWED_SETTINGS:
            current[key] = value
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        SETTINGS_FILE.chmod(0o600)
    except OSError:
        pass
    return current


def public_settings() -> dict:
    settings = load_settings()
    return {
        "engine": settings["engine"],
        "language": settings["language"],
        "whisper_model": settings["whisper_model"],
        "threads": settings["threads"],
        "groq_model": settings["groq_model"],
        "openai_model": settings["openai_model"],
        "has_groq_key": bool(settings["groq_key"]),
        "has_openai_key": bool(settings["openai_key"]),
    }


def model_path(name: str) -> Path:
    """Cegah path traversal: hanya nama file di dalam MODELS_DIR."""
    candidate = (MODELS_DIR / Path(name).name).resolve()
    if candidate.parent != MODELS_DIR.resolve():
        raise ValueError("Nama model tidak valid")
    return candidate
