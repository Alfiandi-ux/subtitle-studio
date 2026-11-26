#!/data/data/com.termux/files/usr/bin/bash
# Pasang dependensi Subtitle Studio di Termux (idempoten).
set -e
cd "$(dirname "$0")"

if command -v pkg >/dev/null 2>&1; then
  pkg install -y ffmpeg cmake git curl python
fi

if ! python3 -c "import flask" >/dev/null 2>&1; then
  pip install --upgrade Flask
fi

WHISPER_DIR="${WHISPER_DIR:-$HOME/whisper.cpp}"
if [ ! -d "$WHISPER_DIR/.git" ]; then
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git "$WHISPER_DIR"
fi

if [ ! -x "$WHISPER_DIR/build/bin/whisper-cli" ]; then
  cmake -S "$WHISPER_DIR" -B "$WHISPER_DIR/build" \
    -DCMAKE_BUILD_TYPE=Release -DWHISPER_BUILD_TESTS=OFF
  cmake --build "$WHISPER_DIR/build" -j"$(nproc)"
fi

mkdir -p "$WHISPER_DIR/models"
if [ ! -s "$WHISPER_DIR/models/ggml-base.bin" ]; then
  curl -L -o "$WHISPER_DIR/models/ggml-base.bin" \
    https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin
fi

mkdir -p assets/fonts
for font in DejaVuSans.ttf DejaVuSans-Bold.ttf; do
  if [ ! -s "assets/fonts/$font" ]; then
    curl -L -o "assets/fonts/$font" \
      "https://github.com/dejavu-fonts/dejavu-fonts/raw/version_2_37/ttf/$font"
  fi
done

echo
echo "Selesai. Jalankan: ./run.sh"
