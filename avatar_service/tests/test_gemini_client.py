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
