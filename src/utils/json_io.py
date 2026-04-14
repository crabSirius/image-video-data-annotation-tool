from __future__ import annotations

import json
from pathlib import Path
from typing import cast


def write_json(path: str | Path, payload: object) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def write_jsonl(path: str | Path, rows: list[dict[str, object]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_jsonl(path: str | Path, row: dict[str, object]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_jsonl(path: str | Path) -> list[dict[str, object]]:
    path = Path(path)
    if not path.exists():
        return []

    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = cast(object, json.loads(line))
            if not isinstance(payload, dict):
                raise ValueError(f"JSONL 行必须是对象，当前类型: {type(payload)}")
            rows.append(cast(dict[str, object], payload))
    return rows


def load_latest_jsonl_records(
    path: str | Path,
    key_field: str,
) -> dict[str, dict[str, object]]:
    latest_records: dict[str, dict[str, object]] = {}
    for row in load_jsonl(path):
        key_value = row.get(key_field)
        if not isinstance(key_value, str) or not key_value:
            raise ValueError(f"JSONL 行缺少有效主键字段 {key_field!r}: {row}")
        latest_records[key_value] = row
    return latest_records
