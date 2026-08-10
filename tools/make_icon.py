"""Generate the integration's brand icons.

    .venv/bin/python tools/make_icon.py

Writes custom_components/dronetower_amu/brand/{,dark_}icon{,@2x}.png.

Since Home Assistant 2026.3 a custom integration ships its own brand images in a
`brand/` folder and they take priority over the brands CDN; home-assistant/brands
no longer accepts icons for custom integrations at all.

The mark is a quadcopter seen from above, inside two rings standing for the
monitored radius — the same idea the integration implements. Drawn oversized and
downsampled, because Pillow has no antialiasing of its own. It reaches the canvas
edge on every side so the icon carries no dead margin.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

WORK = 2048
OUT_DIR = Path("custom_components/dronetower_amu/brand")

BODY_LIGHT = (15, 43, 70, 255)  # navy, for light backgrounds
BODY_DARK = (223, 235, 244, 255)  # near-white, for dark backgrounds
RING_INNER = (46, 155, 214, 255)
RING_OUTER = (143, 213, 245, 255)


def draw_mark(size: int, body: tuple[int, ...]) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    c = size / 2

    # Proportions were designed against a 0.94 outer diameter; scaling them up
    # pushes the outer ring to the canvas edge without reshaping the mark.
    K = 1 / 0.94

    def ring(radius_frac: float, width_frac: float, colour: tuple[int, ...]) -> None:
        r = min(size * radius_frac * K, c)
        draw.ellipse(
            [c - r, c - r, min(c + r, size - 1), min(c + r, size - 1)],
            outline=colour,
            width=max(1, round(size * width_frac * K)),
        )

    ring(0.470, 0.026, RING_OUTER)
    ring(0.355, 0.030, RING_INNER)

    arm_len = size * 0.185 * K
    rotor_r = size * 0.088 * K
    arm_w = round(size * 0.048 * K)
    body_r = size * 0.072 * K

    angles = [math.radians(a) for a in (45, 135, 225, 315)]

    # Stop each arm at the inner edge of its rotor ring, otherwise the line shows
    # through the ring and reads as a notch rather than an arm.
    for angle in angles:
        end = arm_len - rotor_r
        draw.line(
            [c, c, c + math.cos(angle) * end, c + math.sin(angle) * end],
            fill=body,
            width=arm_w,
        )

    draw.ellipse([c - body_r, c - body_r, c + body_r, c + body_r], fill=body)

    for angle in angles:
        x, y = c + math.cos(angle) * arm_len, c + math.sin(angle) * arm_len
        draw.ellipse(
            [x - rotor_r, y - rotor_r, x + rotor_r, y + rotor_r],
            outline=body,
            width=max(1, round(size * 0.030 * K)),
        )

    return image


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for prefix, body in (("", BODY_LIGHT), ("dark_", BODY_DARK)):
        master = draw_mark(WORK, body)
        for name, px in ((f"{prefix}icon.png", 256), (f"{prefix}icon@2x.png", 512)):
            master.resize((px, px), Image.LANCZOS).save(OUT_DIR / name, optimize=True)
            print(f"zapisano {OUT_DIR / name} ({px}x{px})")


if __name__ == "__main__":
    main()
