#!/usr/bin/env python3
"""Generate launcher icons for Subtitle Studio Android app."""
import os
from PIL import Image, ImageDraw, ImageFont

SIZES = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RES_DIR = os.path.join(BASE_DIR, "app", "src", "main", "res")

def create_icon(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background rounded rectangle
    margin = int(size * 0.05)
    radius = int(size * 0.22)
    bg_box = [margin, margin, size - margin, size - margin]
    
    # Outer dark background
    draw.rounded_rectangle(bg_box, radius=radius, fill=(15, 18, 25, 255), outline=(111, 140, 255, 200), width=max(1, int(size * 0.03)))

    # Subtitle waveform / text box visual
    # Draw two subtitle pill bars representing speech/caption
    bar1_y1 = int(size * 0.32)
    bar1_y2 = int(size * 0.44)
    bar1_x1 = int(size * 0.22)
    bar1_x2 = int(size * 0.78)
    draw.rounded_rectangle([bar1_x1, bar1_y1, bar1_x2, bar1_y2], radius=int(size * 0.06), fill=(111, 140, 255, 255))

    bar2_y1 = int(size * 0.52)
    bar2_y2 = int(size * 0.64)
    bar2_x1 = int(size * 0.28)
    bar2_x2 = int(size * 0.72)
    draw.rounded_rectangle([bar2_x1, bar2_y1, bar2_x2, bar2_y2], radius=int(size * 0.06), fill=(45, 212, 191, 255))

    # Small mic / play badge dot
    dot_r = int(size * 0.06)
    dot_cx = int(size * 0.5)
    dot_cy = int(size * 0.76)
    draw.ellipse([dot_cx - dot_r, dot_cy - dot_r, dot_cx + dot_r, dot_cy + dot_r], fill=(255, 255, 255, 220))

    return img

def main():
    for folder, size in SIZES.items():
        out_dir = os.path.join(RES_DIR, folder)
        os.makedirs(out_dir, exist_ok=True)
        icon = create_icon(size)
        out_path = os.path.join(out_dir, "ic_launcher.png")
        icon.save(out_path, "PNG")
        print(f"Generated {out_path} ({size}x{size})")

if __name__ == "__main__":
    main()
