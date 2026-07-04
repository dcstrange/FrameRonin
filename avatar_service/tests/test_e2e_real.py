import os
import time
import pytest
from fastapi.testclient import TestClient
from avatar_service.app import create_app
from avatar_service.config import load_config

pytestmark = pytest.mark.skipif(os.environ.get("RUN_REAL_E2E") != "1",
                                reason="set RUN_REAL_E2E=1 to run real upstream test")


def test_real_prompt_to_glb(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSET_DIR", str(tmp_path))
    cfg = load_config("avatar_service/.env")  # real keys
    app = create_app(cfg)  # real thread runner
    client = TestClient(app)
    jid = client.post("/avatars", json={
        "prompt": "a cute mascot blob holding a tiny coin",
        "style": "3d", "shell": "creature"}).json()["job_id"]
    result = None
    for _ in range(60):  # up to ~5 min
        body = client.get(f"/avatars/{jid}").json()
        if body["status"] == "succeeded":
            result = body["result"]; break
        if body["status"] == "failed":
            pytest.fail(f"job failed: {body['error']}")
        time.sleep(5)
    assert result and result["glb_url"].endswith(".glb")
    glb = client.get(result["glb_url"])
    assert glb.status_code == 200 and glb.content[:4] == b"glTF"  # valid GLB magic
