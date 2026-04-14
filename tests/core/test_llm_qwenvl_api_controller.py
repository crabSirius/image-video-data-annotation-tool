from __future__ import annotations

import asyncio
import base64
import json
from io import BytesIO

import httpx
import numpy as np
import pytest
from PIL import Image

import src.core.llm_qwenvl_api_controller as controller_module
from src.core.llm_qwenvl_api_controller import QwenVLAPIController, QwenVLAPIControllerConfig


class FakeResponse:
    def __init__(
        self,
        *,
        payload: dict[str, object] | None = None,
        text: str = "",
        http_error: httpx.HTTPError | None = None,
        json_error: json.JSONDecodeError | None = None,
    ) -> None:
        self._payload = payload
        self.text = text
        self._http_error = http_error
        self._json_error = json_error

    def raise_for_status(self) -> None:
        if self._http_error is not None:
            raise self._http_error

    def json(self) -> dict[str, object]:
        if self._json_error is not None:
            raise self._json_error
        return self._payload or {}


class FakeAsyncClient:
    def __init__(self, response: FakeResponse, captured: dict[str, object]) -> None:
        self._response = response
        self._captured = captured

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
        timeout: float,
    ) -> FakeResponse:
        self._captured["url"] = url
        self._captured["headers"] = headers
        self._captured["json"] = json
        self._captured["timeout"] = timeout
        return self._response


def make_controller(**overrides: object) -> QwenVLAPIController:
    config = QwenVLAPIControllerConfig(**overrides)
    return QwenVLAPIController(config)


def run_inference_without_retry(
    controller: QwenVLAPIController,
    messages: list[dict[str, object]],
    video_kwargs: dict[str, object] | None = None,
) -> str:
    return asyncio.run(
        controller._inference_with_api.__wrapped__(controller, messages, video_kwargs)
    )


def test_controller_uses_values_from_config() -> None:
    controller = make_controller(
        host="api.internal",
        port=9000,
        model_name="Qwen/test-model",
        video_extract_fps=3,
        video_max_frame_count=24,
    )

    assert controller.host == "api.internal"
    assert controller.port == 9000
    assert controller.model_name == "Qwen/test-model"
    assert controller.video_extract_fps == 3
    assert controller.video_max_frame_count == 24


def test_transform_image_base64_converts_bgr_input_to_rgb_jpeg() -> None:
    controller = make_controller()
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    image[:, :, 0] = 255

    encoded = controller._transform_image_base64(image)
    decoded = np.array(Image.open(BytesIO(base64.b64decode(encoded))))

    assert decoded.shape == (32, 32, 3)
    assert decoded[:, :, 2].mean() > 200
    assert decoded[:, :, 0].mean() < 40
    assert decoded[:, :, 1].mean() < 40


def test_inference_with_api_posts_expected_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = make_controller(host="api.internal", port=8080, model_name="model-x")
    captured: dict[str, object] = {}
    response = FakeResponse(
        payload={"choices": [{"message": {"content": "ok"}}]},
        text='{"choices":[{"message":{"content":"ok"}}]}',
    )

    monkeypatch.setattr(
        controller_module.httpx,
        "AsyncClient",
        lambda: FakeAsyncClient(response, captured),
    )

    result = run_inference_without_retry(
        controller,
        messages=[{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
    )

    assert result == "ok"
    assert captured["url"] == "http://api.internal:8080/v1/chat/completions"
    assert captured["timeout"] == 720.0
    assert captured["json"] == {
        "model": "model-x",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
        "stream": False,
        "temperature": 0.1,
        "top_p": 0.95,
    }


def test_inference_with_api_uses_host_without_port_for_video_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = make_controller(host="api.internal", port=None, model_name="model-x")
    captured: dict[str, object] = {}
    response = FakeResponse(
        payload={"choices": [{"message": {"content": "video-ok"}}]},
        text='{"choices":[{"message":{"content":"video-ok"}}]}',
    )

    monkeypatch.setattr(
        controller_module.httpx,
        "AsyncClient",
        lambda: FakeAsyncClient(response, captured),
    )

    result = run_inference_without_retry(
        controller,
        messages=[{"role": "user", "content": []}],
        video_kwargs={"num_frames": 8},
    )

    assert result == "video-ok"
    assert captured["url"] == "http://api.internal/v1/chat/completions"
    assert captured["json"] == {
        "model": "model-x",
        "messages": [{"role": "user", "content": []}],
        "extra_body": {"mm_processor_kwargs": {"num_frames": 8}},
    }


def test_inference_with_api_raises_for_empty_response(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = make_controller()

    monkeypatch.setattr(
        controller_module.httpx,
        "AsyncClient",
        lambda: FakeAsyncClient(FakeResponse(payload={}, text="{}"), {}),
    )

    with pytest.raises(ValueError, match="Empty response from API"):
        run_inference_without_retry(controller, messages=[{"role": "user", "content": []}])


def test_inference_with_api_propagates_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = make_controller()
    request = httpx.Request("POST", "http://localhost/v1/chat/completions")
    response = httpx.Response(500, request=request)
    http_error = httpx.HTTPStatusError("boom", request=request, response=response)

    monkeypatch.setattr(
        controller_module.httpx,
        "AsyncClient",
        lambda: FakeAsyncClient(FakeResponse(http_error=http_error), {}),
    )

    with pytest.raises(httpx.HTTPStatusError, match="boom"):
        run_inference_without_retry(controller, messages=[{"role": "user", "content": []}])


def test_inference_with_api_propagates_json_decode_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = make_controller()
    json_error = json.JSONDecodeError("Expecting value", "not-json", 0)

    monkeypatch.setattr(
        controller_module.httpx,
        "AsyncClient",
        lambda: FakeAsyncClient(FakeResponse(text="not-json", json_error=json_error), {}),
    )

    with pytest.raises(json.JSONDecodeError, match="Expecting value"):
        run_inference_without_retry(controller, messages=[{"role": "user", "content": []}])


def test_inference_image_base64_builds_messages_and_returns_api_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = make_controller()
    captured: dict[str, object] = {}

    def fake_transform(image: np.ndarray) -> str:
        return f"frame-{int(image.sum())}"

    async def fake_inference(messages: list[dict[str, object]]) -> str:
        captured["messages"] = messages
        return "annotated"

    monkeypatch.setattr(controller, "_transform_image_base64", fake_transform)
    monkeypatch.setattr(controller, "_inference_with_api", fake_inference)

    images = [
        np.ones((1, 1, 3), dtype=np.uint8),
        np.full((1, 1, 3), fill_value=2, dtype=np.uint8),
    ]

    result = asyncio.run(controller.inference_image_base64("describe image", images))

    assert result == "annotated"
    assert captured["messages"] == [
        {
            "role": "system",
            "content": [{"type": "text", "text": "describe image"}],
        },
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,frame-3"}},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,frame-6"}},
            ],
        },
    ]
