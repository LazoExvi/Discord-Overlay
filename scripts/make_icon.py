"""Render the application icon (PNG + multi-size ICO) with Pillow.

Usage: python scripts/make_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "discord_overlay" / "assets"
SIZE = 512
BG = (11, 17, 24)
PANEL = (23, 35, 48)
AMBER = (211, 155, 71)
GREEN = (66, 211, 146)
RED = (255, 101, 119)
TEXT = (231, 237, 244)


def render(size: int = SIZE) -> Image.Image:
    scale = size / SIZE
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def s(value: float) -> int:
        return int(round(value * scale))

    draw.rounded_rectangle((s(16), s(16), s(496), s(496)), radius=s(96), fill=BG)
    draw.rounded_rectangle((s(64), s(112), s(448), s(400)), radius=s(28), fill=PANEL)
    # Three "combat log" bars of different lengths and colors.
    bars = ((AMBER, 300), (RED, 190), (GREEN, 250), (AMBER, 140))
    top = 150
    for color, width in bars:
        draw.rounded_rectangle((s(100), s(top), s(100 + width), s(top + 34)), radius=s(12), fill=color)
        top += 58
    # Countdown ring in the lower right, like a timer card.
    box = (s(320), s(272), s(420), s(372))
    draw.ellipse(box, outline=(38, 52, 64), width=s(14))
    draw.arc(box, start=-90, end=200, fill=AMBER, width=s(14))
    return image


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    icon = render()
    icon.save(ASSETS / "icon.png")
    icon.save(ASSETS / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Wrote icon.png and icon.ico to {ASSETS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
