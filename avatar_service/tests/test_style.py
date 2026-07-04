import io
from PIL import Image
from avatar_service.style import build_prompt, pixelate_png, SHELLS


def test_build_prompt_3d_includes_shell_and_style():
    p = build_prompt("a finance clerk", style="3d", shell="creature")
    assert "finance clerk" in p
    assert SHELLS["creature"].split()[0].lower() in p.lower() or "blob" in p.lower()
    assert "Pop Mart" in p or "3D" in p


def test_build_prompt_pixel_style():
    p = build_prompt("a knight", style="pixel", shell=None)
    assert "knight" in p
    assert "pixel" in p.lower()


def test_pixelate_png_shrinks_and_returns_png():
    src = Image.new("RGB", (512, 512), (255, 255, 255))
    for x in range(120, 400):
        for y in range(120, 400):
            src.putpixel((x, y), (30, 120, 200))
    buf = io.BytesIO(); src.save(buf, format="PNG")
    out = pixelate_png(buf.getvalue(), grid_h=48, colors=8)
    im = Image.open(io.BytesIO(out))
    assert im.mode == "RGBA"
    assert im.height <= 48
