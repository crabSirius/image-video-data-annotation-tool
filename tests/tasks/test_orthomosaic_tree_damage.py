from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin

import src.tasks.orthomosaic_tree_damage as orthomosaic_tree_damage
from src.tasks.orthomosaic_tree_damage import (
    OrthomosaicTreeDamageConfig,
    RegionCandidate,
    TileCandidate,
    build_damage_tile_candidates,
    build_region_candidates,
    build_tree_damage_prompt,
    parse_tree_damage_response,
    parse_tree_region_response,
    project_tile_detection,
    run_pipeline_sync,
)


def test_build_region_candidates_covers_image_edges() -> None:
    regions = build_region_candidates(width=900, height=700, region_size=256, region_overlap=64)

    assert regions[0] == RegionCandidate(
        region_id="region_00000",
        row_off=0,
        col_off=0,
        width=256,
        height=256,
    )
    assert max(region.row_off + region.height for region in regions) == 700
    assert max(region.col_off + region.width for region in regions) == 900


def test_build_damage_tile_candidates_stays_inside_region() -> None:
    region = RegionCandidate(
        region_id="region_00007",
        row_off=500,
        col_off=700,
        width=300,
        height=260,
    )

    candidates = build_damage_tile_candidates(region, tile_size=128, overlap=32)

    assert candidates[0].tile_id == "region_00007_tile_0000"
    assert all(candidate.region_id == region.region_id for candidate in candidates)
    assert max(candidate.row_off + candidate.height for candidate in candidates) == 760
    assert max(candidate.col_off + candidate.width for candidate in candidates) == 1000


def test_parse_tree_region_response_parses_expected_json() -> None:
    parsed = parse_tree_region_response(
        '{"has_tree": true, "score": 0.81, "tree_coverage": 0.46, "reason": "存在明显林冠"}',
        default_vegetation_fraction=0.4,
        default_texture_score=0.2,
    )

    assert parsed.has_tree is True
    assert parsed.score == 0.81
    assert parsed.tree_coverage == 0.46
    assert parsed.reason == "存在明显林冠"


def test_build_tree_damage_prompt_excludes_power_tower_artifacts() -> None:
    tile = TileCandidate(
        tile_id="region_00001_tile_0003",
        region_id="region_00001",
        row_off=0,
        col_off=0,
        width=512,
        height=512,
        vegetation_fraction=0.35,
        texture_score=0.22,
        candidate_score=0.41,
    )

    prompt = build_tree_damage_prompt(tile, ("fallen_tree", "diseased_tree"))

    assert "只有在图中能明确看到树干、树冠或整株树木" in prompt
    assert "电塔、输电杆塔、电线杆" in prompt
    assert "塔影或清障带都不是目标" in prompt
    assert "无法确认异常主体是树木本体，必须放弃检测" in prompt


def test_parse_tree_damage_response_supports_markdown_and_alias_labels() -> None:
    tile = TileCandidate(
        tile_id="region_00001_tile_0000",
        region_id="region_00001",
        row_off=100,
        col_off=200,
        width=256,
        height=128,
        vegetation_fraction=0.4,
        texture_score=0.2,
        candidate_score=0.35,
    )
    response = """```json
{
  "detections": [
    {
      "label": "倒伏树木",
      "score": 0.93,
      "bbox": {"x": 12, "y": 18, "width": 50, "height": 30},
      "reason": "树冠呈条带状倾倒"
    },
    {
      "label": "其他",
      "score": 0.99,
      "bbox": [0, 0, 10, 10]
    }
  ]
}
```"""

    detections = parse_tree_damage_response(
        response_text=response,
        tile=tile,
        min_detection_score=0.5,
        allowed_labels=("fallen_tree", "diseased_tree"),
    )

    assert len(detections) == 1
    assert detections[0].label == "fallen_tree"
    assert detections[0].tile_px_bbox == (12.0, 18.0, 62.0, 48.0)


def test_project_tile_detection_maps_pixels_to_global_and_wgs84() -> None:
    tile = TileCandidate(
        tile_id="region_00002_tile_0001",
        region_id="region_00002",
        row_off=100,
        col_off=200,
        width=256,
        height=256,
        vegetation_fraction=0.3,
        texture_score=0.2,
        candidate_score=0.4,
    )
    detection = parse_tree_damage_response(
        response_text=json.dumps(
            {"detections": [{"label": "diseased_tree", "score": 0.88, "bbox": [20, 10, 70, 40]}]}
        ),
        tile=tile,
        min_detection_score=0.5,
        allowed_labels=("fallen_tree", "diseased_tree"),
    )[0]

    projected = project_tile_detection(
        tile=tile,
        detection=detection,
        transform=from_origin(100.0, 20.0, 0.1, 0.1),
        crs=CRS.from_epsg(4326),
    )

    assert projected.orig_px_bbox == (220.0, 110.0, 270.0, 140.0)
    assert projected.region_id == "region_00002"
    assert projected.source_crs == "EPSG:4326"
    assert projected.wgs84_polygon == (
        (122.0, 9.0),
        (127.0, 9.0),
        (127.0, 6.0),
        (122.0, 6.0),
        (122.0, 9.0),
    )


def test_run_pipeline_sync_exports_dashboard_and_state(tmp_path: Path) -> None:
    orthomosaic_path = tmp_path / "sample.tif"
    output_dir = tmp_path / "outputs"
    _write_sample_orthomosaic(orthomosaic_path)

    class FakeRunner:
        def __init__(self) -> None:
            self.calls = 0

        async def run_prompt(self, prompt: str, image: np.ndarray) -> str:
            del prompt, image
            self.calls += 1
            return json.dumps(
                {
                    "detections": [
                        {
                            "label": "fallen_tree",
                            "score": 0.91,
                            "bbox": [16, 20, 48, 56],
                            "reason": "疑似大面积倒伏",
                        }
                    ]
                }
            )

    runner = FakeRunner()
    summary = run_pipeline_sync(
        config=OrthomosaicTreeDamageConfig(
            orthomosaic_path=orthomosaic_path,
            output_dir=output_dir,
            region_size=192,
            region_overlap=0,
            tile_size=96,
            overlap=0,
            tree_region_mode="heuristic",
            overview_max_size=512,
        ),
        runner=runner,
    )

    assert summary["total_region_count"] == 4
    assert summary["tree_region_count"] == 2
    assert summary["damage_done_region_count"] == 2
    assert runner.calls == 8
    assert (output_dir / "dashboard" / "index.html").exists()
    assert (output_dir / "dashboard" / "overview.jpg").exists()
    assert (output_dir / "region_status.jsonl").exists()
    assert (output_dir / "damage_tile_status.jsonl").exists()
    assert (output_dir / "label_studio_tasks.json").exists()
    dashboard_html = (output_dir / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert 'id="region-search"' in dashboard_html
    assert 'id="focus-first-match"' in dashboard_html
    assert 'data-filter="positive"' in dashboard_html

    dashboard_data = json.loads(
        (output_dir / "dashboard" / "dashboard_data.json").read_text(encoding="utf-8")
    )
    assert dashboard_data["summary"]["tree_region_count"] == 2
    assert dashboard_data["source_image"] == {"width": 384, "height": 384}
    assert dashboard_data["overview_image"]["width"] <= 384
    assert dashboard_data["overview_image"]["height"] <= 384
    assert len(dashboard_data["regions"]) == 4
    assert dashboard_data["detections"]


def test_log_llm_output_emits_raw_response_when_enabled(monkeypatch: object) -> None:
    logged_messages: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_info(*args: object, **kwargs: object) -> None:
        logged_messages.append((args, kwargs))

    monkeypatch.setattr(orthomosaic_tree_damage.logger, "info", fake_info)

    orthomosaic_tree_damage._log_llm_output(
        enabled=True,
        stage="damage_tile",
        item_id="region_00001_tile_0001",
        response_text='{"detections":[]}',
    )

    assert len(logged_messages) == 1
    args, kwargs = logged_messages[0]
    assert kwargs == {}
    assert args == (
        "大模型输出 stage={} item_id={}\n{}",
        "damage_tile",
        "region_00001_tile_0001",
        '{"detections":[]}',
    )


def test_run_pipeline_sync_limits_llm_parallelism_to_configured_value(tmp_path: Path) -> None:
    orthomosaic_path = tmp_path / "sample_parallel.tif"
    output_dir = tmp_path / "outputs_parallel"
    _write_sample_orthomosaic(orthomosaic_path)

    class ParallelTrackingRunner:
        def __init__(self) -> None:
            self.calls = 0
            self.active_calls = 0
            self.max_active_calls = 0

        async def run_prompt(self, prompt: str, image: np.ndarray) -> str:
            del prompt, image
            self.calls += 1
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
            await asyncio.sleep(0.01)
            self.active_calls -= 1
            return json.dumps(
                {
                    "detections": [
                        {
                            "label": "fallen_tree",
                            "score": 0.91,
                            "bbox": [16, 20, 48, 56],
                            "reason": "疑似大面积倒伏",
                        }
                    ]
                }
            )

    runner = ParallelTrackingRunner()
    run_pipeline_sync(
        config=OrthomosaicTreeDamageConfig(
            orthomosaic_path=orthomosaic_path,
            output_dir=output_dir,
            region_size=192,
            region_overlap=0,
            tile_size=96,
            overlap=0,
            tree_region_mode="heuristic",
            llm_max_concurrency=4,
        ),
        runner=runner,
    )

    assert runner.calls == 8
    assert runner.max_active_calls == 4


def test_resume_skips_completed_regions(tmp_path: Path) -> None:
    orthomosaic_path = tmp_path / "sample_resume.tif"
    output_dir = tmp_path / "outputs_resume"
    _write_sample_orthomosaic(orthomosaic_path)

    class CountingRunner:
        def __init__(self) -> None:
            self.calls = 0

        async def run_prompt(self, prompt: str, image: np.ndarray) -> str:
            del prompt, image
            self.calls += 1
            return json.dumps(
                {
                    "detections": [
                        {
                            "label": "diseased_tree",
                            "score": 0.85,
                            "bbox": [12, 12, 40, 40],
                            "reason": "树冠异常发黄",
                        }
                    ]
                }
            )

    first_runner = CountingRunner()
    run_pipeline_sync(
        config=OrthomosaicTreeDamageConfig(
            orthomosaic_path=orthomosaic_path,
            output_dir=output_dir,
            region_size=192,
            region_overlap=0,
            tile_size=96,
            overlap=0,
            tree_region_mode="heuristic",
            max_regions=1,
        ),
        runner=first_runner,
    )
    assert first_runner.calls == 4

    second_runner = CountingRunner()
    summary = run_pipeline_sync(
        config=OrthomosaicTreeDamageConfig(
            orthomosaic_path=orthomosaic_path,
            output_dir=output_dir,
            region_size=192,
            region_overlap=0,
            tile_size=96,
            overlap=0,
            tree_region_mode="heuristic",
        ),
        runner=second_runner,
    )

    assert second_runner.calls == 4
    assert summary["tree_region_count"] == 2
    assert summary["damage_done_region_count"] == 2


def _write_sample_orthomosaic(path: Path) -> None:
    width = 384
    height = 384
    bands = np.zeros((3, height, width), dtype=np.uint8)
    bands[0, :, :] = 110
    bands[1, :, :] = 70
    bands[2, :, :] = 55

    bands[0, :, :192] = 35
    bands[1, :, :192] = 160
    bands[2, :, :192] = 45
    bands[1, 40:340, 20:160] = 200

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=3,
        dtype=np.uint8,
        transform=from_origin(120.0, 30.0, 0.5, 0.5),
        crs="EPSG:4326",
    ) as dataset:
        dataset.write(bands)
