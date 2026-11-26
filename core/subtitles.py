"""Konversi dan validasi segmen subtitle (SRT, VTT, TXT, ASS)."""
from __future__ import annotations

from .utils import fmt_srt_time, fmt_vtt_time, parse_time

COLORS = {
    "white": "&H00FFFFFF",
    "yellow": "&H0000FFFF",
    "cyan": "&H00FFFF00",
    "green": "&H0000FF00",
    "orange": "&H0000A5FF",
}


def normalize_segments(segments) -> list[dict]:
    """Bersihkan, urutkan, dan buang segmen tanpa teks."""
    result = []
    for item in segments or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        try:
            start = parse_time(item.get("start", 0))
            end = parse_time(item.get("end", start + 2))
        except (TypeError, ValueError):
            continue
        if end <= start:
            end = start + 0.2
        result.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
            }
        )
    result.sort(key=lambda s: (s["start"], s["end"]))
    return result


def to_srt(segments: list[dict]) -> str:
    blocks = []
    for index, seg in enumerate(segments, 1):
        text = seg["text"].replace("\r\n", "\n").strip()
        blocks.append(
            f"{index}\n{fmt_srt_time(seg['start'])} --> {fmt_srt_time(seg['end'])}\n{text}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def to_vtt(segments: list[dict]) -> str:
    blocks = ["WEBVTT\n"]
    for seg in segments:
        text = seg["text"].replace("\r\n", "\n").strip()
        blocks.append(
            f"{fmt_vtt_time(seg['start'])} --> {fmt_vtt_time(seg['end'])}\n{text}"
        )
    return "\n\n".join(blocks) + "\n"


def to_txt(segments: list[dict]) -> str:
    return "\n".join(seg["text"].strip() for seg in segments) + (
        "\n" if segments else ""
    )


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    centis = int(round(seconds * 100))
    hours, centis = divmod(centis, 360000)
    minutes, centis = divmod(centis, 6000)
    secs, centis = divmod(centis, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _ass_escape(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("{", "(").replace("}", ")")
    text = text.replace("\n", "\\N")
    return text.strip()


def to_ass(
    segments: list[dict],
    width: int,
    height: int,
    *,
    font_size: int = 0,
    color: str = "white",
    bold: bool = True,
    outline: int | None = None,
    position: str = "bottom",
    margin_v: int = 0,
) -> str:
    width = max(2, int(width or 1280))
    height = max(2, int(height or 720))
    short_side = min(width, height)

    if not font_size or font_size <= 0:
        font_size = int(round(short_side * 0.045))
    font_size = max(10, min(200, int(font_size)))
    if outline is None:
        outline = max(2, int(round(font_size * 0.055)))
    outline = max(0, min(20, int(outline)))
    if not margin_v or margin_v <= 0:
        margin_v = int(round(height * 0.05))
    margin_v = max(0, min(height // 2, int(margin_v)))

    alignment = {"bottom": 2, "middle": 5, "top": 8}.get(position, 2)
    primary = COLORS.get(color, COLORS["white"])
    bold_flag = -1 if bold else 0
    margin_h = max(20, int(width * 0.05))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,{font_size},{primary},&H000000FF,&H00000000,&H64000000,{bold_flag},0,0,0,100,100,0,0,1,{outline},0,{alignment},{margin_h},{margin_h},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for seg in segments:
        text = _ass_escape(seg["text"])
        if not text:
            continue
        lines.append(
            f"Dialogue: 0,{_ass_time(seg['start'])},{_ass_time(seg['end'])},"
            f"Default,,0,0,0,,{text}"
        )
    return "\n".join(lines) + "\n"
