from pathlib import Path
from avatar_service.pipeline import run_job
from avatar_service.store import JobStore, AssetStore
from avatar_service.config import Config


def _cfg(tmp_path, base_url=""):
    return Config(gemini_api_key="g", dashscope_api_key="s",
                  gemini_image_model="m", tripo_model="tm",
                  asset_dir=tmp_path, asset_base_url=base_url, port=8800)


def _deps_ok():
    return {
        "generate_image": lambda prompt, **kw: b"PNGIMG",
        "submit": lambda img, **kw: "task1",
        "poll": lambda tid, **kw: "http://up/model.glb",
        "download": lambda url, **kw: b"GLBBYTES",
    }


def test_run_job_3d_success(tmp_path):
    cfg = _cfg(tmp_path)
    jobs, assets = JobStore(), AssetStore(tmp_path)
    jid = jobs.create()
    run_job(jid, {"prompt": "a blob", "style": "3d", "shell": "creature"},
            cfg, jobs, assets, deps=_deps_ok())
    job = jobs.get(jid)
    assert job["status"] == "succeeded"
    assert job["result"]["glb_url"] == f"/assets/{jid}.glb"
    assert job["result"]["source_image_url"] == f"/assets/{jid}.png"
    assert (tmp_path / f"{jid}.glb").read_bytes() == b"GLBBYTES"
    assert (tmp_path / f"{jid}.png").read_bytes() == b"PNGIMG"


def test_run_job_uses_asset_base_url(tmp_path):
    cfg = _cfg(tmp_path, base_url="https://cdn.example.com")
    jobs, assets = JobStore(), AssetStore(tmp_path)
    jid = jobs.create()
    run_job(jid, {"prompt": "x", "style": "3d", "shell": None}, cfg, jobs, assets, deps=_deps_ok())
    assert jobs.get(jid)["result"]["glb_url"] == f"https://cdn.example.com/assets/{jid}.glb"


def _real_png_bytes():
    import io
    from PIL import Image
    im = Image.new("RGB", (64, 64), (255, 255, 255))
    for x in range(16, 48):
        for y in range(16, 48):
            im.putpixel((x, y), (40, 130, 210))
    buf = io.BytesIO(); im.save(buf, format="PNG")
    return buf.getvalue()


def test_run_job_pixel_returns_image_url_no_glb(tmp_path):
    cfg = _cfg(tmp_path)
    jobs, assets = JobStore(), AssetStore(tmp_path)
    jid = jobs.create()
    deps = _deps_ok()
    deps["generate_image"] = lambda prompt, **kw: _real_png_bytes()  # pixel branch processes the image
    run_job(jid, {"prompt": "knight", "style": "pixel", "shell": None}, cfg, jobs, assets, deps=deps)
    job = jobs.get(jid)
    assert job["status"] == "succeeded"
    assert job["result"]["glb_url"] is None
    assert job["result"]["image_url"] == f"/assets/{jid}.png"


def test_run_job_failure_sets_error(tmp_path):
    cfg = _cfg(tmp_path)
    jobs, assets = JobStore(), AssetStore(tmp_path)
    jid = jobs.create()
    def boom(prompt, **kw):
        raise RuntimeError("gemini down")
    deps = _deps_ok(); deps["generate_image"] = boom
    run_job(jid, {"prompt": "x", "style": "3d", "shell": None}, cfg, jobs, assets, deps=deps)
    job = jobs.get(jid)
    assert job["status"] == "failed"
    assert "gemini down" in job["error"]
