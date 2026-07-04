import pytest
from fastapi.testclient import TestClient
from avatar_service.app import create_app
from avatar_service.config import Config
from avatar_service.pipeline import run_job


def _cfg(tmp_path):
    return Config(gemini_api_key="g", dashscope_api_key="s", gemini_image_model="m",
                  tripo_model="tm", asset_dir=tmp_path, asset_base_url="", port=8800)


def _sync_runner_ok(job_id, req, cfg, jobs, assets):
    deps = {
        "generate_image": lambda prompt, **kw: b"PNGIMG",
        "submit": lambda img, **kw: "t1",
        "poll": lambda tid, **kw: "http://up/m.glb",
        "download": lambda url, **kw: b"GLB",
    }
    run_job(job_id, req, cfg, jobs, assets, deps=deps)


def test_post_avatar_then_poll_succeeds(tmp_path):
    app = create_app(_cfg(tmp_path), runner=_sync_runner_ok)
    client = TestClient(app)
    r = client.post("/avatars", json={"prompt": "a blob", "style": "3d", "shell": "creature"})
    assert r.status_code == 200
    jid = r.json()["job_id"]
    r2 = client.get(f"/avatars/{jid}")
    assert r2.status_code == 200
    body = r2.json()
    assert body["status"] == "succeeded"
    assert body["result"]["glb_url"] == f"/assets/{jid}.glb"


def test_post_empty_prompt_400(tmp_path):
    app = create_app(_cfg(tmp_path), runner=_sync_runner_ok)
    client = TestClient(app)
    assert client.post("/avatars", json={"prompt": "  "}).status_code == 400


def test_get_unknown_job_404(tmp_path):
    app = create_app(_cfg(tmp_path), runner=_sync_runner_ok)
    client = TestClient(app)
    assert client.get("/avatars/nope").status_code == 404


def test_assets_served(tmp_path):
    app = create_app(_cfg(tmp_path), runner=_sync_runner_ok)
    client = TestClient(app)
    jid = client.post("/avatars", json={"prompt": "x", "style": "3d"}).json()["job_id"]
    r = client.get(f"/assets/{jid}.glb")
    assert r.status_code == 200
    assert r.content == b"GLB"
