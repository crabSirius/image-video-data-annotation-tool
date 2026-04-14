from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

import numpy as np
import rasterio
from loguru import logger
from PIL import Image
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.warp import transform as warp_transform
from rasterio.windows import Window

from src.core.llm_qwenvl_api_controller import QwenVLAPIController
from src.utils.geometry import clip_box, deduplicate_detections
from src.utils.json_io import (
    append_jsonl,
    load_latest_jsonl_records,
    write_json,
    write_jsonl,
)
from src.utils.llm import parse_response_text
from src.visualization.orthomosaic_dashboard import build_dashboard_payload, write_dashboard

DamageLabel = Literal["fallen_tree", "diseased_tree"]
TreeRegionMode = Literal["heuristic", "qwen_vl"]

DONE_TILE_STATUSES = {"done", "skipped_low_signal"}
RESOLVED_TILE_STATUSES = DONE_TILE_STATUSES | {"pending_model"}

LABEL_ALIASES: dict[str, DamageLabel] = {
    "fallen_tree": "fallen_tree",
    "fall_tree": "fallen_tree",
    "tree_fall": "fallen_tree",
    "tree_fallen": "fallen_tree",
    "lodged_tree": "fallen_tree",
    "倒伏树木": "fallen_tree",
    "树木倒伏": "fallen_tree",
    "倒木": "fallen_tree",
    "倒伏": "fallen_tree",
    "diseased_tree": "diseased_tree",
    "tree_disease": "diseased_tree",
    "dead_tree": "diseased_tree",
    "declining_tree": "diseased_tree",
    "病害树木": "diseased_tree",
    "树木病害": "diseased_tree",
    "病树": "diseased_tree",
    "枯死木": "diseased_tree",
    "枯黄树木": "diseased_tree",
}


@dataclass(slots=True, frozen=True)
class OrthomosaicTreeDamageConfig:
    orthomosaic_path: Path
    output_dir: Path
    region_size: int = 4096
    region_overlap: int = 0
    region_preview_size: int = 512
    tree_region_mode: TreeRegionMode = "heuristic"
    min_tree_region_vegetation_fraction: float = 0.08
    min_tree_region_score: float = 0.18
    tile_size: int = 1024
    overlap: int = 128
    max_regions: int | None = None
    max_tiles_per_region: int | None = None
    min_vegetation_fraction: float = 0.08
    min_candidate_score: float = 0.14
    min_detection_score: float = 0.5
    labels: tuple[DamageLabel, ...] = ("fallen_tree", "diseased_tree")
    label_studio_image_root_url: str | None = None
    overview_max_size: int = 1800
    dashboard_title: str = "Orthomosaic Tree Damage Dashboard"
    dashboard_refresh_interval_regions: int = 1

    def __post_init__(self) -> None:
        if self.region_size <= 0:
            raise ValueError("region_size 必须大于 0")
        if self.region_overlap < 0:
            raise ValueError("region_overlap 不能小于 0")
        if self.region_overlap >= self.region_size:
            raise ValueError("region_overlap 必须小于 region_size")
        if self.region_preview_size <= 0:
            raise ValueError("region_preview_size 必须大于 0")
        if self.tile_size <= 0:
            raise ValueError("tile_size 必须大于 0")
        if self.overlap < 0:
            raise ValueError("overlap 不能小于 0")
        if self.overlap >= self.tile_size:
            raise ValueError("overlap 必须小于 tile_size")
        if self.max_regions is not None and self.max_regions <= 0:
            raise ValueError("max_regions 必须为正整数或 None")
        if self.max_tiles_per_region is not None and self.max_tiles_per_region <= 0:
            raise ValueError("max_tiles_per_region 必须为正整数或 None")
        if self.tree_region_mode not in {"heuristic", "qwen_vl"}:
            raise ValueError("tree_region_mode 仅支持 heuristic 或 qwen_vl")
        if self.dashboard_refresh_interval_regions <= 0:
            raise ValueError("dashboard_refresh_interval_regions 必须大于 0")


@dataclass(slots=True, frozen=True)
class RegionCandidate:
    region_id: str
    row_off: int
    col_off: int
    width: int
    height: int

    def to_dict(self) -> dict[str, object]:
        return {
            "region_id": self.region_id,
            "row_off": self.row_off,
            "col_off": self.col_off,
            "width": self.width,
            "height": self.height,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> RegionCandidate:
        return cls(
            region_id=str(payload["region_id"]),
            row_off=int(payload["row_off"]),
            col_off=int(payload["col_off"]),
            width=int(payload["width"]),
            height=int(payload["height"]),
        )


@dataclass(slots=True, frozen=True)
class TreeRegionResult:
    region_id: str
    row_off: int
    col_off: int
    width: int
    height: int
    method: str
    has_tree: bool
    score: float
    vegetation_fraction: float
    texture_score: float
    tree_coverage: float | None
    reason: str
    processed_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "region_id": self.region_id,
            "row_off": self.row_off,
            "col_off": self.col_off,
            "width": self.width,
            "height": self.height,
            "method": self.method,
            "has_tree": self.has_tree,
            "score": round(self.score, 6),
            "vegetation_fraction": round(self.vegetation_fraction, 6),
            "texture_score": round(self.texture_score, 6),
            "tree_coverage": None if self.tree_coverage is None else round(self.tree_coverage, 6),
            "reason": self.reason,
            "processed_at": self.processed_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> TreeRegionResult:
        tree_coverage = payload.get("tree_coverage")
        return cls(
            region_id=str(payload["region_id"]),
            row_off=int(payload["row_off"]),
            col_off=int(payload["col_off"]),
            width=int(payload["width"]),
            height=int(payload["height"]),
            method=str(payload["method"]),
            has_tree=bool(payload["has_tree"]),
            score=float(payload["score"]),
            vegetation_fraction=float(payload["vegetation_fraction"]),
            texture_score=float(payload["texture_score"]),
            tree_coverage=None if tree_coverage is None else float(tree_coverage),
            reason=str(payload.get("reason", "")),
            processed_at=str(payload.get("processed_at", "")),
        )


@dataclass(slots=True, frozen=True)
class RegionState:
    region_id: str
    row_off: int
    col_off: int
    width: int
    height: int
    tree_stage_status: str
    tree_presence: bool | None
    tree_method: str | None
    tree_score: float | None
    tree_reason: str
    vegetation_fraction: float | None
    texture_score: float | None
    damage_stage_status: str
    damage_tile_total: int
    damage_tile_prepared: int
    damage_tile_processed: int
    damage_tile_pending_model: int
    detection_count: int
    dashboard_status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "region_id": self.region_id,
            "row_off": self.row_off,
            "col_off": self.col_off,
            "width": self.width,
            "height": self.height,
            "tree_stage_status": self.tree_stage_status,
            "tree_presence": self.tree_presence,
            "tree_method": self.tree_method,
            "tree_score": self.tree_score,
            "tree_reason": self.tree_reason,
            "vegetation_fraction": self.vegetation_fraction,
            "texture_score": self.texture_score,
            "damage_stage_status": self.damage_stage_status,
            "damage_tile_total": self.damage_tile_total,
            "damage_tile_prepared": self.damage_tile_prepared,
            "damage_tile_processed": self.damage_tile_processed,
            "damage_tile_pending_model": self.damage_tile_pending_model,
            "detection_count": self.detection_count,
            "dashboard_status": self.dashboard_status,
        }


@dataclass(slots=True, frozen=True)
class TileCandidate:
    tile_id: str
    region_id: str
    row_off: int
    col_off: int
    width: int
    height: int
    vegetation_fraction: float
    texture_score: float
    candidate_score: float

    def to_dict(self) -> dict[str, object]:
        return {
            "tile_id": self.tile_id,
            "region_id": self.region_id,
            "row_off": self.row_off,
            "col_off": self.col_off,
            "width": self.width,
            "height": self.height,
            "vegetation_fraction": round(self.vegetation_fraction, 6),
            "texture_score": round(self.texture_score, 6),
            "candidate_score": round(self.candidate_score, 6),
        }


@dataclass(slots=True, frozen=True)
class TileDetection:
    label: DamageLabel
    score: float
    reason: str
    tile_px_bbox: tuple[float, float, float, float]


@dataclass(slots=True, frozen=True)
class ProjectedDetection:
    tile_id: str
    region_id: str
    label: DamageLabel
    score: float
    reason: str
    tile_px_bbox: tuple[float, float, float, float]
    orig_px_bbox: tuple[float, float, float, float]
    source_crs: str | None
    source_crs_polygon: tuple[tuple[float, float], ...] | None
    wgs84_polygon: tuple[tuple[float, float], ...] | None

    def to_dict(self) -> dict[str, object]:
        return {
            "tile_id": self.tile_id,
            "region_id": self.region_id,
            "label": self.label,
            "score": round(self.score, 6),
            "reason": self.reason,
            "tile_px_bbox": list(self.tile_px_bbox),
            "orig_px_bbox": list(self.orig_px_bbox),
            "source_crs": self.source_crs,
            "source_crs_polygon": self.source_crs_polygon,
            "wgs84_polygon": self.wgs84_polygon,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> ProjectedDetection:
        return cls(
            tile_id=str(payload["tile_id"]),
            region_id=str(payload["region_id"]),
            label=_normalize_label(payload["label"]) or "fallen_tree",
            score=float(payload["score"]),
            reason=str(payload.get("reason", "")),
            tile_px_bbox=_coerce_bbox(payload["tile_px_bbox"]) or (0.0, 0.0, 0.0, 0.0),
            orig_px_bbox=_coerce_bbox(payload["orig_px_bbox"]) or (0.0, 0.0, 0.0, 0.0),
            source_crs=None if payload.get("source_crs") is None else str(payload["source_crs"]),
            source_crs_polygon=_coerce_polygon(payload.get("source_crs_polygon")),
            wgs84_polygon=_coerce_polygon(payload.get("wgs84_polygon")),
        )


@dataclass(slots=True, frozen=True)
class DamageTileResult:
    tile_id: str
    region_id: str
    row_off: int
    col_off: int
    width: int
    height: int
    vegetation_fraction: float
    texture_score: float
    candidate_score: float
    status: str
    image_path: str | None
    detections: tuple[ProjectedDetection, ...]
    processed_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "tile_id": self.tile_id,
            "region_id": self.region_id,
            "row_off": self.row_off,
            "col_off": self.col_off,
            "width": self.width,
            "height": self.height,
            "vegetation_fraction": round(self.vegetation_fraction, 6),
            "texture_score": round(self.texture_score, 6),
            "candidate_score": round(self.candidate_score, 6),
            "status": self.status,
            "image_path": self.image_path,
            "detection_count": len(self.detections),
            "detections": [detection.to_dict() for detection in self.detections],
            "processed_at": self.processed_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> DamageTileResult:
        detections_payload = payload.get("detections")
        detections: tuple[ProjectedDetection, ...] = ()
        if isinstance(detections_payload, list):
            detections = tuple(
                ProjectedDetection.from_dict(item)
                for item in detections_payload
                if isinstance(item, dict)
            )
        return cls(
            tile_id=str(payload["tile_id"]),
            region_id=str(payload["region_id"]),
            row_off=int(payload["row_off"]),
            col_off=int(payload["col_off"]),
            width=int(payload["width"]),
            height=int(payload["height"]),
            vegetation_fraction=float(payload["vegetation_fraction"]),
            texture_score=float(payload["texture_score"]),
            candidate_score=float(payload["candidate_score"]),
            status=str(payload["status"]),
            image_path=None if payload.get("image_path") is None else str(payload["image_path"]),
            detections=detections,
            processed_at=str(payload.get("processed_at", "")),
        )

    def to_tile_candidate(self) -> TileCandidate:
        return TileCandidate(
            tile_id=self.tile_id,
            region_id=self.region_id,
            row_off=self.row_off,
            col_off=self.col_off,
            width=self.width,
            height=self.height,
            vegetation_fraction=self.vegetation_fraction,
            texture_score=self.texture_score,
            candidate_score=self.candidate_score,
        )

    def to_task_meta(self) -> dict[str, object]:
        payload = self.to_tile_candidate().to_dict()
        payload["status"] = self.status
        payload["image_path"] = self.image_path
        return payload


class ImagePromptRunner(Protocol):
    async def run_prompt(self, prompt: str, image: np.ndarray) -> str:
        """Run a prompt against one image."""


class QwenVLImageRunner:
    def __init__(self, controller: QwenVLAPIController) -> None:
        self._controller = controller

    async def run_prompt(self, prompt: str, image: np.ndarray) -> str:
        # Pipeline images are RGB, while the low-level controller expects OpenCV-style BGR arrays.
        bgr_image = image[:, :, ::-1].copy()
        return await self._controller.inference_image_base64(prompt, [bgr_image])


QwenVLTileAnnotator = QwenVLImageRunner


def build_tree_region_prompt(region: RegionCandidate) -> str:
    return (
        "你是一名林业遥感助手。请判断当前低分辨率正射图区域是否包含值得继续做"
        "树木枯死/倒伏精查的树木区域，只输出 JSON。\n"
        f"区域尺寸: width={region.width}, height={region.height}。\n"
        "输出格式:\n"
        "{\n"
        '  "has_tree": true 或 false,\n'
        '  "score": 0 到 1 之间的小数,\n'
        '  "tree_coverage": 0 到 1 之间的小数,\n'
        '  "reason": "简短说明"\n'
        "}\n"
        "判定要求:\n"
        "1. 若区域中存在明显林冠、成片树带、林地斑块或足以继续细查的树木群，则 has_tree=true。\n"
        "2. 道路、水体、裸地、建筑、稀疏灌丛为主时，has_tree=false。\n"
        "3. 不要输出 markdown，不要补充解释。"
    )


def build_tree_damage_prompt(
    tile: TileCandidate,
    labels: tuple[DamageLabel, ...],
) -> str:
    label_descriptions = {
        "fallen_tree": "fallen_tree: 树干或树冠明显倒伏、横卧、顺坡倾倒，和周边直立树形成明显差异。",
        "diseased_tree": "diseased_tree: 树冠明显发黄、发红、灰败、稀疏或局部枯死，呈现可疑病害或衰败迹象。",
    }
    requested_labels = "\n".join(label_descriptions[label] for label in labels)
    return (
        "你是一名林业遥感标注助手。请对当前正射图切片做目标检测，只输出 JSON。\n"
        f"切片尺寸: width={tile.width}, height={tile.height}。\n"
        "需要检测的类别:\n"
        f"{requested_labels}\n"
        "输出格式:\n"
        "{\n"
        '  "summary": "一句话概括该切片情况",\n'
        '  "detections": [\n'
        "    {\n"
        '      "label": "fallen_tree 或 diseased_tree",\n'
        '      "score": 0 到 1 之间的小数,\n'
        '      "bbox": [x0, y0, x1, y1],\n'
        '      "reason": "简短判断依据"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "要求:\n"
        "1. bbox 使用当前切片内的像素坐标。\n"
        "2. 如果没有可信目标，detections 返回空数组。\n"
        "3. 不要输出 markdown，不要附加解释。"
    )


def generate_tile_candidates(
    width: int,
    height: int,
    tile_size: int,
    overlap: int,
) -> list[tuple[int, int, int, int]]:
    row_starts = _generate_starts(height, tile_size, overlap)
    col_starts = _generate_starts(width, tile_size, overlap)
    windows: list[tuple[int, int, int, int]] = []
    for row_off in row_starts:
        for col_off in col_starts:
            tile_width = min(tile_size, width - col_off)
            tile_height = min(tile_size, height - row_off)
            windows.append((row_off, col_off, tile_height, tile_width))
    return windows


def build_region_candidates(
    width: int,
    height: int,
    region_size: int,
    region_overlap: int,
) -> list[RegionCandidate]:
    candidates: list[RegionCandidate] = []
    for index, (row_off, col_off, region_height, region_width) in enumerate(
        generate_tile_candidates(width, height, region_size, region_overlap)
    ):
        candidates.append(
            RegionCandidate(
                region_id=f"region_{index:05d}",
                row_off=row_off,
                col_off=col_off,
                width=region_width,
                height=region_height,
            )
        )
    return candidates


def build_damage_tile_candidates(
    region: RegionCandidate,
    tile_size: int,
    overlap: int,
    max_tiles_per_region: int | None = None,
) -> list[TileCandidate]:
    candidates: list[TileCandidate] = []
    windows = generate_tile_candidates(region.width, region.height, tile_size, overlap)
    if max_tiles_per_region is not None:
        windows = windows[:max_tiles_per_region]

    for index, (row_off, col_off, tile_height, tile_width) in enumerate(windows):
        candidates.append(
            TileCandidate(
                tile_id=f"{region.region_id}_tile_{index:04d}",
                region_id=region.region_id,
                row_off=region.row_off + row_off,
                col_off=region.col_off + col_off,
                width=tile_width,
                height=tile_height,
                vegetation_fraction=0.0,
                texture_score=0.0,
                candidate_score=0.0,
            )
        )
    return candidates


def parse_tree_region_response(
    response_text: str,
    default_vegetation_fraction: float = 0.0,
    default_texture_score: float = 0.0,
) -> TreeRegionResult:
    payload = parse_response_text(response_text)
    if not isinstance(payload, dict):
        raise ValueError("树木区域响应必须是对象")

    has_tree = _coerce_bool(
        payload.get("has_tree")
        or payload.get("contains_trees")
        or payload.get("tree_present")
        or payload.get("tree_region")
    )
    if has_tree is None:
        raise ValueError(f"树木区域响应缺少 has_tree: {payload}")

    score = _coerce_score(payload.get("score") or payload.get("confidence"))
    if score is None:
        score = 1.0 if has_tree else 0.0

    tree_coverage = _coerce_score(
        payload.get("tree_coverage") or payload.get("coverage") or payload.get("canopy_coverage")
    )
    reason_value = payload.get("reason") or payload.get("summary") or ""

    return TreeRegionResult(
        region_id="",
        row_off=0,
        col_off=0,
        width=0,
        height=0,
        method="qwen_vl",
        has_tree=has_tree,
        score=score,
        vegetation_fraction=default_vegetation_fraction,
        texture_score=default_texture_score,
        tree_coverage=tree_coverage,
        reason=str(reason_value),
        processed_at=_now_iso(),
    )


def parse_tree_damage_response(
    response_text: str,
    tile: TileCandidate,
    min_detection_score: float,
    allowed_labels: tuple[DamageLabel, ...],
) -> list[TileDetection]:
    payload = parse_response_text(response_text)
    detection_payloads = _extract_detection_payloads(payload)
    detections: list[TileDetection] = []

    for detection_payload in detection_payloads:
        label = _normalize_label(detection_payload.get("label"))
        if label is None or label not in allowed_labels:
            continue

        score = _coerce_score(detection_payload.get("score"))
        if score is None or score < min_detection_score:
            continue

        bbox = _coerce_bbox(detection_payload.get("bbox"))
        if bbox is None:
            continue
        clipped_bbox = clip_box(bbox, tile.width, tile.height)
        if clipped_bbox[2] <= clipped_bbox[0] or clipped_bbox[3] <= clipped_bbox[1]:
            continue

        reason_value = detection_payload.get("reason")
        reason = "" if reason_value is None else str(reason_value)
        detections.append(
            TileDetection(
                label=label,
                score=score,
                reason=reason,
                tile_px_bbox=clipped_bbox,
            )
        )

    return detections


def project_tile_detection(
    tile: TileCandidate,
    detection: TileDetection,
    transform: Affine,
    crs: CRS | None,
) -> ProjectedDetection:
    x0, y0, x1, y1 = detection.tile_px_bbox
    orig_bbox = (
        tile.col_off + x0,
        tile.row_off + y0,
        tile.col_off + x1,
        tile.row_off + y1,
    )

    source_crs_polygon: tuple[tuple[float, float], ...] | None = None
    wgs84_polygon: tuple[tuple[float, float], ...] | None = None
    source_crs = None if crs is None else str(crs)

    if crs is not None:
        source_crs_polygon = _pixel_bbox_to_polygon(orig_bbox, transform)
        if crs.to_string() == "EPSG:4326":
            wgs84_polygon = source_crs_polygon
        else:
            xs = [point[0] for point in source_crs_polygon]
            ys = [point[1] for point in source_crs_polygon]
            longitudes, latitudes = warp_transform(crs, "EPSG:4326", xs, ys)
            wgs84_polygon = tuple(zip(longitudes, latitudes, strict=True))

    return ProjectedDetection(
        tile_id=tile.tile_id,
        region_id=tile.region_id,
        label=detection.label,
        score=detection.score,
        reason=detection.reason,
        tile_px_bbox=detection.tile_px_bbox,
        orig_px_bbox=orig_bbox,
        source_crs=source_crs,
        source_crs_polygon=source_crs_polygon,
        wgs84_polygon=wgs84_polygon,
    )


def export_label_studio_tasks(
    path: str | Path,
    tile_results: list[DamageTileResult],
    image_root_url: str | None = None,
    from_name: str = "label",
    to_name: str = "image",
    model_version: str = "tree-damage-pre-annotation-v2",
) -> list[dict[str, object]]:
    tasks: list[dict[str, object]] = []
    for tile_result in tile_results:
        if tile_result.image_path is None:
            continue

        image_reference = _build_image_reference(Path(tile_result.image_path), image_root_url)
        predictions = [
            {
                "id": f"{tile_result.tile_id}_{index:03d}",
                "from_name": from_name,
                "to_name": to_name,
                "type": "rectanglelabels",
                "origin": "prediction",
                "score": detection.score,
                "value": {
                    "x": detection.tile_px_bbox[0] / tile_result.width * 100.0,
                    "y": detection.tile_px_bbox[1] / tile_result.height * 100.0,
                    "width": (detection.tile_px_bbox[2] - detection.tile_px_bbox[0])
                    / tile_result.width
                    * 100.0,
                    "height": (detection.tile_px_bbox[3] - detection.tile_px_bbox[1])
                    / tile_result.height
                    * 100.0,
                    "rectanglelabels": [detection.label],
                },
            }
            for index, detection in enumerate(tile_result.detections, start=1)
        ]
        tasks.append(
            {
                "id": tile_result.tile_id,
                "data": {"image": image_reference},
                "meta": tile_result.to_task_meta(),
                "predictions": [
                    {
                        "model_version": model_version,
                        "score": round(_mean_detection_score(tile_result.detections), 6),
                        "result": predictions,
                    }
                ],
            }
        )

    write_json(path, tasks)
    return tasks


def export_geojson(path: str | Path, detections: list[ProjectedDetection]) -> dict[str, object]:
    features: list[dict[str, object]] = []
    for detection in detections:
        if detection.wgs84_polygon is None:
            continue
        polygon = [[list(point) for point in detection.wgs84_polygon]]
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "tile_id": detection.tile_id,
                    "region_id": detection.region_id,
                    "label": detection.label,
                    "score": round(detection.score, 6),
                    "reason": detection.reason,
                    "orig_px_bbox": list(detection.orig_px_bbox),
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": polygon,
                },
            }
        )

    payload: dict[str, object] = {"type": "FeatureCollection", "features": features}
    write_json(path, payload)
    return payload


async def run_orthomosaic_tree_damage_pipeline(
    config: OrthomosaicTreeDamageConfig,
    runner: ImagePromptRunner | None = None,
) -> dict[str, object]:
    output_dir = config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    state_dir = output_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    dashboard_dir = output_dir / "dashboard"
    dashboard_dir.mkdir(parents=True, exist_ok=True)

    damage_tiles_dir = output_dir / "damage_tiles"
    damage_tiles_dir.mkdir(parents=True, exist_ok=True)

    tree_result_path = state_dir / "tree_region_results.jsonl"
    damage_tile_result_path = state_dir / "damage_tile_results.jsonl"
    region_index_path = state_dir / "region_index.json"
    overview_path = dashboard_dir / "overview.jpg"

    with rasterio.open(config.orthomosaic_path) as dataset:
        regions = _load_or_create_region_index(
            path=region_index_path,
            width=dataset.width,
            height=dataset.height,
            config=config,
        )
        _initialize_manifest(
            output_dir=output_dir,
            config=config,
            dataset=dataset,
            regions=regions,
        )
        overview_width, overview_height = _ensure_overview_image(
            dataset=dataset, path=overview_path, max_size=config.overview_max_size
        )

        tree_results = _load_tree_region_results(tree_result_path)
        damage_tile_results = _load_damage_tile_results(damage_tile_result_path)

        _materialize_pipeline_outputs(
            config=config,
            dataset=dataset,
            overview_image_name=overview_path.name,
            overview_width=overview_width,
            overview_height=overview_height,
            regions=regions,
            tree_results=tree_results,
            damage_tile_results=damage_tile_results,
        )

        initial_region_states = build_region_states(
            regions=regions,
            tree_results=tree_results,
            damage_tile_results=damage_tile_results,
            config=config,
        )
        pending_regions = [
            region
            for region in regions
            if _region_needs_processing(initial_region_states[region.region_id], runner)
        ]
        target_regions = pending_regions
        if config.max_regions is not None:
            target_regions = pending_regions[: config.max_regions]

        logger.info(
            "开始处理正射图: total_regions={} pending_regions={} target_regions={} output_dir={}",
            len(regions),
            len(pending_regions),
            len(target_regions),
            output_dir,
        )

        processed_regions_this_run = 0
        total_target_regions = len(target_regions)
        for region_index, region in enumerate(target_regions, start=1):
            logger.info(
                "区域进度 {}，开始处理 region_id={} row={} col={} size={}x{}",
                _format_progress(region_index, total_target_regions),
                region.region_id,
                region.row_off,
                region.col_off,
                region.width,
                region.height,
            )
            tree_result = tree_results.get(region.region_id)
            if tree_result is None:
                preview = read_window_image(
                    dataset=dataset,
                    row_off=region.row_off,
                    col_off=region.col_off,
                    width=region.width,
                    height=region.height,
                    max_size=config.region_preview_size,
                )
                tree_result = await classify_tree_region(
                    region=region,
                    preview=preview,
                    config=config,
                    runner=runner,
                )
                tree_results[region.region_id] = tree_result
                append_jsonl(tree_result_path, tree_result.to_dict())
                logger.info(
                    "区域 {} 树木判定完成: has_tree={} score={:.3f} method={}",
                    region.region_id,
                    tree_result.has_tree,
                    tree_result.score,
                    tree_result.method,
                )
            else:
                logger.info(
                    "区域 {} 复用已有树木判定: has_tree={} score={:.3f} method={}",
                    region.region_id,
                    tree_result.has_tree,
                    tree_result.score,
                    tree_result.method,
                )

            if tree_result.has_tree:
                await _process_region_damage_tiles(
                    dataset=dataset,
                    region=region,
                    config=config,
                    runner=runner,
                    damage_tiles_dir=damage_tiles_dir,
                    damage_tile_results=damage_tile_results,
                    damage_tile_result_path=damage_tile_result_path,
                )
            else:
                logger.info("区域 {} 无树木，跳过损伤检测阶段", region.region_id)

            processed_regions_this_run += 1
            region_summary = _build_region_processing_summary(region.region_id, damage_tile_results)
            logger.info(
                "区域进度 {}，处理完成 region_id={} tree={} damage_tiles={}/{} pending_model={} detections={}",
                _format_progress(processed_regions_this_run, total_target_regions),
                region.region_id,
                tree_result.has_tree,
                region_summary["processed_tiles"],
                region_summary["total_tiles"],
                region_summary["pending_model_tiles"],
                region_summary["detection_count"],
            )
            if processed_regions_this_run % config.dashboard_refresh_interval_regions == 0:
                _materialize_pipeline_outputs(
                    config=config,
                    dataset=dataset,
                    overview_image_name=overview_path.name,
                    overview_width=overview_width,
                    overview_height=overview_height,
                    regions=regions,
                    tree_results=tree_results,
                    damage_tile_results=damage_tile_results,
                )
                logger.info(
                    "已刷新 dashboard 和导出文件: processed_regions_this_run={}",
                    processed_regions_this_run,
                )

        logger.info(
            "正射图处理结束: processed_regions_this_run={} target_regions={}",
            processed_regions_this_run,
            total_target_regions,
        )

    with rasterio.open(config.orthomosaic_path) as dataset:
        return _materialize_pipeline_outputs(
            config=config,
            dataset=dataset,
            overview_image_name=overview_path.name,
            overview_width=overview_width,
            overview_height=overview_height,
            regions=regions,
            tree_results=tree_results,
            damage_tile_results=damage_tile_results,
        )


def run_pipeline_sync(
    config: OrthomosaicTreeDamageConfig,
    runner: ImagePromptRunner | None = None,
) -> dict[str, object]:
    return asyncio.run(run_orthomosaic_tree_damage_pipeline(config, runner))


async def classify_tree_region(
    region: RegionCandidate,
    preview: np.ndarray,
    config: OrthomosaicTreeDamageConfig,
    runner: ImagePromptRunner | None,
) -> TreeRegionResult:
    vegetation_fraction, texture_score, tree_score = score_tree_region_preview(preview)

    if config.tree_region_mode == "qwen_vl" and runner is not None:
        prompt = build_tree_region_prompt(region)
        try:
            parsed = parse_tree_region_response(
                await runner.run_prompt(prompt, preview),
                default_vegetation_fraction=vegetation_fraction,
                default_texture_score=texture_score,
            )
            return replace(
                parsed,
                region_id=region.region_id,
                row_off=region.row_off,
                col_off=region.col_off,
                width=region.width,
                height=region.height,
                tree_coverage=parsed.tree_coverage
                if parsed.tree_coverage is not None
                else vegetation_fraction,
                processed_at=_now_iso(),
            )
        except ValueError:
            pass

    has_tree = (
        vegetation_fraction >= config.min_tree_region_vegetation_fraction
        and tree_score >= config.min_tree_region_score
    )
    reason = (
        f"heuristic vegetation={vegetation_fraction:.3f}, texture={texture_score:.3f}, "
        f"score={tree_score:.3f}"
    )
    return TreeRegionResult(
        region_id=region.region_id,
        row_off=region.row_off,
        col_off=region.col_off,
        width=region.width,
        height=region.height,
        method="heuristic",
        has_tree=has_tree,
        score=tree_score,
        vegetation_fraction=vegetation_fraction,
        texture_score=texture_score,
        tree_coverage=vegetation_fraction,
        reason=reason,
        processed_at=_now_iso(),
    )


def score_tree_region_preview(image: np.ndarray) -> tuple[float, float, float]:
    vegetation_fraction, texture_score = _score_vegetation_texture(image)
    tree_score = min(vegetation_fraction * 0.65 + texture_score * 0.35, 1.0)
    return vegetation_fraction, texture_score, tree_score


def score_tile_for_tree_damage(image: np.ndarray) -> tuple[float, float, float]:
    vegetation_fraction, texture_score = _score_vegetation_texture(image)
    candidate_score = min(vegetation_fraction * 0.75 + texture_score * 0.25, 1.0)
    return vegetation_fraction, texture_score, candidate_score


def read_window_image(
    dataset: rasterio.io.DatasetReader,
    row_off: int,
    col_off: int,
    width: int,
    height: int,
    max_size: int | None = None,
) -> np.ndarray:
    window = Window(col_off=col_off, row_off=row_off, width=width, height=height)
    out_shape: tuple[int, int, int] | None = None
    if max_size is not None and max(width, height) > max_size:
        scale = max_size / max(width, height)
        out_height = max(1, int(round(height * scale)))
        out_width = max(1, int(round(width * scale)))
        out_shape = (dataset.count, out_height, out_width)

    raw_tile = dataset.read(
        window=window,
        out_shape=out_shape,
        resampling=Resampling.bilinear,
    )
    if raw_tile.size == 0:
        raise ValueError(
            f"切片读取失败: row={row_off}, col={col_off}, width={width}, height={height}"
        )

    rgb = _select_rgb_bands(raw_tile)
    return np.transpose(rgb, (1, 2, 0))


def build_region_states(
    *,
    regions: list[RegionCandidate],
    tree_results: dict[str, TreeRegionResult],
    damage_tile_results: dict[str, DamageTileResult],
    config: OrthomosaicTreeDamageConfig,
) -> dict[str, RegionState]:
    damage_tiles_by_region: dict[str, list[DamageTileResult]] = {}
    for tile_result in damage_tile_results.values():
        damage_tiles_by_region.setdefault(tile_result.region_id, []).append(tile_result)

    states: dict[str, RegionState] = {}
    for region in regions:
        tree_result = tree_results.get(region.region_id)
        tile_results = damage_tiles_by_region.get(region.region_id, [])
        total_tiles = len(
            build_damage_tile_candidates(
                region=region,
                tile_size=config.tile_size,
                overlap=config.overlap,
                max_tiles_per_region=config.max_tiles_per_region,
            )
        )
        prepared_tiles = len(tile_results)
        processed_tiles = sum(
            1 for tile_result in tile_results if tile_result.status in DONE_TILE_STATUSES
        )
        pending_model_tiles = sum(
            1 for tile_result in tile_results if tile_result.status == "pending_model"
        )
        detection_count = sum(len(tile_result.detections) for tile_result in tile_results)

        if tree_result is None:
            state = RegionState(
                region_id=region.region_id,
                row_off=region.row_off,
                col_off=region.col_off,
                width=region.width,
                height=region.height,
                tree_stage_status="pending",
                tree_presence=None,
                tree_method=None,
                tree_score=None,
                tree_reason="",
                vegetation_fraction=None,
                texture_score=None,
                damage_stage_status="pending",
                damage_tile_total=total_tiles,
                damage_tile_prepared=prepared_tiles,
                damage_tile_processed=processed_tiles,
                damage_tile_pending_model=pending_model_tiles,
                detection_count=0,
                dashboard_status="pending",
            )
            states[region.region_id] = state
            continue

        damage_stage_status = _compute_damage_stage_status(
            tree_result=tree_result,
            total_tiles=total_tiles,
            prepared_tiles=prepared_tiles,
            processed_tiles=processed_tiles,
            pending_model_tiles=pending_model_tiles,
        )
        dashboard_status = _compute_dashboard_status(
            tree_result=tree_result,
            damage_stage_status=damage_stage_status,
            detection_count=detection_count,
            processed_tiles=processed_tiles,
        )
        states[region.region_id] = RegionState(
            region_id=region.region_id,
            row_off=region.row_off,
            col_off=region.col_off,
            width=region.width,
            height=region.height,
            tree_stage_status="done",
            tree_presence=tree_result.has_tree,
            tree_method=tree_result.method,
            tree_score=round(tree_result.score, 6),
            tree_reason=tree_result.reason,
            vegetation_fraction=round(tree_result.vegetation_fraction, 6),
            texture_score=round(tree_result.texture_score, 6),
            damage_stage_status=damage_stage_status,
            damage_tile_total=total_tiles,
            damage_tile_prepared=prepared_tiles,
            damage_tile_processed=processed_tiles,
            damage_tile_pending_model=pending_model_tiles,
            detection_count=detection_count,
            dashboard_status=dashboard_status,
        )
    return states


async def _process_region_damage_tiles(
    *,
    dataset: rasterio.io.DatasetReader,
    region: RegionCandidate,
    config: OrthomosaicTreeDamageConfig,
    runner: ImagePromptRunner | None,
    damage_tiles_dir: Path,
    damage_tile_results: dict[str, DamageTileResult],
    damage_tile_result_path: Path,
) -> None:
    tile_candidates = build_damage_tile_candidates(
        region=region,
        tile_size=config.tile_size,
        overlap=config.overlap,
        max_tiles_per_region=config.max_tiles_per_region,
    )

    pending_tile_candidates: list[TileCandidate] = []
    for base_candidate in tile_candidates:
        existing = damage_tile_results.get(base_candidate.tile_id)
        if existing is not None and existing.status in DONE_TILE_STATUSES:
            continue
        if existing is not None and existing.status == "pending_model" and runner is None:
            continue
        pending_tile_candidates.append(base_candidate)
    total_pending_tiles = len(pending_tile_candidates)
    if total_pending_tiles == 0:
        logger.info(
            "区域 {} 损伤切片无需新增处理: total_tiles={}",
            region.region_id,
            len(tile_candidates),
        )
        return

    logger.info(
        "区域 {} 开始损伤切片处理: pending_tiles={} total_tiles={}",
        region.region_id,
        total_pending_tiles,
        len(tile_candidates),
    )

    completed_tiles = 0
    for base_candidate in pending_tile_candidates:
        existing = damage_tile_results.get(base_candidate.tile_id)

        tile_candidate = base_candidate
        image_path: Path | None = None
        result_status = "pending"
        detection_count = 0

        if existing is not None and existing.status == "pending_model":
            tile_candidate = existing.to_tile_candidate()
            image_path = None if existing.image_path is None else Path(existing.image_path)
            image = _load_saved_image(image_path) if image_path and image_path.exists() else None
            if image is None:
                image = read_window_image(
                    dataset=dataset,
                    row_off=tile_candidate.row_off,
                    col_off=tile_candidate.col_off,
                    width=tile_candidate.width,
                    height=tile_candidate.height,
                )
                image_path = damage_tiles_dir / f"{tile_candidate.tile_id}.jpg"
                _save_tile_image(image_path, image)
        else:
            image = read_window_image(
                dataset=dataset,
                row_off=base_candidate.row_off,
                col_off=base_candidate.col_off,
                width=base_candidate.width,
                height=base_candidate.height,
            )
            vegetation_fraction, texture_score, candidate_score = score_tile_for_tree_damage(image)
            tile_candidate = replace(
                base_candidate,
                vegetation_fraction=vegetation_fraction,
                texture_score=texture_score,
                candidate_score=candidate_score,
            )
            if (
                tile_candidate.vegetation_fraction < config.min_vegetation_fraction
                or tile_candidate.candidate_score < config.min_candidate_score
            ):
                result = DamageTileResult(
                    tile_id=tile_candidate.tile_id,
                    region_id=tile_candidate.region_id,
                    row_off=tile_candidate.row_off,
                    col_off=tile_candidate.col_off,
                    width=tile_candidate.width,
                    height=tile_candidate.height,
                    vegetation_fraction=tile_candidate.vegetation_fraction,
                    texture_score=tile_candidate.texture_score,
                    candidate_score=tile_candidate.candidate_score,
                    status="skipped_low_signal",
                    image_path=None,
                    detections=(),
                    processed_at=_now_iso(),
                )
                damage_tile_results[result.tile_id] = result
                append_jsonl(damage_tile_result_path, result.to_dict())
                result_status = result.status
                completed_tiles += 1
                _log_tile_progress(
                    region_id=region.region_id,
                    tile_id=result.tile_id,
                    completed_tiles=completed_tiles,
                    total_tiles=total_pending_tiles,
                    status=result_status,
                    detection_count=detection_count,
                )
                continue

            image_path = damage_tiles_dir / f"{tile_candidate.tile_id}.jpg"
            _save_tile_image(image_path, image)
            if runner is None:
                result = DamageTileResult(
                    tile_id=tile_candidate.tile_id,
                    region_id=tile_candidate.region_id,
                    row_off=tile_candidate.row_off,
                    col_off=tile_candidate.col_off,
                    width=tile_candidate.width,
                    height=tile_candidate.height,
                    vegetation_fraction=tile_candidate.vegetation_fraction,
                    texture_score=tile_candidate.texture_score,
                    candidate_score=tile_candidate.candidate_score,
                    status="pending_model",
                    image_path=str(image_path),
                    detections=(),
                    processed_at=_now_iso(),
                )
                damage_tile_results[result.tile_id] = result
                append_jsonl(damage_tile_result_path, result.to_dict())
                result_status = result.status
                completed_tiles += 1
                _log_tile_progress(
                    region_id=region.region_id,
                    tile_id=result.tile_id,
                    completed_tiles=completed_tiles,
                    total_tiles=total_pending_tiles,
                    status=result_status,
                    detection_count=detection_count,
                )
                continue

        if runner is None:
            continue

        assert image_path is not None
        prompt = build_tree_damage_prompt(tile_candidate, config.labels)
        response_text = await runner.run_prompt(prompt, image)
        detections = parse_tree_damage_response(
            response_text=response_text,
            tile=tile_candidate,
            min_detection_score=config.min_detection_score,
            allowed_labels=config.labels,
        )
        projected_detections = tuple(
            project_tile_detection(tile_candidate, detection, dataset.transform, dataset.crs)
            for detection in detections
        )
        result = DamageTileResult(
            tile_id=tile_candidate.tile_id,
            region_id=tile_candidate.region_id,
            row_off=tile_candidate.row_off,
            col_off=tile_candidate.col_off,
            width=tile_candidate.width,
            height=tile_candidate.height,
            vegetation_fraction=tile_candidate.vegetation_fraction,
            texture_score=tile_candidate.texture_score,
            candidate_score=tile_candidate.candidate_score,
            status="done",
            image_path=str(image_path),
            detections=projected_detections,
            processed_at=_now_iso(),
        )
        damage_tile_results[result.tile_id] = result
        append_jsonl(damage_tile_result_path, result.to_dict())
        result_status = result.status
        detection_count = len(projected_detections)
        completed_tiles += 1
        _log_tile_progress(
            region_id=region.region_id,
            tile_id=result.tile_id,
            completed_tiles=completed_tiles,
            total_tiles=total_pending_tiles,
            status=result_status,
            detection_count=detection_count,
        )

    logger.info(
        "区域 {} 损伤切片处理完成: processed_tiles={} total_tiles={}",
        region.region_id,
        completed_tiles,
        total_pending_tiles,
    )


def _materialize_pipeline_outputs(
    *,
    config: OrthomosaicTreeDamageConfig,
    dataset: rasterio.io.DatasetReader,
    overview_image_name: str,
    overview_width: int,
    overview_height: int,
    regions: list[RegionCandidate],
    tree_results: dict[str, TreeRegionResult],
    damage_tile_results: dict[str, DamageTileResult],
) -> dict[str, object]:
    region_states = build_region_states(
        regions=regions,
        tree_results=tree_results,
        damage_tile_results=damage_tile_results,
        config=config,
    )
    ordered_region_states = [region_states[region.region_id] for region in regions]
    ordered_tile_results = sorted(damage_tile_results.values(), key=lambda item: item.tile_id)
    deduplicated_detections = _collect_deduplicated_detections(ordered_tile_results)

    write_jsonl(
        config.output_dir / "region_status.jsonl",
        [state.to_dict() for state in ordered_region_states],
    )
    write_jsonl(
        config.output_dir / "damage_tile_status.jsonl",
        [tile_result.to_dict() for tile_result in ordered_tile_results],
    )
    write_jsonl(
        config.output_dir / "tile_artifacts.jsonl",
        [
            tile_result.to_task_meta()
            for tile_result in ordered_tile_results
            if tile_result.image_path is not None
        ],
    )
    write_jsonl(
        config.output_dir / "detections.jsonl",
        [detection.to_dict() for detection in deduplicated_detections],
    )
    export_geojson(config.output_dir / "detections_wgs84.geojson", deduplicated_detections)
    export_label_studio_tasks(
        path=config.output_dir / "label_studio_tasks.json",
        tile_results=[
            tile_result
            for tile_result in ordered_tile_results
            if tile_result.status in {"done", "pending_model"}
        ],
        image_root_url=config.label_studio_image_root_url,
    )

    label_counts = {label: 0 for label in config.labels}
    for detection in deduplicated_detections:
        label_counts[detection.label] += 1

    summary = {
        "orthomosaic_path": str(config.orthomosaic_path),
        "output_dir": str(config.output_dir),
        "source_crs": None if dataset.crs is None else str(dataset.crs),
        "tree_region_mode": config.tree_region_mode,
        "resume_enabled": True,
        "dashboard_path": str(config.output_dir / "dashboard" / "index.html"),
        "overview_width": overview_width,
        "overview_height": overview_height,
        "total_region_count": len(ordered_region_states),
        "tree_region_checked_count": sum(
            1 for state in ordered_region_states if state.tree_stage_status == "done"
        ),
        "tree_region_count": sum(1 for state in ordered_region_states if state.tree_presence),
        "non_tree_region_count": sum(
            1 for state in ordered_region_states if state.tree_presence is False
        ),
        "damage_done_region_count": sum(
            1 for state in ordered_region_states if state.damage_stage_status == "done"
        ),
        "damage_pending_region_count": sum(
            1
            for state in ordered_region_states
            if state.damage_stage_status in {"pending", "pending_model", "running"}
        ),
        "damage_positive_region_count": sum(
            1 for state in ordered_region_states if state.detection_count > 0
        ),
        "damage_tile_total_count": sum(state.damage_tile_total for state in ordered_region_states),
        "damage_tile_prepared_count": sum(
            state.damage_tile_prepared for state in ordered_region_states
        ),
        "damage_tile_processed_count": sum(
            state.damage_tile_processed for state in ordered_region_states
        ),
        "damage_tile_pending_model_count": sum(
            state.damage_tile_pending_model for state in ordered_region_states
        ),
        "detection_count": len(deduplicated_detections),
        "label_counts": label_counts,
    }
    write_json(config.output_dir / "summary.json", summary)

    dashboard_payload = build_dashboard_payload(
        title=config.dashboard_title,
        orthomosaic_path=str(config.orthomosaic_path),
        overview_image_name=overview_image_name,
        source_image_width=dataset.width,
        source_image_height=dataset.height,
        overview_width=overview_width,
        overview_height=overview_height,
        summary=summary,
        regions=[state.to_dict() for state in ordered_region_states],
        detections=[detection.to_dict() for detection in deduplicated_detections],
    )
    write_dashboard(config.output_dir / "dashboard", dashboard_payload)
    return summary


def _collect_deduplicated_detections(
    tile_results: list[DamageTileResult],
) -> list[ProjectedDetection]:
    detections: list[ProjectedDetection] = []
    for tile_result in tile_results:
        detections.extend(tile_result.detections)
    return deduplicate_detections(detections, iou_threshold=0.35)


def _compute_damage_stage_status(
    *,
    tree_result: TreeRegionResult,
    total_tiles: int,
    prepared_tiles: int,
    processed_tiles: int,
    pending_model_tiles: int,
) -> str:
    if not tree_result.has_tree:
        return "skipped"
    if total_tiles == 0:
        return "done"
    if prepared_tiles == 0:
        return "pending"
    if processed_tiles == total_tiles:
        return "done"
    if prepared_tiles == total_tiles and pending_model_tiles == total_tiles:
        return "pending_model"
    return "running"


def _format_progress(current: int, total: int) -> str:
    if total <= 0:
        return "0/0 (0.0%)"
    return f"{current}/{total} ({current / total:.1%})"


def _should_log_progress(current: int, total: int) -> bool:
    if total <= 10:
        return True
    if current in {1, total}:
        return True
    if current % 10 == 0:
        return True
    previous_bucket = (current - 1) * 10 // total
    current_bucket = current * 10 // total
    return current_bucket != previous_bucket


def _log_tile_progress(
    *,
    region_id: str,
    tile_id: str,
    completed_tiles: int,
    total_tiles: int,
    status: str,
    detection_count: int,
) -> None:
    if not _should_log_progress(completed_tiles, total_tiles):
        return
    logger.info(
        "区域 {} 切片进度 {} latest_tile={} status={} detections={}",
        region_id,
        _format_progress(completed_tiles, total_tiles),
        tile_id,
        status,
        detection_count,
    )


def _build_region_processing_summary(
    region_id: str,
    damage_tile_results: dict[str, DamageTileResult],
) -> dict[str, int]:
    region_tile_results = [
        tile_result for tile_result in damage_tile_results.values() if tile_result.region_id == region_id
    ]
    return {
        "total_tiles": len(region_tile_results),
        "processed_tiles": sum(
            1 for tile_result in region_tile_results if tile_result.status in DONE_TILE_STATUSES
        ),
        "pending_model_tiles": sum(
            1 for tile_result in region_tile_results if tile_result.status == "pending_model"
        ),
        "detection_count": sum(len(tile_result.detections) for tile_result in region_tile_results),
    }


def _compute_dashboard_status(
    *,
    tree_result: TreeRegionResult,
    damage_stage_status: str,
    detection_count: int,
    processed_tiles: int,
) -> str:
    if not tree_result.has_tree:
        return "non-tree"
    if damage_stage_status == "done" and detection_count > 0:
        return "positive"
    if damage_stage_status == "done":
        return "done"
    if damage_stage_status == "running" and processed_tiles > 0:
        return "running"
    return "tree-only"


def _region_needs_processing(
    region_state: RegionState,
    runner: ImagePromptRunner | None,
) -> bool:
    if region_state.tree_stage_status != "done":
        return True
    if region_state.tree_presence is False:
        return False
    if runner is None:
        return region_state.damage_stage_status in {"pending", "running"}
    return region_state.damage_stage_status in {"pending", "pending_model", "running"}


def _load_or_create_region_index(
    *,
    path: Path,
    width: int,
    height: int,
    config: OrthomosaicTreeDamageConfig,
) -> list[RegionCandidate]:
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("region_index.json 格式错误")
        return [RegionCandidate.from_dict(item) for item in payload if isinstance(item, dict)]

    regions = build_region_candidates(
        width=width,
        height=height,
        region_size=config.region_size,
        region_overlap=config.region_overlap,
    )
    write_json(path, [region.to_dict() for region in regions])
    return regions


def _load_tree_region_results(path: Path) -> dict[str, TreeRegionResult]:
    return {
        key: TreeRegionResult.from_dict(payload)
        for key, payload in load_latest_jsonl_records(path, "region_id").items()
    }


def _load_damage_tile_results(path: Path) -> dict[str, DamageTileResult]:
    return {
        key: DamageTileResult.from_dict(payload)
        for key, payload in load_latest_jsonl_records(path, "tile_id").items()
    }


def _initialize_manifest(
    *,
    output_dir: Path,
    config: OrthomosaicTreeDamageConfig,
    dataset: rasterio.io.DatasetReader,
    regions: list[RegionCandidate],
) -> None:
    manifest_path = output_dir / "run_manifest.json"
    manifest = {
        "orthomosaic_path": str(config.orthomosaic_path),
        "image_width": dataset.width,
        "image_height": dataset.height,
        "source_crs": None if dataset.crs is None else str(dataset.crs),
        "region_size": config.region_size,
        "region_overlap": config.region_overlap,
        "region_preview_size": config.region_preview_size,
        "tree_region_mode": config.tree_region_mode,
        "tile_size": config.tile_size,
        "overlap": config.overlap,
        "max_tiles_per_region": config.max_tiles_per_region,
        "labels": list(config.labels),
        "region_count": len(regions),
    }

    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        comparable_keys = tuple(manifest.keys())
        mismatch_keys = [key for key in comparable_keys if existing.get(key) != manifest.get(key)]
        if mismatch_keys:
            mismatch_text = ", ".join(mismatch_keys)
            raise ValueError(
                f"当前 output_dir 已存在不同配置的断点状态，无法直接续跑。冲突字段: {mismatch_text}"
            )
        return

    write_json(manifest_path, manifest)


def _ensure_overview_image(
    *,
    dataset: rasterio.io.DatasetReader,
    path: Path,
    max_size: int,
) -> tuple[int, int]:
    if path.exists():
        with Image.open(path) as image:
            return image.width, image.height

    image = read_window_image(
        dataset=dataset,
        row_off=0,
        col_off=0,
        width=dataset.width,
        height=dataset.height,
        max_size=max_size,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image).save(path, format="JPEG", quality=90)
    return image.shape[1], image.shape[0]


def _save_tile_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image).save(path, format="JPEG", quality=92)


def _load_saved_image(path: Path) -> np.ndarray | None:
    if not path.exists():
        return None
    return np.asarray(Image.open(path).convert("RGB"))


def _score_vegetation_texture(image: np.ndarray) -> tuple[float, float]:
    rgb = image.astype(np.float32) / 255.0
    red = rgb[:, :, 0]
    green = rgb[:, :, 1]
    blue = rgb[:, :, 2]

    # 明亮区域：绝对阈值检测
    lit_mask = (green > 0.16) & ((green - red) > 0.03) & ((green - blue) > 0.02)

    # 阴影区域：用归一化绿色比例检测（亮度低但绿色相对占比仍高）
    total = red + green + blue + 1e-6
    green_ratio = green / total
    shadow_mask = (
        (green_ratio > 0.38)
        & ((green - red) > 0.01)
        & (green > 0.04)
        & (total > 0.06)
    )

    vegetation_mask = lit_mask | shadow_mask
    vegetation_fraction = float(vegetation_mask.mean())

    grayscale = 0.299 * red + 0.587 * green + 0.114 * blue
    gray_std = float(grayscale.std())
    gray_mean = float(grayscale.mean())

    # 明亮区域用标准差，阴影区域用变异系数（对均匀偏暗更宽容）
    abs_texture = min(gray_std * 5.0, 1.0)
    cv_texture = min((gray_std / gray_mean) * 2.0, 1.0) if gray_mean > 0.02 else 0.0
    texture_score = max(abs_texture, cv_texture)

    return vegetation_fraction, texture_score


def _generate_starts(size: int, tile_size: int, overlap: int) -> list[int]:
    if size <= tile_size:
        return [0]

    stride = tile_size - overlap
    starts = list(range(0, max(size - tile_size, 0) + 1, stride))
    last_start = size - tile_size
    if starts[-1] != last_start:
        starts.append(last_start)
    return starts


def _extract_detection_payloads(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ("detections", "objects", "results", "annotations"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    if {"label", "bbox"} <= payload.keys():
        return [payload]
    return []


def _normalize_label(value: object) -> DamageLabel | None:
    if value is None:
        return None
    label = str(value).strip().lower()
    return LABEL_ALIASES.get(label)


def _coerce_score(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "y"}:
            return True
        if normalized in {"false", "no", "0", "n"}:
            return False
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    return None


def _coerce_bbox(value: object) -> tuple[float, float, float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            x0, y0, x1, y1 = (float(item) for item in value)
        except (TypeError, ValueError):
            return None
        return (x0, y0, x1, y1)

    if isinstance(value, dict):
        if {"x", "y", "width", "height"} <= value.keys():
            try:
                x0 = float(value["x"])
                y0 = float(value["y"])
                width = float(value["width"])
                height = float(value["height"])
            except (TypeError, ValueError):
                return None
            return (x0, y0, x0 + width, y0 + height)
        if {"x0", "y0", "x1", "y1"} <= value.keys():
            try:
                return (
                    float(value["x0"]),
                    float(value["y0"]),
                    float(value["x1"]),
                    float(value["y1"]),
                )
            except (TypeError, ValueError):
                return None
    return None


def _coerce_polygon(value: object) -> tuple[tuple[float, float], ...] | None:
    if not isinstance(value, list):
        return None
    polygon: list[tuple[float, float]] = []
    for point in value:
        if not isinstance(point, list | tuple) or len(point) != 2:
            return None
        try:
            polygon.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError):
            return None
    return tuple(polygon)


def _pixel_bbox_to_polygon(
    bbox: tuple[float, float, float, float],
    transform: Affine,
) -> tuple[tuple[float, float], ...]:
    x0, y0, x1, y1 = bbox
    points = (
        (x0, y0),
        (x1, y0),
        (x1, y1),
        (x0, y1),
        (x0, y0),
    )
    return tuple(transform * point for point in points)


def _select_rgb_bands(raw_tile: np.ndarray) -> np.ndarray:
    if raw_tile.ndim != 3:
        raise ValueError(f"影像切片维度异常: {raw_tile.shape}")

    bands, _, _ = raw_tile.shape
    if bands >= 3:
        rgb = raw_tile[:3]
    elif bands == 1:
        rgb = np.repeat(raw_tile, 3, axis=0)
    else:
        rgb = np.concatenate([raw_tile, raw_tile[-1:, :, :]], axis=0)

    if rgb.dtype == np.uint8:
        return rgb

    stretched = np.empty_like(rgb, dtype=np.uint8)
    for band_index in range(3):
        stretched[band_index] = _stretch_to_uint8(rgb[band_index])
    return stretched


def _stretch_to_uint8(band: np.ndarray) -> np.ndarray:
    finite_mask = np.isfinite(band)
    if not finite_mask.any():
        return np.zeros_like(band, dtype=np.uint8)

    finite_band = band[finite_mask].astype(np.float32)
    lower = float(np.percentile(finite_band, 2))
    upper = float(np.percentile(finite_band, 98))
    if upper <= lower:
        upper = float(finite_band.max())
        lower = float(finite_band.min())

    if upper <= lower:
        return np.zeros_like(band, dtype=np.uint8)

    scaled = np.clip((band.astype(np.float32) - lower) / (upper - lower), 0.0, 1.0)
    return (scaled * 255.0).astype(np.uint8)


def _mean_detection_score(detections: tuple[ProjectedDetection, ...]) -> float:
    if not detections:
        return 0.0
    return sum(detection.score for detection in detections) / len(detections)


def _build_image_reference(image_path: Path, image_root_url: str | None) -> str:
    if not image_root_url:
        return str(image_path)
    return f"{image_root_url.rstrip('/')}/{image_path.name}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
