#!/data/data/com.termux/files/usr/bin/bash
# Hentikan server Subtitle Studio yang berjalan.
PIDS="$(ps -eo pid,args | awk '/[p]ython3 app.py/{print $1}')"
if [ -n "$PIDS" ]; then
  # shellcheck disable=SC2086
  kill $PIDS
  echo "Server Subtitle Studio dihentikan."
else
  echo "Tidak ada server Subtitle Studio yang berjalan."
fi
