"""Pembungkus ffmpeg: progres, trim, burn subtitle, gabung, kompres."""
from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

from . import config
from .utils import FFMPEG, fmt_clock, fmt_duration

DEFAULT_PRESET = "veryfast"


def run_ffmpeg(
    job,
    args: list[str],
    *,
    duration: float | None = None,
    p0: float = 0,
    p1: float = 100,
    cwd: Path | None = None,
) -> None:
    """Jalankan ffmpeg sambil memperbarui progres job."""
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats"]
    cmd.extend(str(arg) for arg in args)

    process = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    errors: list[str] = []

    def read_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            line = line.rstrip()
            if line:
                errors.append(line)
                del errors[:-40]

    err_thread = threading.Thread(target=read_stderr, daemon=True)
    err_thread.start()

    if duration and duration > 0:
        job.progress = p0
    else:
        job.progress = None

    cancelled = False
    assert process.stdout is not None
    for line in process.stdout:
        line = line.strip()
        if job.cancel_event.is_set():
            cancelled = True
            process.kill()
            break
        if line.startswith("out_time_us="):
            try:
                elapsed = int(line.split("=", 1)[1]) / 1_000_000
            except ValueError:
                continue
            if duration and duration > 0:
                ratio = min(0.995, max(0.0, elapsed / duration))
                job.progress = p0 + (p1 - p0) * ratio
                job.message = f"{fmt_clock(elapsed)} / {fmt_duration(duration)}"
        elif line.startswith("out_time="):
            job.message = line.split("=", 1)[1].split(".")[0]

    process.wait()
    err_thread.join(timeout=2)

    if cancelled or job.cancel_event.is_set():
        raise RuntimeError("Job dibatalkan")

    if process.returncode != 0:
        detail = "\n".join(errors[-6:]) or f"kode keluar {process.returncode}"
        raise RuntimeError(f"FFmpeg gagal: {detail}")

    job.progress = p1
    job.message = ""


def make_thumbnail(src: Path, dst: Path) -> bool:
    for seek in ("0.5", "0"):
        cmd = [
            FFMPEG,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-ss",
            seek,
            "-i",
            str(src),
            "-frames:v",
            "1",
            "-vf",
            "scale=480:-2",
            "-q:v",
            "4",
            str(dst),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and dst.exists() and dst.stat().st_size > 0:
            return True
    return False


def extract_audio(
    job,
    src: Path,
    dst: Path,
    *,
    fmt: str = "wav",
    duration: float | None = None,
    p0: float = 0,
    p1: float = 100,
) -> Path:
    args = ["-i", str(src), "-vn", "-ac", "1", "-ar", "16000"]
    if fmt == "wav":
        args += ["-c:a", "pcm_s16le"]
    elif fmt == "m4a":
        args += ["-c:a", "aac", "-b:a", "64k"]
    else:
        args += ["-c:a", "libmp3lame", "-b:a", "48k"]
    args.append(str(dst))
    run_ffmpeg(job, args, duration=duration, p0=p0, p1=p1)
    return dst


def trim(
    job,
    src: Path,
    dst: Path,
    *,
    start: float,
    end: float,
    has_video: bool,
    mode: str = "reencode",
    duration: float | None = None,
) -> None:
    span = max(0.1, end - start)
    args = ["-ss", f"{start:.3f}", "-i", str(src), "-t", f"{span:.3f}"]
    if mode == "copy":
        args += ["-c", "copy", "-avoid_negative_ts", "make_zero", str(dst)]
    elif has_video:
        args += [
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            DEFAULT_PRESET,
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            str(dst),
        ]
    else:
        args += ["-vn", "-c:a", "libmp3lame", "-q:a", "2", str(dst)]
    run_ffmpeg(job, args, duration=span, p0=0, p1=100)


def burn_subtitles(
    job,
    src: Path,
    ass_name: str,
    dst: Path,
    *,
    duration: float | None = None,
    workdir: Path | None = None,
) -> None:
    fonts = str(config.FONT_DIR).replace("'", r"\'")
    filter_value = f"ass=filename={ass_name}:fontsdir='{fonts}'"
    args = [
        "-i",
        str(src),
        "-vf",
        filter_value,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        DEFAULT_PRESET,
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        str(dst),
    ]
    run_ffmpeg(job, args, duration=duration, cwd=workdir, p0=0, p1=100)


def _even(value: int) -> int:
    value = int(value)
    if value < 2:
        return 2
    return value if value % 2 == 0 else value - 1


def concat(
    job,
    clips: list[dict],
    dst: Path,
    *,
    width: int,
    height: int,
    fps: int = 30,
) -> None:
    """Normalisasi tiap klip lalu gabung dengan concat demuxer."""
    width = _even(max(2, width))
    height = _even(max(2, height))
    fps = max(10, min(60, int(fps or 30)))
    workdir = job.dir
    normalized: list[Path] = []
    total = len(clips)

    for index, clip in enumerate(clips):
        p0 = 0 + (index / max(1, total)) * 90
        p1 = ((index + 1) / max(1, total)) * 90
        job.stage = f"Menormalisasi klip {index + 1}/{total}"
        out = workdir / f"clip_{index:03d}.mp4"
        duration = float(clip.get("duration") or 0)
        has_audio = bool(clip.get("has_audio"))

        args = ["-i", clip["path"]]
        if not has_audio:
            args += [
                "-f",
                "lavfi",
                "-t",
                f"{max(0.5, duration):.3f}",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
            ]
        args += [
            "-vf",
            (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
                f"fps={fps},format=yuv420p"
            ),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0" if has_audio else "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            DEFAULT_PRESET,
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
        ]
        if not has_audio:
            args += ["-shortest"]
        args.append(str(out))
        run_ffmpeg(
            job,
            args,
            duration=duration if duration > 0 else None,
            p0=p0,
            p1=p1,
        )
        normalized.append(out)

    job.stage = "Menggabungkan klip"
    list_file = workdir / "concat.txt"
    list_file.write_text(
        "\n".join(f"file '{clip.name}'" for clip in normalized) + "\n",
        encoding="utf-8",
    )
    run_ffmpeg(
        job,
        ["-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy",
         "-movflags", "+faststart", str(dst)],
        duration=None,
        p0=90,
        p1=100,
        cwd=workdir,
    )


def transform(
    job,
    src: Path,
    dst: Path,
    *,
    width: int = 0,
    crf: int = 23,
    preset: str = DEFAULT_PRESET,
    fps: int | None = None,
    has_video: bool = True,
    duration: float | None = None,
) -> None:
    if not has_video:
        extract_audio(job, src, dst, fmt="mp3", duration=duration)
        return

    filters = []
    if width and width > 0:
        filters.append(f"scale={_even(width)}:-2")
    if fps:
        filters.append(f"fps={max(10, min(60, int(fps)))}")

    args = ["-i", str(src)]
    if filters:
        args += ["-vf", ",".join(filters)]
    args += [
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        preset if preset in {
            "ultrafast", "superfast", "veryfast", "faster", "fast",
            "medium", "slow", "slower", "veryslow",
        } else DEFAULT_PRESET,
        "-crf",
        str(max(16, min(35, int(crf)))),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(dst),
    ]
    run_ffmpeg(job, args, duration=duration, p0=0, p1=100)


def export_audio(job, src: Path, dst: Path, *, fmt: str, duration: float | None) -> None:
    args = ["-i", str(src), "-vn"]
    if fmt == "wav":
        args += ["-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2"]
    elif fmt == "m4a":
        args += ["-c:a", "aac", "-b:a", "192k"]
    else:
        args += ["-c:a", "libmp3lame", "-q:a", "2"]
    args.append(str(dst))
    run_ffmpeg(job, args, duration=duration, p0=0, p1=100)


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg"))
