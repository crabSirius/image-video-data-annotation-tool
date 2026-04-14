# Image Video Annotation Tool

这是一个面向图像/视频数据预处理、预标注和审核前准备的工程化仓库。项目按“通用工具层 + 具体任务流水线”组织，方便后续持续扩展新的图像任务、视频任务和不同数据源的预处理流程。

## 能力
- 多模态模型辅助的树木倒伏预标注
- 多模态模型辅助的树木病害预标注

## 已实现功能

- GeoTIFF 正射影像切图。
- 候选窗口启发式打分。
- 检测框回写到原图像素坐标、源 CRS 和 WGS84。
- Label Studio 预标注任务导出。
- Review sample、GeoJSON 和 JSONL 中间产物导出。

## 当前目录结构
- TODO

## 结构约定
- TODO

## 当前任务
- TODO

## 开发方式

安装依赖：

```bash
uv sync --dev
```

运行当前已实现任务：

```bash
uv run python scripts/run_orthomosaic_tree_damage.py
```

运行测试和检查：

```bash
uv run python -m unittest discover -s tests -v
uv run ruff check .
uv run ruff format --check .
```
