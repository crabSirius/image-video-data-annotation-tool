from __future__ import annotations

# ruff: noqa: E402, I001

import argparse
import io
import json
import logging
import sys
from functools import lru_cache
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import numpy as np
import rasterio
from PIL import Image
from rasterio.io import DatasetReader

from src.tasks.orthomosaic_tree_damage import read_window_image

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_REGION_INDEX: dict[str, dict[str, int]] = {}
_ORTHOMOSAIC_PATH: str = ""
_MAX_REGION_IMAGE_SIZE = 4096


def _resolve_dashboard_dir(output_dir: Path) -> Path:
    """定位包含 dashboard_data.json 的目录。

    优先查找 output_dir 本身，再向下查找 dashboard/ 子目录。
    """
    if (output_dir / "dashboard_data.json").exists():
        return output_dir
    sub = output_dir / "dashboard"
    if (sub / "dashboard_data.json").exists():
        return sub
    logger.error(
        "dashboard_data.json 不存在于 %s 或其 dashboard/ 子目录中",
        output_dir,
    )
    sys.exit(1)


def _load_dashboard_data(dashboard_dir: Path) -> dict[str, Any]:
    data_path = dashboard_dir / "dashboard_data.json"
    with data_path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _build_region_index(dashboard_data: dict[str, Any]) -> dict[str, dict[str, int]]:
    index: dict[str, dict[str, int]] = {}
    for region in dashboard_data.get("regions", []):
        rid = str(region["region_id"])
        index[rid] = {
            "row_off": int(region["row_off"]),
            "col_off": int(region["col_off"]),
            "width": int(region["width"]),
            "height": int(region["height"]),
        }
    return index


@lru_cache(maxsize=4)
def _open_dataset(path: str) -> DatasetReader:
    return rasterio.open(path)


def _render_region_jpeg(region_id: str, max_size: int | None) -> bytes | None:
    region = _REGION_INDEX.get(region_id)
    if region is None:
        return None

    if max_size is not None:
        max_size = min(max_size, _MAX_REGION_IMAGE_SIZE)

    dataset = _open_dataset(_ORTHOMOSAIC_PATH)
    image = read_window_image(
        dataset=dataset,
        row_off=region["row_off"],
        col_off=region["col_off"],
        width=region["width"],
        height=region["height"],
        max_size=max_size,
    )

    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


class DashboardHandler(SimpleHTTPRequestHandler):
    """支持区域原图 API 的静态文件服务。"""

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/region-image":
            self._handle_region_image(parsed.query)
            return
        super().do_GET()

    def _handle_region_image(self, query_string: str) -> None:
        params = parse_qs(query_string)
        region_id = (params.get("region_id") or [None])[0]
        if not region_id:
            self._send_json_error(HTTPStatus.BAD_REQUEST, "缺少 region_id 参数")
            return

        raw_max_size = (params.get("max_size") or [None])[0]
        max_size: int | None = None
        if raw_max_size is not None:
            try:
                max_size = int(raw_max_size)
                if max_size <= 0:
                    raise ValueError
            except ValueError:
                self._send_json_error(HTTPStatus.BAD_REQUEST, "max_size 必须为正整数")
                return

        try:
            jpeg_bytes = _render_region_jpeg(region_id, max_size)
        except Exception:
            logger.exception("读取区域图像失败: %s", region_id)
            self._send_json_error(HTTPStatus.INTERNAL_SERVER_ERROR, "读取区域图像失败")
            return

        if jpeg_bytes is None:
            self._send_json_error(HTTPStatus.NOT_FOUND, f"未找到区域: {region_id}")
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(jpeg_bytes)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(jpeg_bytes)

    def _send_json_error(self, status: HTTPStatus, message: str) -> None:
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        logger.info(format, *args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="启动 Orthomosaic Dashboard 本地查看服务")
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="pipeline 输出目录（包含 index.html 和 dashboard_data.json）",
    )
    parser.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0")
    parser.add_argument("--port", type=int, default=8765, help="监听端口，默认 8765")
    return parser


def main() -> None:
    global _REGION_INDEX, _ORTHOMOSAIC_PATH  # noqa: PLW0603

    args = build_parser().parse_args()
    output_dir: Path = args.output_dir.resolve()
    dashboard_dir = _resolve_dashboard_dir(output_dir)

    dashboard_data = _load_dashboard_data(dashboard_dir)
    _REGION_INDEX = _build_region_index(dashboard_data)

    ortho_raw = str(dashboard_data.get("orthomosaic_path", ""))
    ortho_path = Path(ortho_raw)
    if not ortho_path.is_absolute():
        ortho_path = (_PROJECT_ROOT / ortho_path).resolve()
    _ORTHOMOSAIC_PATH = str(ortho_path)

    if not ortho_path.exists():
        logger.error("正射图文件不存在: %s", _ORTHOMOSAIC_PATH)
        sys.exit(1)

    logger.info("Dashboard 目录: %s", dashboard_dir)
    logger.info("已加载 %d 个区域索引", len(_REGION_INDEX))
    logger.info("正射图路径: %s", _ORTHOMOSAIC_PATH)

    import os
    os.chdir(dashboard_dir)

    server = HTTPServer((args.host, args.port), DashboardHandler)
    url = f"http://localhost:{args.port}"
    logger.info("Dashboard 服务已启动: %s", url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("正在关闭服务...")
        server.shutdown()


if __name__ == "__main__":
    main()
