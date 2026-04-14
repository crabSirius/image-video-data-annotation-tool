from __future__ import annotations

import json

import pytest

from src.utils.json_io import (
    append_jsonl,
    load_jsonl,
    load_latest_jsonl_records,
    write_json,
    write_jsonl,
)


def test_write_json_creates_parent_directories_and_writes_utf8_content(tmp_path) -> None:
    target = tmp_path / "nested" / "payload.json"
    payload = {"name": "example", "label": "测试"}

    write_json(target, payload)

    assert json.loads(target.read_text(encoding="utf-8")) == payload


def test_write_jsonl_and_load_jsonl_round_trip_rows(tmp_path) -> None:
    target = tmp_path / "items" / "rows.jsonl"
    rows = [{"id": 1, "name": "alpha"}, {"id": 2, "active": True}]

    write_jsonl(target, rows)

    assert load_jsonl(target) == rows


def test_load_jsonl_returns_empty_list_for_missing_file(tmp_path) -> None:
    assert load_jsonl(tmp_path / "missing.jsonl") == []


def test_load_jsonl_ignores_blank_lines(tmp_path) -> None:
    target = tmp_path / "rows.jsonl"
    target.write_text('\n{"id": 1}\n\n{"id": 2}\n', encoding="utf-8")

    assert load_jsonl(target) == [{"id": 1}, {"id": 2}]


def test_load_jsonl_raises_for_non_object_payloads(tmp_path) -> None:
    target = tmp_path / "invalid.jsonl"
    target.write_text('{"id": 1}\n["bad"]\n', encoding="utf-8")

    with pytest.raises(ValueError):
        load_jsonl(target)


def test_append_jsonl_appends_rows_without_overwriting(tmp_path) -> None:
    target = tmp_path / "events.jsonl"

    append_jsonl(target, {"id": "a", "status": "pending"})
    append_jsonl(target, {"id": "b", "status": "done"})

    assert load_jsonl(target) == [
        {"id": "a", "status": "pending"},
        {"id": "b", "status": "done"},
    ]


def test_load_latest_jsonl_records_keeps_last_row_per_key(tmp_path) -> None:
    target = tmp_path / "events.jsonl"
    target.write_text(
        "\n".join(
            [
                '{"id": "a", "status": "pending"}',
                '{"id": "b", "status": "done"}',
                '{"id": "a", "status": "done"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert load_latest_jsonl_records(target, "id") == {
        "a": {"id": "a", "status": "done"},
        "b": {"id": "b", "status": "done"},
    }
