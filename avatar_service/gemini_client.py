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
