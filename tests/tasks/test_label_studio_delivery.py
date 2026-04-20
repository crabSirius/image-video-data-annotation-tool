from __future__ import annotations

# ruff: noqa: I001

import json
from pathlib import Path

from label_studio_delivery import (
    build_label_studio_subset,
    package_dataset_directory,
    run_label_studio_delivery_pipeline,
)
from src.utils.json_io import load_jsonl


def test_build_label_studio_subset_copies_submitted_images_and_tracks_missing_files(
    tmp_path: Path,
) -> None:
    export_path = tmp_path / "export.json"
    source_image_root = tmp_path / "outputs" / "0901" / "damage_tiles"
    upload_image_root = tmp_path / "DockerDatas" / "label-studio" / "mydata" / "media" / "upload"
    source_image_root.mkdir(parents=True)
    (upload_image_root / "1").mkdir(parents=True)
    (source_image_root / "tile_0001.jpg").write_bytes(b"tile-1")
    (source_image_root / "tile_0002.jpg").write_bytes(b"tile-2")
    (upload_image_root / "1" / "upload_only.png").write_bytes(b"upload-1")

    export_path.write_text(
        json.dumps(
            [
                _task(
                    task_id=1,
                    image="/data/local-files/?d=0901/damage_tiles/tile_0001.jpg",
                    annotation=_annotation(
                        updated_at="2026-04-16T10:00:00Z",
                        results=[
                            _rectangle_result(
                                label="fallen_tree",
                                x=1,
                                y=2,
                                width=3,
                                height=4,
                                original_width=1000,
                                original_height=1000,
                            )
                        ],
                    ),
                ),
                _task(
                    task_id=2,
                    image="/data/local-files/?d=0901/damage_tiles/tile_0002.jpg",
                    annotation=_annotation(
                        updated_at="2026-04-16T11:00:00Z",
                        results=[],
                    ),
                ),
                _task(
                    task_id=3,
                    image="/data/local-files/?d=0901/damage_tiles/tile_0003.jpg",
                    annotation=_annotation(
                        updated_at="2026-04-16T12:00:00Z",
                        results=[],
                        was_cancelled=True,
                    ),
                ),
                _task(
                    task_id=4,
                    image="/data/upload/1/upload_only.png",
                    annotation=_annotation(
                        updated_at="2026-04-16T13:00:00Z",
                        results=[
                            _rectangle_result(
                                label="diseased_tree",
                                x=5,
                                y=6,
                                width=7,
                                height=8,
                                original_width=500,
                                original_height=400,
                            )
                        ],
                    ),
                ),
                _task(
                    task_id=5,
                    image="/data/upload/1/missing_upload.png",
                    annotation=_annotation(
                        updated_at="2026-04-16T14:00:00Z",
                        results=[
                            _rectangle_result(
                                label="fallen_tree",
                                x=6,
                                y=7,
                                width=8,
                                height=9,
                                original_width=600,
                                original_height=500,
                            )
                        ],
                    ),
                ),
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = build_label_studio_subset(
        export_path=export_path,
        source_image_root=source_image_root,
        subset_root=tmp_path / "subset",
        upload_image_root=upload_image_root,
    )

    assert summary["submitted_task_count_in_export"] == 4
    assert summary["available_task_count"] == 3
    assert summary["missing_task_count"] == 1
    assert summary["copied_image_count"] == 3
    assert (tmp_path / "subset" / "images" / "0901" / "damage_tiles" / "tile_0001.jpg").exists()
    assert (tmp_path / "subset" / "images" / "upload" / "1" / "upload_only.png").exists()
    available_tasks = json.loads(
        (tmp_path / "subset" / "label_studio_submitted_tasks_available_images.json").read_text(
            encoding="utf-8"
        )
    )
    assert available_tasks[0]["data"]["image"] == "images/0901/damage_tiles/tile_0001.jpg"
    assert available_tasks[2]["data"]["image"] == "images/upload/1/upload_only.png"
    missing_tasks = json.loads(
        (tmp_path / "subset" / "label_studio_submitted_tasks_missing_images.json").read_text(
            encoding="utf-8"
        )
    )
    assert missing_tasks == [
        {
            "id": 5,
            "annotations": [
                _annotation(
                    updated_at="2026-04-16T14:00:00Z",
                    results=[
                        _rectangle_result(
                            label="fallen_tree",
                            x=6,
                            y=7,
                            width=8,
                            height=9,
                            original_width=600,
                            original_height=500,
                        )
                    ],
                )
            ],
            "data": {"image": "/data/upload/1/missing_upload.png"},
            "missing_subset_image_source": "/data/upload/1/missing_upload.png",
        }
    ]


def test_package_dataset_directory_creates_zip_archive(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    (dataset_dir / "summary.json").write_text('{"ok": true}', encoding="utf-8")

    archive_path = package_dataset_directory(dataset_dir, archive_format="zip")

    assert archive_path.exists()
    assert archive_path.suffix == ".zip"


def test_run_label_studio_delivery_pipeline_writes_subset_jsonls_and_archive(
    tmp_path: Path,
) -> None:
    export_path = tmp_path / "export.json"
    source_image_root = tmp_path / "outputs" / "0910" / "damage_tiles"
    source_image_root.mkdir(parents=True)
    (source_image_root / "tile_0100.jpg").write_bytes(b"tile-100")
    (source_image_root / "tile_0101.jpg").write_bytes(b"tile-101")

    export_path.write_text(
        json.dumps(
            [
                _task(
                    task_id=100,
                    image="/data/local-files/?d=0910/damage_tiles/tile_0100.jpg",
                    annotation=_annotation(
                        updated_at="2026-04-17T10:00:00Z",
                        results=[
                            _rectangle_result(
                                label="fallen_tree",
                                x=1,
                                y=2,
                                width=3,
                                height=4,
                                original_width=1000,
                                original_height=1000,
                            )
                        ],
                    ),
                ),
                _task(
                    task_id=101,
                    image="/data/local-files/?d=0910/damage_tiles/tile_0101.jpg",
                    annotation=_annotation(
                        updated_at="2026-04-17T11:00:00Z",
                        results=[],
                    ),
                ),
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = run_label_studio_delivery_pipeline(
        export_path=export_path,
        source_image_root=source_image_root,
        subset_root=tmp_path / "delivery",
        allowed_labels={"fallen_tree", "diseased_tree"},
        archive_format="zip",
    )

    assert summary["subset"]["available_task_count"] == 2
    assert summary["conversion"]["positive_only"]["exported_samples"] == 1
    assert summary["conversion"]["per_label_with_negatives"]["exported_samples"] == 4
    assert Path(str(summary["package"]["archive_path"])).exists()
    assert load_jsonl(tmp_path / "delivery" / "ms_swift" / "tree_damage_positive_only.jsonl") == [
        {
            "messages": [
                {"role": "user", "content": "<image>找到图像中的fallen_tree"},
                {
                    "role": "assistant",
                    "content": '[{"bbox_2d": [10.0, 20.0, 40.0, 60.0], "label": "fallen_tree"}]',
                },
            ],
            "images": ["images/0910/damage_tiles/tile_0100.jpg"],
            "objects": {"ref": ["fallen_tree"], "bbox": [[10.0, 20.0, 40.0, 60.0]]},
        }
    ]
    assert len(
        load_jsonl(tmp_path / "delivery" / "ms_swift" / "tree_damage_per_label_with_negatives.jsonl")
    ) == 4


def _task(task_id: int, image: str, annotation: dict[str, object]) -> dict[str, object]:
    return {
        "id": task_id,
        "annotations": [annotation],
        "data": {"image": image},
    }


def _annotation(
    *,
    updated_at: str,
    results: list[dict[str, object]],
    was_cancelled: bool = False,
) -> dict[str, object]:
    return {
        "updated_at": updated_at,
        "was_cancelled": was_cancelled,
        "result": results,
    }


def _rectangle_result(
    *,
    label: str,
    x: float,
    y: float,
    width: float,
    height: float,
    original_width: int,
    original_height: int,
) -> dict[str, object]:
    return {
        "type": "rectanglelabels",
        "value": {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "rectanglelabels": [label],
        },
        "original_width": original_width,
        "original_height": original_height,
    }
