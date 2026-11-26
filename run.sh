#!/data/data/com.termux/files/usr/bin/bash
set -e
cd "$(dirname "$0")"
export SS_HOST="${SS_HOST:-127.0.0.1}"
export SS_PORT="${SS_PORT:-8765}"
exec python3 app.py
