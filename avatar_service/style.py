from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw

SHELLS = {
    "creature": "Render the character as a small round blob-like creature companion "
                "with big eyes and tiny stubby limbs",
    "humanoid": "Render the character as a small chibi humanoid with a big head and a small body",
    "ai_spirit": "Render the character as a small rounded floating spirit companion with a minimal cute face",
}

_STYLE_3D = (
    "Cute 3D cartoon character in the style of a Pop Mart designer vinyl toy / blind-box "
    "figure. Soft rounded chibi proportions, smooth matte plastic surfaces, gentle soft "
    "studio lighting with soft shadows, clean pastel colors, high quality 3D render, "
    "centered, front-facing, full body, on a plain solid white background."
)
_STYLE_PIXEL = (
    "Low-resolution retro pixel art sprite, chunky clearly visible square pixels, limited "
    "color palette, bold clean outline, no anti-aliasing, centered, front-facing, full "
    "body, on a plain solid white background."
)


def build_prompt(prompt: str, *, style: str, shell: str | None) -> str:
    shell_txt = SHELLS.get(shell, "") if shell else ""
    base = ". ".join(p for p in (shell_txt.rstrip("."), prompt.strip().rstrip(".")) if p)
    style_txt = _STYLE_PIXEL if style == "pixel" else _STYLE_3D
    return f"{base}. {style_txt}"


def _key_white_bg(img: Image.Image, thresh: int = 30) -> Image.Image:
    rgb = img.convert("RGB")
    sentinel = (255, 0, 255)
    w, h = rgb.size
    for corner in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        ImageDraw.floodfill(rgb, corner, sentinel, thresh=thresh)
    arr = np.asarray(rgb)
    is_sentinel = np.all(arr == np.array(sentinel), axis=-1)
    out = img.convert("RGBA").copy()
    a = np.asarray(out).copy()
    a[..., 3] = np.where(is_sentinel, 0, a[..., 3])
    return Image.fromarray(a, "RGBA")


def pixelate_png(image_bytes: bytes, *, grid_h: int = 64, colors: int = 16) -> bytes:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    gw = max(1, round(w * grid_h / h))
    small = img.resize((gw, grid_h), Image.BILINEAR)
    small = small.quantize(colors=colors, method=Image.MEDIANCUT, dither=0).convert("RGB")
    keyed = _key_white_bg(small.convert("RGBA"), thresh=30)
    buf = io.BytesIO()
    keyed.save(buf, format="PNG")
    return buf.getvalue()
