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

from label_studio_delivery import package_dataset_directory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="打包已生成的数据集子集目录")
    parser.add_argument("--dataset-dir", type=Path, required=True, help="待打包的数据集目录")
    parser.add_argument(
        "--archive-format",
        choices=["zip", "tar.gz"],
        default="zip",
        help="压缩格式，默认 zip",
    )
    parser.add_argument("--archive-path", type=Path, default=None, help="可选输出压缩包路径")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    archive_path = package_dataset_directory(
        args.dataset_dir,
        archive_format=args.archive_format,
        archive_path=args.archive_path,
    )
    print(
        json.dumps(
            {
                "dataset_dir": str(args.dataset_dir),
                "archive_format": args.archive_format,
                "archive_path": str(archive_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
