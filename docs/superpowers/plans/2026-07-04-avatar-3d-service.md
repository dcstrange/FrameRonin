# AI 3D 形象生成服务 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone, packaged FastAPI backend service that turns a text prompt into a hosted 3D (GLB) avatar via Gemini image generation + Tripo image-to-3D (through Aliyun DashScope), exposed as an async submit/poll HTTP API.

**Architecture:** A resident FastAPI process. `POST /avatars` creates a job and runs the pipeline in a background thread; `GET /avatars/{id}` polls status; `GET /assets/{file}` serves hosted GLB/preview/source. The pipeline (prompt → Gemini image → base64 → DashScope Tripo image-to-3D → poll → download GLB → host) is framework-agnostic and unit-tested with mocked upstream HTTP. Proven logic is ported from `scripts/gemini_image.py`, `scripts/tripo_image_to_3d.py`, `scripts/sprite_utils.py`.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, requests, Pillow, python-dotenv, pytest.

## Global Constraints

- All service code lives under `avatar_service/` — a self-contained package, NOT inside the existing `backend/`.
- Upstream API keys (`GEMINI_API_KEY`, `DASHSCOPE_API_KEY`) read ONLY from `.env` via python-dotenv; never hardcoded, never committed. `.env` is gitignored; `.env.example` (no real keys) IS committed.
- Dependencies limited to: `fastapi`, `uvicorn[standard]`, `requests`, `pillow`, `python-dotenv`, `pytest` (dev). No Redis/DB/OSS this iteration.
- Default `GEMINI_IMAGE_MODEL=gemini-3.1-flash-image`, `TRIPO_MODEL=Tripo/Tripo-P1.0`, `PORT=8800`.
- DashScope image-to-3D endpoint: `POST https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/3d-generation`, header `X-DashScope-Async: enable`, model in body `{"model": TRIPO_MODEL, "input": {"image": "data:image/png;base64,..."}}`. Poll `GET https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}` until `output.task_status == "SUCCEEDED"`; GLB at `output.results[0].pbr_model_url`.
- Gemini image endpoint: `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`, header `X-goog-api-key: {key}`, body `{"contents":[{"parts":[{"text": prompt}]}],"generationConfig":{"responseModalities":["IMAGE"]}}`; image bytes are base64 in `candidates[0].content.parts[*].inlineData.data`.
- Upstream DashScope path has intermittent SSL/handshake errors (~1/3 of calls): all DashScope HTTP calls wrapped in a retry helper (default 5 attempts, small backoff).
- Job `status` values: `pending | running | succeeded | failed`. Progress values: `generating_image | converting_3d | downloading | done`.
- Tests must not call real upstreams (mock HTTP); one final task does a real-key end-to-end validation, gated behind an env flag.

---

### Task 1: Scaffold package, config, dependencies

**Files:**
- Create: `avatar_service/__init__.py` (empty)
- Create: `avatar_service/config.py`
- Create: `avatar_service/requirements.txt`
- Create: `avatar_service/.env.example`
- Modify: `.gitignore` (add `avatar_service/.env` and `avatar_service/assets/`)
- Test: `avatar_service/tests/__init__.py` (empty), `avatar_service/tests/test_config.py`

**Interfaces:**
- Produces: `avatar_service.config.Config` dataclass with fields `gemini_api_key: str`, `dashscope_api_key: str`, `gemini_image_model: str`, `tripo_model: str`, `asset_dir: Path`, `asset_base_url: str`, `port: int`. Function `load_config(env_path: str | None = None) -> Config` (reads `.env` via dotenv, applies defaults, expands `asset_dir` to an absolute Path and creates it).

- [ ] **Step 1: Write the failing test**

```python
# avatar_service/tests/test_config.py
from pathlib import Path
from avatar_service.config import load_config, Config


def test_load_config_reads_env_and_defaults(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "GEMINI_API_KEY=g123\n"
        "DASHSCOPE_API_KEY=sk-abc\n"
    )
    cfg = load_config(str(env))
    assert isinstance(cfg, Config)
    assert cfg.gemini_api_key == "g123"
    assert cfg.dashscope_api_key == "sk-abc"
    assert cfg.gemini_image_model == "gemini-3.1-flash-image"  # default
    assert cfg.tripo_model == "Tripo/Tripo-P1.0"               # default
    assert cfg.port == 8800                                    # default
    assert cfg.asset_dir.is_absolute() and cfg.asset_dir.exists()


def test_load_config_overrides(tmp_path):
    env = tmp_path / ".env"
    asset_dir = tmp_path / "myassets"
    env.write_text(
        f"GEMINI_API_KEY=g\nDASHSCOPE_API_KEY=s\nPORT=9000\n"
        f"ASSET_DIR={asset_dir}\nGEMINI_IMAGE_MODEL=gemini-2.5-flash-image\n"
    )
    cfg = load_config(str(env))
    assert cfg.port == 9000
    assert cfg.asset_dir == asset_dir.resolve()
    assert cfg.gemini_image_model == "gemini-2.5-flash-image"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd avatar_service && python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'avatar_service.config'`

- [ ] **Step 3: Write minimal implementation**

```python
# avatar_service/config.py
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Config:
    gemini_api_key: str
    dashscope_api_key: str
    gemini_image_model: str
    tripo_model: str
    asset_dir: Path
    asset_base_url: str
    port: int


def load_config(env_path: str | None = None) -> Config:
    load_dotenv(env_path, override=True)
    asset_dir = Path(os.environ.get("ASSET_DIR", "assets")).resolve()
    asset_dir.mkdir(parents=True, exist_ok=True)
    return Config(
        gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
        dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        gemini_image_model=os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image"),
        tripo_model=os.environ.get("TRIPO_MODEL", "Tripo/Tripo-P1.0"),
        asset_dir=asset_dir,
        asset_base_url=os.environ.get("ASSET_BASE_URL", ""),
        port=int(os.environ.get("PORT", "8800")),
    )
```

```txt
# avatar_service/requirements.txt
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
requests>=2.31.0
pillow>=10.0.0
python-dotenv>=1.0.0
pytest>=8.0.0
```

```txt
# avatar_service/.env.example
GEMINI_API_KEY=
DASHSCOPE_API_KEY=
GEMINI_IMAGE_MODEL=gemini-3.1-flash-image
TRIPO_MODEL=Tripo/Tripo-P1.0
ASSET_DIR=assets
ASSET_BASE_URL=
PORT=8800
```

Create empty `avatar_service/__init__.py` and `avatar_service/tests/__init__.py`. Append to `.gitignore`:
```
avatar_service/.env
avatar_service/assets/
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd avatar_service && python -m pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add avatar_service/__init__.py avatar_service/config.py avatar_service/requirements.txt avatar_service/.env.example avatar_service/tests/__init__.py avatar_service/tests/test_config.py .gitignore
git commit -m "feat(avatar-service): scaffold package + config loader"
```

---

### Task 2: Gemini image client

**Files:**
- Create: `avatar_service/gemini_client.py`
- Test: `avatar_service/tests/test_gemini_client.py`

**Interfaces:**
- Consumes: nothing from prior tasks (takes plain args).
- Produces: `generate_image(prompt: str, *, api_key: str, model: str, session=None) -> bytes` — returns raw image bytes. Raises `GeminiError(str)` on API error or missing image. `session` optional (a `requests.Session`-like object with `.post`) for test injection.

- [ ] **Step 1: Write the failing test**

```python
# avatar_service/tests/test_gemini_client.py
import base64
import pytest
from avatar_service.gemini_client import generate_image, GeminiError


class FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, resp):
        self._resp = resp
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self._resp


def _img_payload(raw: bytes):
    b64 = base64.b64encode(raw).decode()
    return {"candidates": [{"content": {"parts": [{"inlineData": {"data": b64, "mimeType": "image/png"}}]}}]}


def test_generate_image_returns_bytes():
    raw = b"\x89PNG_fake_bytes"
    sess = FakeSession(FakeResp(200, _img_payload(raw)))
    out = generate_image("a cute blob", api_key="k", model="m", session=sess)
    assert out == raw
    # sends key header + IMAGE modality
    assert sess.calls[0]["headers"]["X-goog-api-key"] == "k"
    assert sess.calls[0]["json"]["generationConfig"]["responseModalities"] == ["IMAGE"]
    assert "m:generateContent" in sess.calls[0]["url"]


def test_generate_image_api_error_raises():
    sess = FakeSession(FakeResp(400, {"error": {"message": "bad"}}))
    with pytest.raises(GeminiError):
        generate_image("x", api_key="k", model="m", session=sess)


def test_generate_image_no_image_raises():
    payload = {"candidates": [{"content": {"parts": [{"text": "refused"}]}}]}
    sess = FakeSession(FakeResp(200, payload))
    with pytest.raises(GeminiError):
        generate_image("x", api_key="k", model="m", session=sess)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd avatar_service && python -m pytest tests/test_gemini_client.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# avatar_service/gemini_client.py
from __future__ import annotations

import base64

import requests

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiError(RuntimeError):
    pass


def generate_image(prompt: str, *, api_key: str, model: str, session=None) -> bytes:
    sess = session or requests
    url = _ENDPOINT.format(model=model)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    resp = sess.post(
        url,
        headers={"Content-Type": "application/json", "X-goog-api-key": api_key},
        json=body,
        timeout=120,
    )
    if resp.status_code != 200:
        raise GeminiError(f"Gemini HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if "error" in data:
        raise GeminiError(f"Gemini error: {data['error']}")
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError) as e:
        raise GeminiError(f"Unexpected Gemini response: {data}") from e
    for p in parts:
        blob = p.get("inlineData") or p.get("inline_data")
        if blob and blob.get("data"):
            return base64.b64decode(blob["data"])
    texts = " ".join(p.get("text", "") for p in parts)
    raise GeminiError(f"No image returned. Model said: {texts or '(nothing)'}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd avatar_service && python -m pytest tests/test_gemini_client.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add avatar_service/gemini_client.py avatar_service/tests/test_gemini_client.py
git commit -m "feat(avatar-service): gemini image client with tests"
```

---

### Task 3: Tripo (DashScope) image-to-3D client with retry

**Files:**
- Create: `avatar_service/tripo_client.py`
- Test: `avatar_service/tests/test_tripo_client.py`

**Interfaces:**
- Consumes: nothing from prior tasks.
- Produces:
  - `with_retry(fn, *, attempts=5, backoff=0.0, exceptions=(Exception,))` — calls `fn()`, retrying on listed exceptions; re-raises last on exhaustion. `backoff` seconds between tries (0 in tests).
  - `submit(image_bytes: bytes, *, api_key: str, model: str, session=None) -> str` — returns `task_id`. Raises `TripoError`.
  - `poll(task_id: str, *, api_key: str, session=None, interval: float = 8.0, timeout: float = 600.0, sleep=time.sleep) -> str` — polls until SUCCEEDED, returns GLB url. Raises `TripoError` on FAILED/timeout. `sleep` injectable for tests.
  - `download(url: str, *, session=None) -> bytes`.

- [ ] **Step 1: Write the failing test**

```python
# avatar_service/tests/test_tripo_client.py
import base64
import pytest
from avatar_service.tripo_client import submit, poll, with_retry, TripoError


class FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class SeqSession:
    """Returns queued responses in order for get/post."""
    def __init__(self, posts=None, gets=None):
        self._posts = list(posts or [])
        self._gets = list(gets or [])
        self.post_bodies = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.post_bodies.append(json)
        return self._posts.pop(0)

    def get(self, url, headers=None, timeout=None):
        return self._gets.pop(0)


def test_submit_returns_task_id_and_sends_base64():
    sess = SeqSession(posts=[FakeResp(200, {"output": {"task_id": "t1", "task_status": "PENDING"}})])
    tid = submit(b"IMGDATA", api_key="sk", model="Tripo/Tripo-P1.0", session=sess)
    assert tid == "t1"
    img = sess.post_bodies[0]["input"]["image"]
    assert img.startswith("data:image/png;base64,")
    assert base64.b64decode(img.split(",", 1)[1]) == b"IMGDATA"


def test_submit_no_task_id_raises():
    sess = SeqSession(posts=[FakeResp(200, {"output": {}})])
    with pytest.raises(TripoError):
        submit(b"x", api_key="sk", model="m", session=sess)


def test_poll_succeeds_after_running():
    gets = [
        FakeResp(200, {"output": {"task_status": "RUNNING"}}),
        FakeResp(200, {"output": {"task_status": "SUCCEEDED",
                                   "results": [{"pbr_model_url": "http://x/model.glb"}]}}),
    ]
    sess = SeqSession(gets=gets)
    url = poll("t1", api_key="sk", session=sess, interval=0, sleep=lambda s: None)
    assert url == "http://x/model.glb"


def test_poll_failed_raises():
    sess = SeqSession(gets=[FakeResp(200, {"output": {"task_status": "FAILED",
                                                       "code": "X", "message": "not activated"}})])
    with pytest.raises(TripoError) as e:
        poll("t1", api_key="sk", session=sess, interval=0, sleep=lambda s: None)
    assert "not activated" in str(e.value)


def test_with_retry_retries_then_succeeds():
    calls = {"n": 0}
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("ssl reset")
        return "ok"
    assert with_retry(flaky, attempts=5, backoff=0) == "ok"
    assert calls["n"] == 3


def test_with_retry_exhausts_and_raises():
    def always_fail():
        raise ConnectionError("nope")
    with pytest.raises(ConnectionError):
        with_retry(always_fail, attempts=2, backoff=0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd avatar_service && python -m pytest tests/test_tripo_client.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# avatar_service/tripo_client.py
from __future__ import annotations

import base64
import time

import requests

_BASE = "https://dashscope.aliyuncs.com/api/v1"
_SUBMIT = _BASE + "/services/aigc/video-generation/3d-generation"
_TASK = _BASE + "/tasks/{}"


class TripoError(RuntimeError):
    pass


def with_retry(fn, *, attempts=5, backoff=0.0, exceptions=(Exception,)):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except exceptions as e:  # noqa: PERF203
            last = e
            if i < attempts - 1 and backoff:
                time.sleep(backoff)
    raise last


def submit(image_bytes: bytes, *, api_key: str, model: str, session=None) -> str:
    sess = session or requests
    b64 = base64.b64encode(image_bytes).decode()
    body = {"model": model, "input": {"image": f"data:image/png;base64,{b64}"}}
    resp = sess.post(
        _SUBMIT,
        headers={"Authorization": f"Bearer {api_key}",
                 "X-DashScope-Async": "enable", "Content-Type": "application/json"},
        json=body, timeout=60,
    )
    if resp.status_code != 200:
        raise TripoError(f"submit HTTP {resp.status_code}: {resp.text[:300]}")
    tid = (resp.json().get("output") or {}).get("task_id")
    if not tid:
        raise TripoError(f"submit: no task_id in {resp.json()}")
    return tid


def poll(task_id, *, api_key, session=None, interval=8.0, timeout=600.0, sleep=time.sleep) -> str:
    sess = session or requests
    waited = 0.0
    while waited <= timeout:
        resp = sess.get(_TASK.format(task_id),
                        headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
        out = (resp.json() or {}).get("output", {})
        st = out.get("task_status")
        if st == "SUCCEEDED":
            results = out.get("results") or []
            url = (results[0] if results else {}).get("pbr_model_url")
            if not url:
                raise TripoError(f"succeeded but no model url: {out}")
            return url
        if st == "FAILED":
            raise TripoError(f"task failed: {out.get('code')} — {out.get('message')}")
        sleep(interval)
        waited += max(interval, 0.001)
    raise TripoError("poll timeout")


def download(url: str, *, session=None) -> bytes:
    sess = session or requests
    resp = sess.get(url, timeout=120)
    if resp.status_code != 200:
        raise TripoError(f"download HTTP {resp.status_code}")
    return resp.content
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd avatar_service && python -m pytest tests/test_tripo_client.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add avatar_service/tripo_client.py avatar_service/tests/test_tripo_client.py
git commit -m "feat(avatar-service): tripo/dashscope image-to-3d client with retry"
```

---

### Task 4: Job + asset store

**Files:**
- Create: `avatar_service/store.py`
- Test: `avatar_service/tests/test_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `JobStore`: `create() -> str` (returns new job_id, initial `{"job_id", "status":"pending", "progress":None, "result":None, "error":None}`); `get(job_id) -> dict | None`; `update(job_id, **fields) -> None` (merges fields into the job dict). Thread-safe (internal lock).
  - `AssetStore(asset_dir: Path)`: `save(job_id: str, ext: str, data: bytes) -> str` (writes `{job_id}.{ext}` into asset_dir, returns the filename); `path(filename) -> Path`.

- [ ] **Step 1: Write the failing test**

```python
# avatar_service/tests/test_store.py
from avatar_service.store import JobStore, AssetStore


def test_jobstore_create_get_update():
    js = JobStore()
    jid = js.create()
    job = js.get(jid)
    assert job["status"] == "pending"
    assert job["job_id"] == jid
    js.update(jid, status="running", progress="generating_image")
    assert js.get(jid)["status"] == "running"
    assert js.get(jid)["progress"] == "generating_image"
    assert js.get("nope") is None


def test_assetstore_save_and_path(tmp_path):
    store = AssetStore(tmp_path)
    fn = store.save("abc", "glb", b"GLBDATA")
    assert fn == "abc.glb"
    assert (tmp_path / "abc.glb").read_bytes() == b"GLBDATA"
    assert store.path("abc.glb") == tmp_path / "abc.glb"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd avatar_service && python -m pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# avatar_service/store.py
from __future__ import annotations

import threading
import uuid
from pathlib import Path


class JobStore:
    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self) -> str:
        jid = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[jid] = {
                "job_id": jid, "status": "pending",
                "progress": None, "result": None, "error": None,
            }
        return jid

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def update(self, job_id: str, **fields) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(fields)


class AssetStore:
    def __init__(self, asset_dir: Path):
        self.asset_dir = Path(asset_dir)
        self.asset_dir.mkdir(parents=True, exist_ok=True)

    def save(self, job_id: str, ext: str, data: bytes) -> str:
        filename = f"{job_id}.{ext}"
        (self.asset_dir / filename).write_bytes(data)
        return filename

    def path(self, filename: str) -> Path:
        return self.asset_dir / filename
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd avatar_service && python -m pytest tests/test_store.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add avatar_service/store.py avatar_service/tests/test_store.py
git commit -m "feat(avatar-service): job + asset store"
```

---

### Task 5: Prompt builder + pixelate helper

**Files:**
- Create: `avatar_service/style.py`
- Test: `avatar_service/tests/test_style.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `SHELLS: dict[str, str]` (keys `creature`, `humanoid`, `ai_spirit`).
  - `build_prompt(prompt: str, *, style: str, shell: str | None) -> str` — composes shell + character + style system prompt. `style` in `{"3d","pixel"}`.
  - `pixelate_png(image_bytes: bytes, *, grid_h: int = 64, colors: int = 16) -> bytes` — returns PNG bytes downscaled to a coarse pixel look (ported from `scripts/sprite_utils.py` `pixelate`), keying near-white bg to transparent. Used only for `style="pixel"`.

- [ ] **Step 1: Write the failing test**

```python
# avatar_service/tests/test_style.py
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
    assert im.height <= 48  # coarse
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd avatar_service && python -m pytest tests/test_style.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# avatar_service/style.py
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
```

Note: this introduces `numpy` — add `numpy>=1.24.0` to `avatar_service/requirements.txt` in this task's commit.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd avatar_service && python -m pytest tests/test_style.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add avatar_service/style.py avatar_service/tests/test_style.py avatar_service/requirements.txt
git commit -m "feat(avatar-service): prompt builder + pixelate helper"
```

---

### Task 6: Pipeline orchestrator

**Files:**
- Create: `avatar_service/pipeline.py`
- Test: `avatar_service/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `gemini_client.generate_image`, `tripo_client.{submit,poll,download,with_retry,TripoError}`, `gemini_client.GeminiError`, `store.{JobStore,AssetStore}`, `style.{build_prompt,pixelate_png}`, `config.Config`.
- Produces: `run_job(job_id: str, req: dict, cfg: Config, jobs: JobStore, assets: AssetStore, *, deps: dict | None = None) -> None`. `req` = `{"prompt","style","shell"}`. Updates `jobs` through progress → sets `result` on success or `error` + `status:"failed"` on any exception. `deps` allows injecting fakes for `generate_image`, `submit`, `poll`, `download` in tests; defaults to the real client functions.
  - Success result for `3d`: `{"glb_url","preview_url","source_image_url"}`. For `pixel`: `{"glb_url": None, "image_url": ...}`.
  - URL builder: `f"{cfg.asset_base_url}/assets/{filename}"` if `asset_base_url` else `f"/assets/{filename}"`.

- [ ] **Step 1: Write the failing test**

```python
# avatar_service/tests/test_pipeline.py
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


def test_run_job_pixel_returns_image_url_no_glb(tmp_path):
    cfg = _cfg(tmp_path)
    jobs, assets = JobStore(), AssetStore(tmp_path)
    jid = jobs.create()
    deps = _deps_ok()
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd avatar_service && python -m pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# avatar_service/pipeline.py
from __future__ import annotations

from . import gemini_client, tripo_client
from .config import Config
from .store import AssetStore, JobStore
from .style import build_prompt, pixelate_png


def _default_deps(cfg: Config) -> dict:
    return {
        "generate_image": lambda prompt, **kw: gemini_client.generate_image(
            prompt, api_key=cfg.gemini_api_key, model=cfg.gemini_image_model),
        "submit": lambda img, **kw: tripo_client.with_retry(
            lambda: tripo_client.submit(img, api_key=cfg.dashscope_api_key,
                                        model=cfg.tripo_model), backoff=2),
        "poll": lambda tid, **kw: tripo_client.poll(tid, api_key=cfg.dashscope_api_key),
        "download": lambda url, **kw: tripo_client.with_retry(
            lambda: tripo_client.download(url), backoff=2),
    }


def _url(cfg: Config, filename: str) -> str:
    base = cfg.asset_base_url.rstrip("/") if cfg.asset_base_url else ""
    return f"{base}/assets/{filename}"


def run_job(job_id, req, cfg, jobs: JobStore, assets: AssetStore, *, deps=None) -> None:
    d = deps or _default_deps(cfg)
    style = req.get("style", "3d")
    try:
        jobs.update(job_id, status="running", progress="generating_image")
        prompt = build_prompt(req["prompt"], style=style, shell=req.get("shell"))
        img = d["generate_image"](prompt)

        if style == "pixel":
            png = pixelate_png(img)
            fn = assets.save(job_id, "png", png)
            jobs.update(job_id, progress="done", status="succeeded",
                        result={"glb_url": None, "image_url": _url(cfg, fn)})
            return

        src_fn = assets.save(job_id, "png", img)
        jobs.update(job_id, progress="converting_3d")
        task_id = d["submit"](img)
        glb_url_up = d["poll"](task_id)
        jobs.update(job_id, progress="downloading")
        glb = d["download"](glb_url_up)
        glb_fn = assets.save(job_id, "glb", glb)
        jobs.update(job_id, progress="done", status="succeeded", result={
            "glb_url": _url(cfg, glb_fn),
            "preview_url": _url(cfg, src_fn),      # source image doubles as preview
            "source_image_url": _url(cfg, src_fn),
        })
    except Exception as e:  # noqa: BLE001 — funnel all step failures to job.error
        jobs.update(job_id, status="failed", error=str(e))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd avatar_service && python -m pytest tests/test_pipeline.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add avatar_service/pipeline.py avatar_service/tests/test_pipeline.py
git commit -m "feat(avatar-service): pipeline orchestrator with progress + error funnel"
```

---

### Task 7: FastAPI app (endpoints + background + static)

**Files:**
- Create: `avatar_service/app.py`
- Test: `avatar_service/tests/test_app.py`

**Interfaces:**
- Consumes: `config.load_config`, `store.{JobStore,AssetStore}`, `pipeline.run_job`.
- Produces: `create_app(cfg: Config | None = None, *, runner=None) -> FastAPI`. `runner(job_id, req, cfg, jobs, assets)` defaults to launching `run_job` in a background thread; tests inject a synchronous runner. Endpoints:
  - `POST /avatars` body `{prompt, style?, shell?}` → `{job_id, status}`; empty prompt → 400.
  - `GET /avatars/{job_id}` → job dict; unknown id → 404.
  - `GET /assets/{file}` → static file from `cfg.asset_dir`.
  - Module-level `app = create_app()` for uvicorn.

- [ ] **Step 1: Write the failing test**

```python
# avatar_service/tests/test_app.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd avatar_service && python -m pytest tests/test_app.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# avatar_service/app.py
from __future__ import annotations

import threading

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Config, load_config
from .pipeline import run_job
from .store import AssetStore, JobStore


class AvatarRequest(BaseModel):
    prompt: str
    style: str = "3d"
    shell: str | None = None


def _thread_runner(job_id, req, cfg, jobs, assets):
    threading.Thread(target=run_job, args=(job_id, req, cfg, jobs, assets), daemon=True).start()


def create_app(cfg: Config | None = None, *, runner=None) -> FastAPI:
    cfg = cfg or load_config()
    jobs = JobStore()
    assets = AssetStore(cfg.asset_dir)
    run = runner or _thread_runner
    app = FastAPI(title="Avatar 3D Service")

    @app.post("/avatars")
    def create_avatar(req: AvatarRequest):
        if not req.prompt.strip():
            raise HTTPException(status_code=400, detail="prompt is required")
        job_id = jobs.create()
        run(job_id, req.model_dump(), cfg, jobs, assets)
        return {"job_id": job_id, "status": "pending"}

    @app.get("/avatars/{job_id}")
    def get_avatar(job_id: str):
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    app.mount("/assets", StaticFiles(directory=str(cfg.asset_dir)), name="assets")
    return app


app = create_app() if __name__ != "__main__" else None
```

Note: the module-level `app = create_app()` calls `load_config()`, which needs a real `.env`; guard so imports in tests (which call `create_app(cfg,...)`) don't fail. Use lazy pattern: replace the last line with

```python
def get_app() -> FastAPI:
    return create_app()
```

and document uvicorn target as `avatar_service.app:get_app` with `--factory`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd avatar_service && python -m pytest tests/test_app.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run full suite**

Run: `cd avatar_service && python -m pytest -v`
Expected: PASS (all tasks' tests green)

- [ ] **Step 6: Commit**

```bash
git add avatar_service/app.py avatar_service/tests/test_app.py
git commit -m "feat(avatar-service): FastAPI app with submit/poll/assets endpoints"
```

---

### Task 8: Real-environment end-to-end validation

**Files:**
- Create: `avatar_service/tests/test_e2e_real.py` (skipped unless `RUN_REAL_E2E=1`)

**Interfaces:**
- Consumes: real `.env` with valid keys, running service. This is the "mock-green ≠ correct" gate from the spec.

- [ ] **Step 1: Write the gated real test**

```python
# avatar_service/tests/test_e2e_real.py
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
    cfg = load_config(".env")  # real keys
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
```

- [ ] **Step 2: Run it for real (manual gate)**

Run: `cd avatar_service && cp ../backend/.env.local .env && RUN_REAL_E2E=1 python -m pytest tests/test_e2e_real.py -v -s`
Expected: PASS — real job reaches `succeeded`, GLB downloads with `glTF` magic header. (Retry once if it hits the known transient SSL flake.)

- [ ] **Step 3: Manual browser check**

Copy the produced GLB into `scripts/webdemo/gallery/` and confirm it loads/rotates in an existing `<model-viewer>` page (serve `scripts/webdemo/` on :8770). This confirms the hosted asset is a real, embeddable 3D model.

- [ ] **Step 4: Commit**

```bash
git add avatar_service/tests/test_e2e_real.py
git commit -m "test(avatar-service): gated real-environment e2e validation"
```

---

### Task 9: Docs + Dockerfile (delivery)

**Files:**
- Create: `avatar_service/README.md`
- Create: `avatar_service/API.md`
- Create: `avatar_service/Dockerfile`
- Create: `avatar_service/.dockerignore`

**Interfaces:**
- Consumes: the finished service.
- Produces: deliverable docs. No code/tests.

- [ ] **Step 1: Write `avatar_service/Dockerfile`**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8800 ASSET_DIR=/app/assets
EXPOSE 8800
CMD ["sh", "-c", "uvicorn avatar_service.app:get_app --factory --host 0.0.0.0 --port ${PORT}"]
```

`.dockerignore`:
```
.env
assets/
tests/
__pycache__/
*.pyc
```

Note: the Docker build context must be the repo root so `avatar_service` is importable as a package; document `docker build -f avatar_service/Dockerfile -t avatar-3d-service .` in README.

- [ ] **Step 2: Write `avatar_service/README.md`**

Cover, in Chinese: what the service is; install (`python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`); configure (`cp .env.example .env`, fill `GEMINI_API_KEY` + `DASHSCOPE_API_KEY`, note DashScope Tripo model must be activated once in bailian console); run locally (`uvicorn avatar_service.app:get_app --factory --port 8800` from repo root); run via Docker (`docker build -f avatar_service/Dockerfile -t avatar-3d-service . && docker run -p 8800:8800 --env-file avatar_service/.env avatar-3d-service`); run tests (`python -m pytest avatar_service`); cost note (~$0.039/Gemini image + ~¥0.5-1/Tripo model); known limitations (in-memory jobs lost on restart; single-instance; transient SSL retries may re-bill).

- [ ] **Step 3: Write `avatar_service/API.md`**

Document the 3 endpoints with request/response JSON, a `curl` example for POST + GET, a JS `fetch` polling example (submit → poll every 4s → embed `glb_url` in `<model-viewer>`), the `style`/`shell` parameter values, and the result field differences between `3d` and `pixel`. Include the exact `<model-viewer>` embed snippet consuming `glb_url`.

- [ ] **Step 4: Commit**

```bash
git add avatar_service/README.md avatar_service/API.md avatar_service/Dockerfile avatar_service/.dockerignore
git commit -m "docs(avatar-service): README, API guide, Dockerfile"
```

---

## Self-Review

**1. Spec coverage:**
- §2/§3 定位/技术栈/自包含/依赖 → Task 1 ✓
- §4.1 POST /avatars → Task 7 ✓; §4.2 GET poll → Task 7 ✓; §4.3 GET /assets → Task 7 ✓; §4.4 internal pipeline (image→3d→download→host) → Tasks 2,3,6 ✓
- §5 error handling (funnel to job.error, retry, 400 empty prompt) → Task 6 (funnel), Task 3 (retry), Task 7 (400) ✓
- §6 config from .env + .env.example → Task 1 ✓
- §7 deliverables (code, README, API.md, .env.example, Dockerfile, requirements) → Tasks 1,9 ✓
- §8 test strategy (mocked units + gated real e2e) → all tasks TDD + Task 8 ✓
- §9 risks documented → Task 9 README ✓
- pixel-vs-3d result shape (spec §4.2 note) → Task 6 (pixel branch) + Task 9 API.md ✓

**2. Placeholder scan:** No TBD/TODO; every code step has full code. README/API.md content (Task 9) is specified by required-contents lists, not left vague. ✓

**3. Type consistency:** `generate_image`, `submit`, `poll`, `download`, `with_retry`, `JobStore.{create,get,update}`, `AssetStore.{save,path}`, `build_prompt`, `pixelate_png`, `run_job`, `create_app` signatures are consistent between defining task and consuming task (Task 6 deps keys match Task 2/3 function names; Task 7 runner signature matches Task 6 `run_job`). ✓
