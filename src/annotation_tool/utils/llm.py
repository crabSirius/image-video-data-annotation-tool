from __future__ import annotations

import json
import re
from typing import cast

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


def parse_json(llm_output: str) -> JsonValue:
    """解析 LLM 输出中的 JSON 内容。"""
    if not llm_output or not isinstance(llm_output, str):
        raise ValueError(f"输入必须是非空字符串，当前输入: {type(llm_output)}")

    # 尝试查找JSON代码块
    json_content = _extract_json_from_markdown(llm_output)

    # 如果没有找到代码块，直接尝试解析整个字符串
    if json_content is None:
        json_content = llm_output.strip()

    # 移除JSON中的注释
    json_content = _remove_comments_from_json(json_content)

    try:
        return cast(JsonValue, json.loads(json_content))
    except json.JSONDecodeError as e:
        # 如果解析失败，记录错误信息并重新抛出异常
        raise ValueError(f"JSON解析失败: {e}，原始内容: {json_content[:100]}...")  # noqa: B904


def _extract_json_from_markdown(text: str) -> str | None:
    """从 Markdown 文本中提取 JSON 代码块。"""
    # 尝试查找 ```json 格式
    json_start = text.find("```json")
    if json_start != -1:
        # 查找这个起始位置之后的第一个 ``` 标记
        json_end = text.find("```", json_start + len("```json"))
        if json_end != -1:
            # 提取并清理JSON内容
            return text[json_start + len("```json") : json_end].strip()

    # 尝试查找普通代码块 ``` 格式
    code_start = text.find("```")
    if code_start != -1:
        # 查找结束标记（跳过起始标记）
        code_end = text.find("```", code_start + len("```"))
        if code_end != -1:
            # 提取并清理代码块内容
            return text[code_start + len("```") : code_end].strip()

    return None


def _remove_comments_from_json(json_str: str) -> str:
    """移除 JSON 字符串中的单行和多行注释。"""
    # 移除单行注释 (// 后面的内容)
    # 注意不匹配字符串内的 // 序列
    pattern = r"//.*?(?=\n|$)"
    json_without_line_comments = re.sub(pattern, "", json_str)

    # 移除多行注释 (/* ... */)
    # 使用非贪婪模式，避免匹配过多内容
    pattern = r"/\*.*?\*/"
    return re.sub(pattern, "", json_without_line_comments, flags=re.DOTALL)


def parse_response_text(text: str) -> JsonValue:
    try:
        return cast(JsonValue, json.loads(text))
    except json.JSONDecodeError:
        return parse_json(text)
