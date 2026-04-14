from __future__ import annotations

import io
import json
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import rasterio
from PIL import Image

from src.tasks.orthomosaic_tree_damage import read_window_image


def load_dashboard_payload(output_dir: str | Path) -> dict[str, object]:
    output_dir = Path(output_dir)
    payload_path = output_dir / "dashboard" / "dashboard_data.json"
    return json.loads(payload_path.read_text(encoding="utf-8"))


def render_region_preview(
    output_dir: str | Path,
    *,
    region_id: str,
    max_size: int = 1400,
) -> bytes:
    payload = load_dashboard_payload(output_dir)
    regions = payload.get("regions")
    if not isinstance(regions, list):
        raise ValueError("dashboard_data.json 缺少 regions 字段")

    region = next(
        (
            item
            for item in regions
            if isinstance(item, dict) and str(item.get("region_id")) == region_id
        ),
        None,
    )
    if region is None:
        raise ValueError(f"未找到区域: {region_id}")

    orthomosaic_path = Path(str(payload["orthomosaic_path"]))
    preview_max_size = max(128, int(max_size))
    with rasterio.open(orthomosaic_path) as dataset:
        image = read_window_image(
            dataset=dataset,
            row_off=int(region["row_off"]),
            col_off=int(region["col_off"]),
            width=int(region["width"]),
            height=int(region["height"]),
            max_size=preview_max_size,
        )

    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


class OrthomosaicDashboardRequestHandler(SimpleHTTPRequestHandler):
    def __init__(
        self,
        *args: object,
        output_dir: Path,
        dashboard_dir: Path,
        **kwargs: object,
    ) -> None:
        self._output_dir = output_dir
        super().__init__(*args, directory=str(dashboard_dir), **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/region-preview":
            self._handle_region_preview(parsed.query)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        else:
            self.path = parsed.path
        super().do_GET()

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _handle_region_preview(self, query: str) -> None:
        params = parse_qs(query)
        region_id = params.get("region_id", [""])[0].strip()
        if not region_id:
            self.send_error(HTTPStatus.BAD_REQUEST, "missing region_id")
            return

        max_size_raw = params.get("max_size", ["1400"])[0]
        try:
            max_size = int(max_size_raw)
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "invalid max_size")
            return

        try:
            image_bytes = render_region_preview(
                self._output_dir,
                region_id=region_id,
                max_size=max_size,
            )
        except ValueError as exc:
            self.send_error(HTTPStatus.NOT_FOUND, str(exc))
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(image_bytes)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(image_bytes)


def serve_dashboard(output_dir: str | Path, *, host: str, port: int) -> None:
    output_dir = Path(output_dir)
    dashboard_dir = output_dir / "dashboard"
    handler = partial(
        OrthomosaicDashboardRequestHandler,
        output_dir=output_dir,
        dashboard_dir=dashboard_dir,
    )
    with ThreadingHTTPServer((host, port), handler) as server:
        print(f"Dashboard running at http://{host}:{port}")
        server.serve_forever()
