"""Generate the brand icons for home-assistant/brands.

    .venv/bin/python tools/make_icon.py

Writes brands/custom_integrations/dronetower_amu/{icon,icon@2x}.png.

The mark is a quadcopter seen from above, inside two rings standing for the
monitored radius — the same idea the integration implements. Drawn oversized and
downsampled, because Pillow has no antialiasing of its own.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

WORK = 2048
OUT_DIR = Path("brands/custom_integrations/dronetower_amu")

NAVY = (15, 43, 70, 255)
BLUE = (46, 155, 214, 255)
PALE = (143, 213, 245, 255)


def draw_mark(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    c = size / 2

    # home-assistant/brands rejects images with transparent padding, so the outer
    # ring has to reach the canvas edge. Every other proportion is scaled to match.
    K = 1 / 0.94

    def ring(radius_frac: float, width_frac: float, colour: tuple[int, ...]) -> None:
        r = min(size * radius_frac * K, c)
        draw.ellipse(
            [c - r, c - r, min(c + r, size - 1), min(c + r, size - 1)],
            outline=colour,
            width=max(1, round(size * width_frac * K)),
        )

    # Monitored area: an outer boundary and an inner one for depth.
    ring(0.470, 0.026, PALE)
    ring(0.355, 0.030, BLUE)

    # Quadcopter, top view: four rotors on the diagonals joined by arms.
    arm_len = size * 0.185 * K
    rotor_r = size * 0.088 * K
    arm_w = round(size * 0.048 * K)
    body_r = size * 0.072 * K

    angles = [math.radians(a) for a in (45, 135, 225, 315)]
    offsets = [(math.cos(a) * arm_len, math.sin(a) * arm_len) for a in angles]

    # Stop each arm at the inner edge of its rotor ring, otherwise the line shows
    # through the ring and reads as a notch rather than an arm.
    for angle in angles:
        end = arm_len - rotor_r
        draw.line(
            [c, c, c + math.cos(angle) * end, c + math.sin(angle) * end],
            fill=NAVY,
            width=arm_w,
        )

    draw.ellipse([c - body_r, c - body_r, c + body_r, c + body_r], fill=NAVY)

    for dx, dy in offsets:
        x, y = c + dx, c + dy
        draw.ellipse(
            [x - rotor_r, y - rotor_r, x + rotor_r, y + rotor_r],
            outline=NAVY,
            width=max(1, round(size * 0.030)),
        )

    return image


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    master = draw_mark(WORK)

    for name, px in (("icon.png", 256), ("icon@2x.png", 512)):
        master.resize((px, px), Image.LANCZOS).save(OUT_DIR / name, optimize=True)
        print(f"zapisano {OUT_DIR / name} ({px}x{px})")


if __name__ == "__main__":
    main()
