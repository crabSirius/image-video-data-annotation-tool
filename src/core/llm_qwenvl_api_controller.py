from __future__ import annotations

import base64
import json
import time
from io import BytesIO
from typing import Any

import cv2
import httpx
import numpy as np
from loguru import logger
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


def _log_before_retry(retry_state: RetryCallState) -> None:
    exception = retry_state.outcome.exception() if retry_state.outcome is not None else None
    sleep_seconds = 0.0 if retry_state.next_action is None else retry_state.next_action.sleep
    logger.warning(
        "VLM API 调用失败，准备重试: attempt={} next_sleep={:.2f}s error={}",
        retry_state.attempt_number,
        sleep_seconds,
        exception,
    )


class QwenVLAPIControllerConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scheme: str = "http"
    host: str = "localhost"
    port: int | None = 3001
    api_path: str = "/v1/chat/completions"
    model_name: str = "Qwen/Qwen2.5-VL-32B-Instruct"
    api_key: str | None = None
    request_headers: dict[str, str] = Field(default_factory=dict)
    request_timeout_seconds: float = 720.0
    video_extract_fps: int = 1
    video_max_frame_count: int = 60
    temperature: float = 0.1
    top_p: float = 0.95


class QwenVLAPIController:
    def __init__(self, config: QwenVLAPIControllerConfig) -> None:
        self.scheme = config.scheme.lower()
        self.host = config.host
        self.port = config.port
        self.api_path = config.api_path
        self.model_name = config.model_name
        self.api_key = config.api_key
        self.request_headers = dict(config.request_headers)
        self.request_timeout_seconds = config.request_timeout_seconds
        self.video_extract_fps = config.video_extract_fps
        self.video_max_frame_count = config.video_max_frame_count
        self.temperature = config.temperature
        self.top_p = config.top_p

    @staticmethod
    def _transform_image_base64(image: np.ndarray) -> str:
        """将 numpy 图像转换为 base64 JPEG。"""
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(image_rgb)
        output_buffer = BytesIO()
        pil_image.save(output_buffer, format="JPEG")
        return base64.b64encode(output_buffer.getvalue()).decode("utf-8")

    def _build_base_url(self) -> str:
        if self.port in (None, 0):
            return f"{self.scheme}://{self.host}"
        return f"{self.scheme}://{self.host}:{self.port}"

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        headers.update(self.request_headers)
        if self.api_key and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        video_kwargs: dict[str, object] | None,
    ) -> dict[str, Any]:
        if video_kwargs:
            return {
                "model": self.model_name,
                "messages": messages,
                "extra_body": {"mm_processor_kwargs": video_kwargs},
            }

        return {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "temperature": self.temperature,
            "top_p": self.top_p,
        }

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        before_sleep=_log_before_retry,
    )
    async def _inference_with_api(
        self,
        messages: list[dict[str, Any]],
        video_kwargs: dict[str, object] | None = None,
    ) -> str:
        """调用兼容 OpenAI Chat Completions 的多模态接口。"""
        payload = self._build_payload(messages, video_kwargs)
        response: httpx.Response | None = None

        try:
            start_time = time.time()
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self._build_base_url()}{self.api_path}",
                    headers=self._build_headers(),
                    json=payload,
                    timeout=self.request_timeout_seconds,
                )
            elapsed = time.time() - start_time
            logger.info("VLM API 推理时间: {:.2f} 秒", elapsed)
            response.raise_for_status()

            result = response.json()
            if not result:
                raise ValueError("Empty response from API")

            content = result.get("choices", [{}])[0].get("message", {}).get("content")
            if content:
                logger.info("VLM API 推理成功")
                return str(content)

            raise ValueError(f"VLM API 返回格式异常: {result}")
        except httpx.HTTPError as exc:
            logger.error("API 请求异常: {}", exc)
            raise
        except json.JSONDecodeError as exc:
            raw_response = "" if response is None else response.text
            logger.error("JSON 解析异常: {}, 原始响应: {}", exc, raw_response)
            raise
        except Exception as exc:
            logger.error("未预期的异常: {}", exc)
            raise

    async def inference_image_base64(self, prompt: str, images: list[np.ndarray]) -> str:
        start_time = time.time()
        base64_frames = [self._transform_image_base64(image) for image in images]
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": [{"type": "text", "text": prompt}],
            },
            {
                "role": "user",
                "content": [],
            },
        ]
        for base64_frame in base64_frames:
            messages[1]["content"].append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{base64_frame}"},
                }
            )
        result = await self._inference_with_api(messages)
        elapsed = time.time() - start_time
        logger.info("推理执行时间: {:.2f} 秒", elapsed)
        return result
