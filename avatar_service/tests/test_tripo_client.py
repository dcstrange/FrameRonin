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
