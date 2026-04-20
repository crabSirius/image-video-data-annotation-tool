from __future__ import annotations

# ruff: noqa: I001

import shutil
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, unquote, urlparse

from label_studio_ms_swift import (
    convert_label_studio_export_file,
    load_label_studio_export_tasks,
    select_latest_submitted_annotation,
)
from src.utils.json_io import write_json

ArchiveFormat = Literal["zip", "tar.gz"]
DEFAULT_LABEL_STUDIO_UPLOAD_ROOT = Path(
    "~/DockerDatas/label-studio/mydata/media/upload"
).expanduser()


def build_label_studio_subset(
    *,
    export_path: str | Path,
    source_image_root: str | Path,
    subset_root: str | Path,
    upload_image_root: str | Path | None = DEFAULT_LABEL_STUDIO_UPLOAD_ROOT,
) -> dict[str, object]:
    export_path = Path(export_path)
    source_image_root = Path(source_image_root)
    subset_root = Path(subset_root)
    resolved_upload_root = Path(upload_image_root).expanduser() if upload_image_root is not None else None

    available_tasks: list[dict[str, Any]] = []
    missing_tasks: list[dict[str, Any]] = []
    copied_image_relpaths: set[str] = set()
    submitted_task_count = 0

    for task in load_label_studio_export_tasks(export_path):
        annotation = select_latest_submitted_annotation(task)
        if annotation is None:
            continue

        submitted_task_count += 1
        image_value = _extract_task_image(task)
        target_image_relpath = _build_subset_image_relative_path(image_value)
        source_image_path = _find_source_image_path(
            image_value,
            source_image_root=source_image_root,
            upload_image_root=resolved_upload_root,
        )
        task_payload = _build_subset_task_payload(task, annotation)

        if source_image_path is None:
            task_payload["missing_subset_image_source"] = image_value
            missing_tasks.append(task_payload)
            continue

        target_image_path = subset_root / target_image_relpath
        target_image_path.parent.mkdir(parents=True, exist_ok=True)
        if target_image_relpath.as_posix() not in copied_image_relpaths:
            shutil.copy2(source_image_path, target_image_path)
            copied_image_relpaths.add(target_image_relpath.as_posix())

        task_payload["data"]["image"] = target_image_relpath.as_posix()
        task_payload["subset_image_source"] = str(source_image_path)
        available_tasks.append(task_payload)

    write_json(subset_root / "label_studio_submitted_tasks_available_images.json", available_tasks)
    write_json(subset_root / "label_studio_submitted_tasks_missing_images.json", missing_tasks)

    summary = {
        "source_export": str(export_path),
        "source_images_root": str(source_image_root),
        "upload_image_root": str(resolved_upload_root) if resolved_upload_root is not None else None,
        "subset_root": str(subset_root),
        "submitted_task_count_in_export": submitted_task_count,
        "available_task_count": len(available_tasks),
        "missing_task_count": len(missing_tasks),
        "copied_image_count": len(copied_image_relpaths),
    }
    write_json(subset_root / "summary.json", summary)
    return summary


def package_dataset_directory(
    dataset_dir: str | Path,
    *,
    archive_format: ArchiveFormat = "zip",
    archive_path: str | Path | None = None,
) -> Path:
    dataset_dir = Path(dataset_dir)
    base_name = _archive_base_name(dataset_dir, archive_format, archive_path)
    shutil.make_archive(
        str(base_name),
        "zip" if archive_format == "zip" else "gztar",
        root_dir=dataset_dir.parent,
        base_dir=dataset_dir.name,
    )
    return Path(f"{base_name}{'.zip' if archive_format == 'zip' else '.tar.gz'}")


def run_label_studio_delivery_pipeline(
    *,
    export_path: str | Path,
    source_image_root: str | Path,
    subset_root: str | Path,
    allowed_labels: set[str],
    upload_image_root: str | Path | None = DEFAULT_LABEL_STUDIO_UPLOAD_ROOT,
    archive_format: ArchiveFormat = "zip",
) -> dict[str, object]:
    subset_root = Path(subset_root)
    subset_summary = build_label_studio_subset(
        export_path=export_path,
        source_image_root=source_image_root,
        subset_root=subset_root,
        upload_image_root=upload_image_root,
    )

    available_tasks_path = subset_root / "label_studio_submitted_tasks_available_images.json"
    ms_swift_root = subset_root / "ms_swift"
    positive_only_path = ms_swift_root / "tree_damage_positive_only.jsonl"
    negatives_path = ms_swift_root / "tree_damage_per_label_with_negatives.jsonl"
    positive_only_summary = convert_label_studio_export_file(
        available_tasks_path,
        positive_only_path,
        allowed_labels=allowed_labels,
    )
    per_label_with_negatives_summary = convert_label_studio_export_file(
        available_tasks_path,
        negatives_path,
        allowed_labels=allowed_labels,
        include_empty_negatives=True,
    )
    archive_path = package_dataset_directory(subset_root, archive_format=archive_format)

    summary = {
        "subset": subset_summary,
        "conversion": {
            "positive_only": positive_only_summary,
            "per_label_with_negatives": per_label_with_negatives_summary,
        },
        "package": {
            "archive_format": archive_format,
            "archive_path": str(archive_path),
        },
    }
    write_json(subset_root / "delivery_pipeline_summary.json", summary)
    return summary


def _build_subset_task_payload(
    task: dict[str, Any],
    annotation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": task.get("id"),
        "annotations": [annotation],
        "data": {"image": _extract_task_image(task)},
    }


def _extract_task_image(task: dict[str, Any]) -> str:
    data = task.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"任务 {task.get('id')} 缺少 data 字段")

    image_value = data.get("image")
    if not isinstance(image_value, str) or not image_value:
        raise ValueError(f"任务 {task.get('id')} 缺少有效的图片路径")
    return image_value


def _build_subset_image_relative_path(image_value: str) -> Path:
    parsed = urlparse(image_value)
    if parsed.path == "/data/local-files/":
        relative_path = parse_qs(parsed.query).get("d", [None])[0]
        if not isinstance(relative_path, str) or not relative_path:
            raise ValueError(f"无法从 Label Studio 图片路径解析相对路径: {image_value}")
        return Path("images") / Path(unquote(relative_path))

    if parsed.path.startswith("/data/upload/"):
        return Path("images") / "upload" / Path(parsed.path.removeprefix("/data/upload/"))

    parsed_path = Path(parsed.path.lstrip("/"))
    if parsed_path.parts:
        return Path("images") / parsed_path
    raise ValueError(f"无法解析图片路径: {image_value}")


def _find_source_image_path(
    image_value: str,
    *,
    source_image_root: Path,
    upload_image_root: Path | None,
) -> Path | None:
    for candidate in _iter_source_image_candidates(
        image_value,
        source_image_root=source_image_root,
        upload_image_root=upload_image_root,
    ):
        if candidate.exists():
            return candidate
    return None


def _iter_source_image_candidates(
    image_value: str,
    *,
    source_image_root: Path,
    upload_image_root: Path | None,
) -> list[Path]:
    parsed = urlparse(image_value)
    candidates: list[Path] = []

    if parsed.path == "/data/local-files/":
        relative_path = parse_qs(parsed.query).get("d", [None])[0]
        if not isinstance(relative_path, str) or not relative_path:
            raise ValueError(f"无法从 Label Studio 图片路径解析相对路径: {image_value}")
        decoded_path = Path(unquote(relative_path))
        candidates.extend([source_image_root / decoded_path, source_image_root / decoded_path.name])
    elif parsed.path.startswith("/data/upload/"):
        upload_relative_path = Path(parsed.path.removeprefix("/data/upload/"))
        if upload_image_root is not None:
            candidates.extend(
                [upload_image_root / upload_relative_path, upload_image_root / upload_relative_path.name]
            )
    else:
        parsed_path = Path(parsed.path.lstrip("/"))
        candidates.extend([source_image_root / parsed_path, source_image_root / parsed_path.name])

    deduped_candidates: list[Path] = []
    seen_paths: set[Path] = set()
    for candidate in candidates:
        if candidate in seen_paths:
            continue
        seen_paths.add(candidate)
        deduped_candidates.append(candidate)
    return deduped_candidates


def _archive_base_name(
    dataset_dir: Path,
    archive_format: ArchiveFormat,
    archive_path: str | Path | None,
) -> Path:
    if archive_path is None:
        return dataset_dir.parent / dataset_dir.name

    archive_path = Path(archive_path)
    if archive_format == "zip":
        return archive_path.with_suffix("") if archive_path.suffix == ".zip" else archive_path
    archive_suffix = "".join(archive_path.suffixes[-2:])
    if archive_suffix == ".tar.gz":
        return archive_path.with_suffix("").with_suffix("")
    return archive_path
