from __future__ import annotations

# ruff: noqa: E402, I001

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.core.llm_qwenvl_api_controller import QwenVLAPIController, QwenVLAPIControllerConfig
from src.tasks.orthomosaic_tree_damage import (
    OrthomosaicTreeDamageConfig,
    QwenVLImageRunner,
    run_pipeline_sync,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="正射图树木区域 + 枯死/倒伏两阶段预标注流水线")
    parser.add_argument("--input-path", type=Path, required=True, help="输入 GeoTIFF 正射图路径")
    parser.add_argument("--output-dir", type=Path, required=True, help="输出目录")
    parser.add_argument("--region-size", type=int, default=4096, help="粗粒度区域尺寸，默认 4096")
    parser.add_argument("--region-overlap", type=int, default=0, help="粗粒度区域重叠像素")
    parser.add_argument(
        "--region-preview-size",
        type=int,
        default=512,
        help="树木区域判断时的缩略图最大边长，默认 512",
    )
    parser.add_argument(
        "--tree-region-mode",
        choices=["heuristic", "qwen_vl"],
        default="heuristic",
        help="树木区域判断方式",
    )
    parser.add_argument(
        "--min-tree-region-vegetation-fraction",
        type=float,
        default=0.4,
        help="粗区域最小植被占比阈值",
    )
    parser.add_argument(
        "--min-tree-region-score",
        type=float,
        default=0.2,
        help="粗区域树木判定得分阈值",
    )
    parser.add_argument("--tile-size", type=int, default=1024, help="细粒度检测切片尺寸")
    parser.add_argument("--overlap", type=int, default=128, help="细粒度检测切片重叠像素")
    parser.add_argument(
        "--max-regions",
        type=int,
        default=None,
        help="本次运行最多新增处理多少个区域，便于分批执行",
    )
    parser.add_argument(
        "--max-tiles-per-region",
        type=int,
        default=None,
        help="单个区域最多切多少个细粒度切片",
    )
    parser.add_argument(
        "--min-vegetation-fraction",
        type=float,
        default=0.08,
        help="细粒度切片最小植被占比阈值",
    )
    parser.add_argument(
        "--min-candidate-score",
        type=float,
        default=0.14,
        help="细粒度切片启发式得分阈值",
    )
    parser.add_argument(
        "--min-detection-score",
        type=float,
        default=0.5,
        help="保留检测框的最小置信度",
    )
    parser.add_argument(
        "--label-studio-image-root-url",
        default=None,
        help="导出 Label Studio 任务时使用的图片 URL 前缀",
    )
    parser.add_argument(
        "--labels",
        nargs="+",
        default=["fallen_tree", "diseased_tree"],
        choices=["fallen_tree", "diseased_tree"],
        help="要检测的标签集合",
    )
    parser.add_argument(
        "--overview-max-size",
        type=int,
        default=1800,
        help="dashboard overview 图最大边长",
    )
    parser.add_argument(
        "--dashboard-refresh-interval-regions",
        type=int,
        default=1,
        help="每处理多少个区域刷新一次 dashboard 和导出文件",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只做树木区域判定和细粒度候选准备，不调用异常检测模型",
    )
    parser.add_argument("--llm-scheme", default="http", help="多模态模型服务协议，默认 http")
    parser.add_argument("--llm-host", default="localhost", help="多模态模型服务主机")
    parser.add_argument("--llm-port", type=int, default=3001, help="多模态模型服务端口")
    parser.add_argument(
        "--llm-api-path",
        default="/v1/chat/completions",
        help="兼容 OpenAI 的接口路径",
    )
    parser.add_argument(
        "--llm-model-name",
        default="Qwen/Qwen2.5-VL-32B-Instruct",
        help="模型名称",
    )
    parser.add_argument("--llm-api-key", default=None, help="可选 Bearer Token")
    parser.add_argument(
        "--llm-timeout-seconds",
        type=float,
        default=720.0,
        help="接口超时秒数",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    pipeline_config = OrthomosaicTreeDamageConfig(
        orthomosaic_path=args.input_path,
        output_dir=args.output_dir,
        region_size=args.region_size,
        region_overlap=args.region_overlap,
        region_preview_size=args.region_preview_size,
        tree_region_mode=args.tree_region_mode,
        min_tree_region_vegetation_fraction=args.min_tree_region_vegetation_fraction,
        min_tree_region_score=args.min_tree_region_score,
        tile_size=args.tile_size,
        overlap=args.overlap,
        max_regions=args.max_regions,
        max_tiles_per_region=args.max_tiles_per_region,
        min_vegetation_fraction=args.min_vegetation_fraction,
        min_candidate_score=args.min_candidate_score,
        min_detection_score=args.min_detection_score,
        labels=tuple(args.labels),
        label_studio_image_root_url=args.label_studio_image_root_url,
        overview_max_size=args.overview_max_size,
        dashboard_refresh_interval_regions=args.dashboard_refresh_interval_regions,
    )

    runner = None
    if not args.dry_run:
        controller_config = QwenVLAPIControllerConfig(
            scheme=args.llm_scheme,
            host=args.llm_host,
            port=args.llm_port,
            api_path=args.llm_api_path,
            model_name=args.llm_model_name,
            api_key=args.llm_api_key,
            request_timeout_seconds=args.llm_timeout_seconds,
        )
        runner = QwenVLImageRunner(QwenVLAPIController(controller_config))

    summary = run_pipeline_sync(pipeline_config, runner)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
