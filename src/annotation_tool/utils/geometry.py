from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol


class ScoredBBoxLike(Protocol):
    score: float
    orig_px_bbox: tuple[float, float, float, float]


def clip_box(
    bbox: tuple[float, float, float, float], width: int, height: int
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bbox
    x0 = max(0.0, min(float(width), x0))
    y0 = max(0.0, min(float(height), y0))
    x1 = max(0.0, min(float(width), x1))
    y1 = max(0.0, min(float(height), y1))
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    return (x0, y0, x1, y1)


def bbox_iou(
    bbox1: tuple[float, float, float, float], bbox2: tuple[float, float, float, float]
) -> float:
    bbox1_x0, bbox1_y0, bbox1_x1, bbox1_y1 = bbox1
    bbox2_x0, bbox2_y0, bbox2_x1, bbox2_y1 = bbox2

    inter_x0 = max(bbox1_x0, bbox2_x0)
    inter_y0 = max(bbox1_y0, bbox2_y0)
    inter_x1 = min(bbox1_x1, bbox2_x1)
    inter_y1 = min(bbox1_y1, bbox2_y1)

    if inter_x1 <= inter_x0 or inter_y1 <= inter_y0:
        return 0.0

    inter_area = (inter_x1 - inter_x0) * (inter_y1 - inter_y0)
    bbox1_area = max(0.0, bbox1_x1 - bbox1_x0) * max(0.0, bbox1_y1 - bbox1_y0)
    bbox2_area = max(0.0, bbox2_x1 - bbox2_x0) * max(0.0, bbox2_y1 - bbox2_y0)
    union_area = bbox1_area + bbox2_area - inter_area
    if union_area <= 0:
        return 0.0
    return inter_area / union_area


def deduplicate_detections[TScoredBBox: ScoredBBoxLike](
    detections: Iterable[TScoredBBox],
    iou_threshold: float = 0.5,
) -> list[TScoredBBox]:
    ordered = sorted(detections, key=lambda item: item.score, reverse=True)
    kept: list[TScoredBBox] = []
    for detection in ordered:
        if any(
            bbox_iou(detection.orig_px_bbox, existing.orig_px_bbox) >= iou_threshold
            for existing in kept
        ):
            continue
        kept.append(detection)
    return kept
