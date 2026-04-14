import base64
import json
import logging
import time
from io import BytesIO

import cv2
import httpx
import numpy as np
from PIL import Image
from pydantic import BaseModel
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# TODO 需要兼容https， 使用self.client.request的方式

# todo 。传入视频 URL 时：Qwen2.5-VL 系列模型支持传入的视频大小不超过1 GB，其他模型不超过150MB。
# todo 。传入本地文件时：使用 OpenAI SDK 方式经 Base64编码后的视频需小于 10MB；使用 DashScope SDK 方式，视频本身需小于 100MB
# todo 。可以考虑使用rsync同步视频，再调用API

class QwenVLAPIControllerConfig(BaseModel):
    host: str = "localhost"
    port: int | None = 3001
    model_name: str = "Qwen/Qwen2.5-VL-32B-Instruct"
    video_extract_fps: int = 1
    video_max_frame_count: int = 60

    class Config:
        extra = "ignore"


class QwenVLAPIController:
    def __init__(
        self,
        config: QwenVLAPIControllerConfig,
    ) -> None:
        self.host = config.host
        self.port = config.port
        self.model_name = config.model_name
        self.video_extract_fps = config.video_extract_fps
        self.video_max_frame_count = config.video_max_frame_count
    
    @staticmethod
    def _transform_image_base64(image: np.ndarray) -> str:
        """
        将numpy数组转换为base64字符串
        """
        # 将BGR转换为RGB
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(image_rgb)
        output_buffer = BytesIO()
        pil_image.save(output_buffer, format="jpeg")
        return base64.b64encode(output_buffer.getvalue()).decode("utf-8")
    
    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(
            multiplier=1,
            min=2,
            max=10
        ),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    async def _inference_with_api(self, messages: list[dict], video_kwargs: dict | None = None) -> str:
        """
        使用VLLM API推理。

        Args:
            messages: 消息列表
            video_kwargs: 视频相关参数

        Returns:
            str: 推理结果

        Raises:
            httpx.HTTPError: API请求异常
            json.JSONDecodeError: JSON解析异常
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer xxxx",
            "X-HW-AppKey": "9DtHeTHyZeU34+#UzTHBW9k!hJW4TCx4%H.%IGj@rMNyNEY0iJzVgGlEWEu!Lu20",
            "X-HW-ID": "96ac58bb-0f9e-4e80-abdb-c31b59bffc11",
            "X-Sdk-Content-Sha256": "UNSIGNED-PAYLOAD",
        }
        if video_kwargs:
            payload = {
                "model": self.model_name,
                "messages": messages,
                "extra_body": {
                    "mm_processor_kwargs": video_kwargs
                }
            }
        else:
            payload = {
                "model": self.model_name,
                "messages": messages,
                "stream": False,
                "temperature": 0.1,
                "top_p": 0.95,
            }

        try:
            # with self._api_lock:  # 使用上下文管理器确保锁的正确获取和释放
            start_time = time.time()
            if self.port in (None, 0):
                base_url = f"http://{self.host}"
            else:
                base_url = f"http://{self.host}:{self.port}"
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{base_url}/v1/chat/completions", # noqa
                    headers=headers,
                    json=payload,
                    timeout=720.0  # 添加超时设置
                )
            end_time = time.time()
            logging.info(f"VLLM API推理时间: {end_time - start_time} 秒")
            response.raise_for_status()  # 检查HTTP状态码

            # 记录原始响应
            logging.debug(f"Raw API response: {response.text}")

            result = response.json()
            if not result:
                logging.error("Empty response from API")
                raise ValueError("Empty response from API")

            content = result.get("choices", [{}])[0].get("message", {}).get("content")
            if content:
                logging.info(f"VLLM API推理成功: {content}")
                return content
            logging.error(f"VLLM API返回格式异常: {result}")
            raise ValueError(f"VLLM API返回格式异常: {result}")
        except httpx.HTTPError as e:
            logging.error(f"API请求异常: {str(e)}")
            raise e
        except json.JSONDecodeError as e:
            logging.error(f"JSON解析异常: {str(e)}, 原始响应: {response.text}")
            raise e
        except Exception as e:
            logging.error(f"未预期的异常: {str(e)}")
            raise e
            
    async def inference_image_base64(self, prompt: str, images:list[np.ndarray]) -> str:
        start_time = time.time()
        base64_frames = [self._transform_image_base64(image) for image in images]
        messages = [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            },
            {
                "role": "user",
                "content": [
                ]
            }
        ]
        for base64_frame in base64_frames:
            messages[1]["content"].append({
                "type": "image_url",
                "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_frame}"
                    }
                })
        result = await self._inference_with_api(messages)
        end_time = time.time()
        logging.info(f"推理执行时间: {end_time - start_time} 秒")
        return result
