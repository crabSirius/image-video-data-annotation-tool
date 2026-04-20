from __future__ import annotations

# ruff: noqa: E402, I001

import argparse
import json
import sys
from pathlib import Path

_TOOL_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOL_ROOT))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from label_studio_delivery import DEFAULT_LABEL_STUDIO_UPLOAD_ROOT
from label_studio_ms_swift import DEFAULT_PROMPT_TEMPLATE, convert_label_studio_export_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="将 Label Studio 导出标注转换为 ms-swift 训练 Qwen3-VL 可用的 JSONL"
    )
    parser.add_argument("--input", type=Path, required=True, help="Label Studio 导出 JSON 文件")
    parser.add_argument("--output", type=Path, required=True, help="输出 JSONL 路径")
    parser.add_argument(
        "--label-studio-local-files-root",
        type=Path,
        default=None,
        help="Label Studio local-files 的根目录，用于将 /data/local-files/?d=... 映射到真实文件路径",
    )
    parser.add_argument(
        "--label-studio-upload-root",
        type=Path,
        default=DEFAULT_LABEL_STUDIO_UPLOAD_ROOT,
        help="Label Studio upload 媒体根目录，用于将 /data/upload/... 映射到真实文件路径",
    )
    parser.add_argument(
        "--allowed-label",
        action="append",
        default=None,
        help="仅导出指定类别，可重复传入多次",
    )
    parser.add_argument(
        "--prompt-template",
        default=DEFAULT_PROMPT_TEMPLATE,
        help="用户消息模板，使用 {label} 作为类别占位符",
    )
    parser.add_argument(
        "--include-empty-negatives",
        action="store_true",
        help="对 allowed-label 中的每个类别都导出样本，空标注任务会产出空框负样本",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    summary = convert_label_studio_export_file(
        args.input,
        args.output,
        allowed_labels=set(args.allowed_label) if args.allowed_label else None,
        label_studio_local_files_root=args.label_studio_local_files_root,
        label_studio_upload_root=args.label_studio_upload_root,
        prompt_template=args.prompt_template,
        include_empty_negatives=args.include_empty_negatives,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
