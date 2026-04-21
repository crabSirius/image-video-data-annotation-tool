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

from label_studio_delivery import DEFAULT_LABEL_STUDIO_UPLOAD_ROOT, run_label_studio_delivery_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="串联执行 Label Studio 数据集转换、子集生成与打包"
    )
    parser.add_argument("--input", type=Path, required=True, help="Label Studio 导出 JSON 文件")
    parser.add_argument("--source-image-root", type=Path, required=True, help="原始图片根目录")
    parser.add_argument(
        "--upload-image-root",
        type=Path,
        default=DEFAULT_LABEL_STUDIO_UPLOAD_ROOT,
        help="Label Studio upload 图片根目录",
    )
    parser.add_argument("--subset-root", type=Path, required=True, help="输出子集目录")
    parser.add_argument(
        "--allowed-label",
        action="append",
        required=True,
        help="目标类别，可重复传入多次",
    )
    parser.add_argument(
        "--archive-format",
        choices=["zip", "tar.gz"],
        default="zip",
        help="压缩格式，默认 zip",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    summary = run_label_studio_delivery_pipeline(
        export_path=args.input,
        source_image_root=args.source_image_root,
        subset_root=args.subset_root,
        upload_image_root=args.upload_image_root,
        allowed_labels=set(args.allowed_label),
        archive_format=args.archive_format,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
