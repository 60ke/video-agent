from __future__ import annotations

import base64
from pathlib import Path

import httpx

from video_agent.ai import gpt_image


class _Client:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, *_args, **_kwargs) -> httpx.Response:
        response = self.responses[self.calls]
        self.calls += 1
        return response


def _response(status: int, payload: dict) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        request=httpx.Request("POST", "https://example.invalid/v1/images/edits"),
    )


def test_edit_image_retries_rate_limit_then_succeeds(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    provider = gpt_image.ImageProvider(
        name="test",
        base_url="https://example.invalid",
        api_key="secret",
        model="gpt-image-test",
        edit_path="/v1/images/edits",
        quality="low",
        size="1024x1792",
        timeout_seconds=10,
        weight=1,
        max_retries=2,
    )
    expected = b"generated"
    client = _Client(
        [
            _response(429, {"error": "rate limited"}),
            _response(200, {"id": "img_1", "data": [{"b64_json": base64.b64encode(expected).decode()}]}),
        ]
    )
    monkeypatch.setattr(gpt_image, "_providers", lambda _root: [provider])
    monkeypatch.setattr(gpt_image.httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(gpt_image.time, "sleep", lambda _seconds: None)

    result = gpt_image.edit_image(tmp_path, source, "keep content")

    assert result.content == expected
    assert result.response_id == "img_1"
    assert client.calls == 2
