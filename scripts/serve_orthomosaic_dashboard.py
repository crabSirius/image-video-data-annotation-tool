from __future__ import annotations

import argparse

from src.visualization.orthomosaic_dashboard_server import serve_dashboard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve orthomosaic dashboard locally")
    parser.add_argument("--output-dir", required=True, help="pipeline 输出目录")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8765, help="监听端口")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    serve_dashboard(args.output_dir, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
