from __future__ import annotations

import pytest

from src.utils.llm import parse_json, parse_response_text


def test_parse_json_parses_plain_json_string() -> None:
    assert parse_json('{"task": "annotate", "count": 2}') == {"task": "annotate", "count": 2}


def test_parse_json_extracts_json_code_block_and_removes_comments() -> None:
    response = """Result:
```json
{
  // line comment
  "task": "annotate",
  /* block comment */
  "count": 2
}
```"""

    assert parse_json(response) == {"task": "annotate", "count": 2}


def test_parse_json_preserves_comment_like_content_inside_strings() -> None:
    response = r"""```json
{
  "url": "https://example.com/path",
  "note": "/* keep this text */"
}
```"""

    assert parse_json(response) == {
        "url": "https://example.com/path",
        "note": "/* keep this text */",
    }


def test_parse_json_extracts_generic_code_block() -> None:
    response = """```
{"status": "ok", "items": [1, 2, 3]}
```"""

    assert parse_json(response) == {"status": "ok", "items": [1, 2, 3]}


def test_parse_json_raises_value_error_for_invalid_input() -> None:
    with pytest.raises(ValueError):
        parse_json("")


def test_parse_json_raises_value_error_for_invalid_json_content() -> None:
    with pytest.raises(ValueError):
        parse_json("not-json")


def test_parse_response_text_prefers_direct_json_and_falls_back_to_markdown_parsing() -> None:
    direct = parse_response_text('{"result": true}')
    fallback = parse_response_text('```json\n{"result": false}\n```')

    assert direct == {"result": True}
    assert fallback == {"result": False}
