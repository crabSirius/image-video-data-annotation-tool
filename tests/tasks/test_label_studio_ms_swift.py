from __future__ import annotations

# ruff: noqa: I001

import json
from pathlib import Path

from label_studio_ms_swift import (
    build_ms_swift_grounding_rows,
    convert_label_studio_export_file,
)
from src.utils.json_io import load_jsonl


def test_build_ms_swift_grounding_rows_splits_rows_per_label_and_resolves_image_paths(
    tmp_path: Path,
) -> None:
    tasks = [
        {
            "id": 1,
            "data": {"image": "/data/local-files/?d=0901/damage_tiles/tile_0001.jpg"},
            "annotations": [
                {
                    "updated_at": "2026-04-15T08:00:00Z",
                    "was_cancelled": False,
                    "result": [
                        _rectangle_result(
                            label="diseased_tree",
                            x=10,
                            y=20,
                            width=30,
                            height=40,
                            original_width=1000,
                            original_height=500,
                        ),
                    ],
                },
                {
                    "updated_at": "2026-04-16T08:00:00Z",
                    "was_cancelled": False,
                    "result": [
                        _rectangle_result(
                            label="diseased_tree",
                            x=12.5,
                            y=10,
                            width=20,
                            height=30,
                            original_width=1000,
                            original_height=500,
                        ),
                        _rectangle_result(
                            label="diseased_tree",
                            x=60,
                            y=20,
                            width=10,
                            height=10,
                            original_width=1000,
                            original_height=500,
                        ),
                        _rectangle_result(
                            label="fallen_tree",
                            x=2,
                            y=5,
                            width=8,
                            height=10,
                            original_width=1000,
                            original_height=500,
                        ),
                    ],
                },
            ],
        },
        {
            "id": 2,
            "data": {"image": "/data/local-files/?d=0901/damage_tiles/tile_0002.jpg"},
            "annotations": [
                {
                    "updated_at": "2026-04-16T09:00:00Z",
                    "was_cancelled": True,
                    "result": [],
                }
            ],
        },
    ]

    rows = build_ms_swift_grounding_rows(
        tasks,
        label_studio_local_files_root=tmp_path / "label_studio_files",
    )

    assert len(rows) == 2
    assert rows[0]["images"] == [str((tmp_path / "label_studio_files/0901/damage_tiles/tile_0001.jpg").resolve())]
    assert rows[0]["objects"] == {
        "ref": ["diseased_tree", "diseased_tree", "diseased_tree"],
        "bbox": [[125.0, 100.0, 325.0, 400.0], [600.0, 200.0, 700.0, 300.0]],
    }
    assert rows[0]["messages"][0] == {
        "role": "user",
        "content": "<image>找到图像中的<ref-object>",
    }
    assert rows[0]["messages"][1]["content"] == (
        "[\n"
        '\t{"bbox_2d": <bbox>, "label": "<ref-object>"},\n'
        '\t{"bbox_2d": <bbox>, "label": "<ref-object>"}\n'
        "]"
    )
    assert rows[1]["objects"] == {
        "ref": ["fallen_tree", "fallen_tree"],
        "bbox": [[20.0, 50.0, 100.0, 150.0]],
    }


def test_build_ms_swift_grounding_rows_filters_unwanted_labels() -> None:
    tasks = [
        {
            "id": 10,
            "data": {"image": "/data/local-files/?d=0901/damage_tiles/tile_0010.jpg"},
            "annotations": [
                {
                    "updated_at": "2026-04-16T10:00:00Z",
                    "was_cancelled": False,
                    "result": [
                        _rectangle_result(
                            label="diseased_tree",
                            x=10,
                            y=10,
                            width=10,
                            height=10,
                            original_width=100,
                            original_height=100,
                        ),
                        _rectangle_result(
                            label="泥石流",
                            x=40,
                            y=40,
                            width=20,
                            height=20,
                            original_width=100,
                            original_height=100,
                        ),
                    ],
                }
            ],
        }
    ]

    rows = build_ms_swift_grounding_rows(tasks, allowed_labels={"diseased_tree"})

    assert len(rows) == 1
    assert rows[0]["objects"] == {
        "ref": ["diseased_tree", "diseased_tree"],
        "bbox": [[100.0, 100.0, 200.0, 200.0]],
    }


def test_convert_label_studio_export_file_writes_jsonl_and_summary(tmp_path: Path) -> None:
    export_path = tmp_path / "export.json"
    output_path = tmp_path / "outputs" / "train.jsonl"
    export_path.write_text(
        json.dumps(
            [
                {
                    "id": 100,
                    "data": {"image": "/data/local-files/?d=0901/damage_tiles/tile_0100.jpg"},
                    "annotations": [
                        {
                            "updated_at": "2026-04-16T11:00:00Z",
                            "was_cancelled": False,
                            "result": [
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
                        }
                    ],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = convert_label_studio_export_file(
        export_path,
        output_path,
        label_studio_local_files_root=tmp_path / "label_studio_files",
    )

    assert summary == {
        "input_path": str(export_path),
        "output_path": str(output_path),
        "total_tasks": 1,
        "exported_samples": 1,
        "exported_images": 1,
        "skipped_tasks_without_boxes": 0,
        "label_counts": {"fallen_tree": 1},
    }
    assert load_jsonl(output_path) == [
        {
            "messages": [
                {"role": "user", "content": "<image>找到图像中的<ref-object>"},
                {
                    "role": "assistant",
                    "content": '[\n\t{"bbox_2d": <bbox>, "label": "<ref-object>"}\n]',
                },
            ],
            "images": [
                str((tmp_path / "label_studio_files/0901/damage_tiles/tile_0100.jpg").resolve())
            ],
            "objects": {
                "ref": ["fallen_tree", "fallen_tree"],
                "bbox": [[10.0, 20.0, 40.0, 60.0]],
            },
        }
    ]


def test_build_ms_swift_grounding_rows_can_include_empty_negatives() -> None:
    tasks = [
        {
            "id": 200,
            "data": {"image": "images/tile_0200.jpg"},
            "annotations": [
                {
                    "updated_at": "2026-04-16T11:00:00Z",
                    "was_cancelled": False,
                    "result": [],
                }
            ],
        }
    ]

    rows = build_ms_swift_grounding_rows(
        tasks,
        allowed_labels={"fallen_tree", "diseased_tree"},
        include_empty_negatives=True,
    )

    assert rows == [
        {
            "messages": [
                {"role": "user", "content": "<image>找到图像中的<ref-object>"},
                {"role": "assistant", "content": "[]"},
            ],
            "images": ["images/tile_0200.jpg"],
            "objects": {"ref": ["diseased_tree"], "bbox": []},
        },
        {
            "messages": [
                {"role": "user", "content": "<image>找到图像中的<ref-object>"},
                {"role": "assistant", "content": "[]"},
            ],
            "images": ["images/tile_0200.jpg"],
            "objects": {"ref": ["fallen_tree"], "bbox": []},
        },
    ]


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
