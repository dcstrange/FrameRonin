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
        except exceptions as e:
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
