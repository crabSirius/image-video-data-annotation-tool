from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from annotation_tool.pipelines.orthomosaic_tree_damage.models import DetectionRecord
from annotation_tool.utils.geometry import bbox_iou, clip_box, deduplicate_detections


def _detection(detection_id: str, bbox: tuple[float, float, float, float], score: float) -> DetectionRecord:
    return DetectionRecord(
        detection_id=detection_id,
        raster_path="/tmp/example.tif",
        tile_id="tile-1",
        tile_path="/tmp/tile-1.png",
        candidate_id=f"{detection_id}-candidate",
        class_name="fallen_tree",
        score=score,
        evidence="",
        tile_bbox=bbox,
        orig_px_bbox=bbox,
        geo_bbox=bbox,
        geo_bbox_wgs84=bbox,
        source_crs="EPSG:3857",
        tile_width=1024,
        tile_height=1024,
        model_name="demo",
        prompt_version="v1",
    )


class PostprocessTests(unittest.TestCase):
    def test_clip_box_clamps_to_image_bounds(self) -> None:
        assert clip_box((-5, 10, 140, 160), 100, 120) == (0.0, 10, 100.0, 120.0)

    def test_bbox_iou_returns_expected_overlap(self) -> None:
        bbox1 = (0, 0, 10, 10)
        bbox2 = (5, 5, 15, 15)
        expected_iou = 25.0 / 175.0
        assert bbox_iou(bbox1, bbox2) == expected_iou
        assert bbox_iou(bbox2, bbox1) == expected_iou

    def test_deduplicate_detections_keeps_highest_score(self) -> None:
        kept = deduplicate_detections(
            [
                _detection("low", (10, 10, 40, 40), 0.4),
                _detection("high", (12, 12, 42, 42), 0.8),
                _detection("separate", (200, 200, 240, 240), 0.7),
            ],
            iou_threshold=0.5,
        )
        assert [item.detection_id for item in kept] == ["high", "separate"]


if __name__ == "__main__":
    unittest.main()
