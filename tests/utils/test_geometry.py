from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.utils.geometry import bbox_iou, clip_box, deduplicate_detections


@dataclass(frozen=True)
class Detection:
    score: float
    orig_px_bbox: tuple[float, float, float, float]


def test_clip_box_clamps_to_image_bounds_and_preserves_valid_order() -> None:
    clipped = clip_box((-5.0, 3.0, 12.0, 20.0), width=10, height=8)

    assert clipped == (0.0, 3.0, 10.0, 8.0)


def test_clip_box_swaps_inverted_coordinates_after_clamping() -> None:
    clipped = clip_box((9.0, 7.0, 2.0, -2.0), width=6, height=5)

    assert clipped == (2.0, 0.0, 6.0, 5.0)


def test_bbox_iou_returns_expected_overlap_ratio() -> None:
    iou = bbox_iou((0.0, 0.0, 10.0, 10.0), (5.0, 5.0, 15.0, 15.0))

    assert iou == pytest.approx(25.0 / 175.0)


def test_bbox_iou_returns_zero_for_non_overlapping_boxes() -> None:
    assert bbox_iou((0.0, 0.0, 1.0, 1.0), (2.0, 2.0, 3.0, 3.0)) == 0.0


def test_deduplicate_detections_keeps_highest_score_when_boxes_overlap() -> None:
    detections = [
        Detection(score=0.6, orig_px_bbox=(0.0, 0.0, 10.0, 10.0)),
        Detection(score=0.9, orig_px_bbox=(1.0, 1.0, 9.0, 9.0)),
        Detection(score=0.8, orig_px_bbox=(20.0, 20.0, 30.0, 30.0)),
    ]

    kept = deduplicate_detections(detections, iou_threshold=0.5)

    assert kept == [
        Detection(score=0.9, orig_px_bbox=(1.0, 1.0, 9.0, 9.0)),
        Detection(score=0.8, orig_px_bbox=(20.0, 20.0, 30.0, 30.0)),
    ]


def test_deduplicate_detections_keeps_boxes_below_threshold_in_score_order() -> None:
    detections = [
        Detection(score=0.2, orig_px_bbox=(0.0, 0.0, 10.0, 10.0)),
        Detection(score=0.7, orig_px_bbox=(5.0, 5.0, 15.0, 15.0)),
        Detection(score=0.5, orig_px_bbox=(30.0, 30.0, 40.0, 40.0)),
    ]

    kept = deduplicate_detections(detections, iou_threshold=0.6)

    assert kept == [
        Detection(score=0.7, orig_px_bbox=(5.0, 5.0, 15.0, 15.0)),
        Detection(score=0.5, orig_px_bbox=(30.0, 30.0, 40.0, 40.0)),
        Detection(score=0.2, orig_px_bbox=(0.0, 0.0, 10.0, 10.0)),
    ]
