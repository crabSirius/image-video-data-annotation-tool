from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from src.utils.json_io import write_jsonl

DEFAULT_PROMPT_TEMPLATE = "<image>找到图像中的{label}"


def load_label_studio_export_tasks(input_path: str | Path) -> list[dict[str, Any]]:
    input_path = Path(input_path)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Label Studio 导出文件必须是任务列表")
    return [task for task in payload if isinstance(task, dict)]


def build_ms_swift_grounding_rows(
    tasks: list[dict[str, Any]],
    *,
    allowed_labels: set[str] | None = None,
    label_studio_local_files_root: Path | None = None,
    label_studio_upload_root: Path | None = None,
    prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
    include_empty_negatives: bool = False,
) -> list[dict[str, object]]:
    samples = _extract_grounding_samples(
        tasks,
        allowed_labels=allowed_labels,
        label_studio_local_files_root=label_studio_local_files_root,
        label_studio_upload_root=label_studio_upload_root,
        include_empty_negatives=include_empty_negatives,
    )

    rows: list[dict[str, object]] = []
    for sample in samples:
        assistant_payload = [
            {"bbox_2d": bbox, "label": sample["label"]} for bbox in sample["bboxes"]
        ]
        rows.append(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": prompt_template.format(label=sample["label"]),
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps(assistant_payload, ensure_ascii=False),
                    },
                ],
                "images": [sample["image"]],
                "objects": {
                    "ref": [sample["label"]],
                    "bbox": sample["bboxes"],
                },
            }
        )
    return rows


def convert_label_studio_export_file(
    input_path: str | Path,
    output_path: str | Path,
    *,
    allowed_labels: set[str] | None = None,
    label_studio_local_files_root: Path | None = None,
    label_studio_upload_root: Path | None = None,
    prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
    include_empty_negatives: bool = False,
) -> dict[str, object]:
    input_path = Path(input_path)
    output_path = Path(output_path)
    tasks = load_label_studio_export_tasks(input_path)
    samples = _extract_grounding_samples(
        tasks,
        allowed_labels=allowed_labels,
        label_studio_local_files_root=label_studio_local_files_root,
        label_studio_upload_root=label_studio_upload_root,
        include_empty_negatives=include_empty_negatives,
    )
    rows = build_ms_swift_grounding_rows(
        tasks,
        allowed_labels=allowed_labels,
        label_studio_local_files_root=label_studio_local_files_root,
        label_studio_upload_root=label_studio_upload_root,
        prompt_template=prompt_template,
        include_empty_negatives=include_empty_negatives,
    )
    write_jsonl(output_path, rows)

    label_counts: dict[str, int] = {}
    for sample in samples:
        label = sample["label"]
        label_counts[label] = label_counts.get(label, 0) + 1

    exported_task_ids = {sample["task_id"] for sample in samples}
    exported_images = {sample["image"] for sample in samples}
    return {
        "input_path": str(input_path),
        "output_path": str(output_path),
        "total_tasks": len(tasks),
        "exported_samples": len(samples),
        "exported_images": len(exported_images),
        "skipped_tasks_without_boxes": len(tasks) - len(exported_task_ids),
        "label_counts": label_counts,
    }


def _extract_grounding_samples(
    tasks: list[dict[str, Any]],
    *,
    allowed_labels: set[str] | None,
    label_studio_local_files_root: Path | None,
    label_studio_upload_root: Path | None,
    include_empty_negatives: bool,
) -> list[dict[str, Any]]:
    if include_empty_negatives and not allowed_labels:
        raise ValueError("include_empty_negatives=True 时必须提供 allowed_labels")

    samples: list[dict[str, Any]] = []
    normalized_allowed_labels = {label for label in allowed_labels} if allowed_labels else None

    for task in tasks:
        annotation = select_latest_submitted_annotation(task)
        if annotation is None:
            continue

        image_value = _extract_task_image(task)
        image_path = _resolve_image_path(
            image_value,
            label_studio_local_files_root=label_studio_local_files_root,
            label_studio_upload_root=label_studio_upload_root,
        )
        grouped_bboxes: dict[str, list[list[float]]] = defaultdict(list)

        for result in annotation.get("result", []):
            if not isinstance(result, dict) or result.get("type") != "rectanglelabels":
                continue

            label = _extract_rectangle_label(result)
            if label is None:
                continue
            if normalized_allowed_labels is not None and label not in normalized_allowed_labels:
                continue

            grouped_bboxes[label].append(_rectangle_result_to_bbox(result, task_id=task.get("id")))

        labels_to_export = (
            sorted(normalized_allowed_labels)
            if normalized_allowed_labels and include_empty_negatives
            else sorted(grouped_bboxes)
        )
        for label in labels_to_export:
            if not include_empty_negatives and not grouped_bboxes.get(label):
                continue
            samples.append(
                {
                    "task_id": task.get("id"),
                    "image": image_path,
                    "label": label,
                    "bboxes": grouped_bboxes.get(label, []),
                }
            )

    return samples


def select_latest_submitted_annotation(task: dict[str, Any]) -> dict[str, Any] | None:
    annotations = task.get("annotations", [])
    if not isinstance(annotations, list):
        raise ValueError(f"任务 {task.get('id')} 的 annotations 必须是列表")

    submitted_annotations = [
        annotation
        for annotation in annotations
        if isinstance(annotation, dict)
        and not bool(annotation.get("was_cancelled"))
        and isinstance(annotation.get("result"), list)
    ]
    if not submitted_annotations:
        return None

    return max(submitted_annotations, key=_annotation_sort_key)


def _annotation_sort_key(annotation: dict[str, Any]) -> str:
    updated_at = annotation.get("updated_at")
    if isinstance(updated_at, str):
        return updated_at
    created_at = annotation.get("created_at")
    if isinstance(created_at, str):
        return created_at
    return ""


def _extract_task_image(task: dict[str, Any]) -> str:
    data = task.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"任务 {task.get('id')} 缺少 data 字段")

    image_value = data.get("image")
    if not isinstance(image_value, str) or not image_value:
        raise ValueError(f"任务 {task.get('id')} 缺少有效的图片路径")
    return image_value


def _resolve_image_path(
    image_value: str,
    *,
    label_studio_local_files_root: Path | None,
    label_studio_upload_root: Path | None,
) -> str:
    parsed = urlparse(image_value)
    if parsed.path == "/data/local-files/":
        relative_path = parse_qs(parsed.query).get("d", [None])[0]
        if not isinstance(relative_path, str) or not relative_path:
            raise ValueError(f"无法从 Label Studio 图片路径解析相对路径: {image_value}")

        decoded_relative_path = unquote(relative_path)
        if label_studio_local_files_root is None:
            return decoded_relative_path

        return str((label_studio_local_files_root / decoded_relative_path).expanduser().resolve())

    if parsed.path.startswith("/data/upload/"):
        upload_relative_path = Path(parsed.path.removeprefix("/data/upload/"))
        if label_studio_upload_root is None:
            return Path("upload") / upload_relative_path
        return str((label_studio_upload_root / upload_relative_path).expanduser().resolve())

    return image_value


def _extract_rectangle_label(result: dict[str, Any]) -> str | None:
    value = result.get("value")
    if not isinstance(value, dict):
        raise ValueError("rectanglelabels 结果缺少 value")

    labels = value.get("rectanglelabels")
    if not isinstance(labels, list) or not labels:
        return None

    first_label = labels[0]
    if not isinstance(first_label, str) or not first_label:
        return None
    return first_label


def _rectangle_result_to_bbox(result: dict[str, Any], *, task_id: object) -> list[float]:
    value = result.get("value")
    if not isinstance(value, dict):
        raise ValueError(f"任务 {task_id} 的矩形框缺少 value")

    x = _require_number(value.get("x"), field_name="x", task_id=task_id)
    y = _require_number(value.get("y"), field_name="y", task_id=task_id)
    width = _require_number(value.get("width"), field_name="width", task_id=task_id)
    height = _require_number(value.get("height"), field_name="height", task_id=task_id)
    original_width = _require_number(
        result.get("original_width"),
        field_name="original_width",
        task_id=task_id,
    )
    original_height = _require_number(
        result.get("original_height"),
        field_name="original_height",
        task_id=task_id,
    )

    x1 = round(original_width * x / 100, 2)
    y1 = round(original_height * y / 100, 2)
    x2 = round(x1 + original_width * width / 100, 2)
    y2 = round(y1 + original_height * height / 100, 2)
    return [x1, y1, x2, y2]


def _require_number(value: object, *, field_name: str, task_id: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"任务 {task_id} 的字段 {field_name} 缺少有效数值")
    return float(value)
