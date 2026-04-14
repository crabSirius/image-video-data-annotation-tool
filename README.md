# Image Video Annotation Tool

这是一个面向图像/视频数据预处理、预标注和人工复核前准备的工程化仓库。当前首个落地场景是“大幅正射图上的树木区域筛选 + 树木倒伏/树木病害两阶段预标注”。

## 当前能力

- 将大幅 GeoTIFF 正射图按粗粒度 region 切分，并在低分辨率上判断哪些区域包含树木。
- 只在树木区域内继续切细粒度 tile，做树木倒伏和树木病害检测。
- 支持断点继续。处理中断后，重跑同一个输出目录会自动跳过已完成区域和已完成 tile。
- 导出一个本地可打开的 dashboard，查看全图哪些区域未处理、哪些已完成树木区域判断、哪些已完成异常检测。
- 将检测框回写到原图像素坐标，并同步导出源 CRS 和 WGS84 多边形。
- 导出 Label Studio 预标注任务、GeoJSON、JSONL 和切片样本。

## 目录结构

- `src/utils/`: 通用工具函数，例如几何处理、JSON 读写、LLM 输出解析。
- `src/core/`: 模型服务适配层，例如 Qwen VL API controller。
- `src/tasks/`: 具体任务流水线。当前包含正射图树木异常预标注。
- `scripts/`: 可直接运行的 CLI 入口。
- `tests/`: 单元测试与集成测试。

## 已实现任务

### 正射图树木异常预标注

两阶段流程：

1. 粗筛阶段：先用低分辨率 region 判断是否存在值得继续细查的树木区域。
2. 精查阶段：只在树木区域内切更细的 tile，做枯死木和倒伏树检测。
3. 可视化阶段：把当前处理状态和检测结果渲染到 dashboard 上。

入口脚本：

```bash
uv run python scripts/run_orthomosaic_tree_damage.py \
  --input-path datas/正射图/giuhua_cog_9.1.tif \
  --output-dir outputs
```

```bash
uv run python scripts/run_orthomosaic_tree_damage.py \
  --input-path datas/正射图/giuhua_cog_9.1.tif \
  --output-dir outputs \
  --max-regions 1
```

常用参数：

- `--region-size`: 粗粒度 region 尺寸，默认 `4096`。
- `--region-preview-size`: 树木区域判断时的缩略图最大边长，默认 `512`。
- `--tree-region-mode`: `heuristic` 或 `qwen_vl`。前者速度快、零模型依赖；后者更适合复杂场景。
- `--tile-size`: 细粒度异常检测 tile 尺寸，默认 `1024`。
- `--overlap`: 细粒度 tile 重叠像素，默认 `128`。
- `--max-regions`: 本次运行最多新增处理多少个 region，便于分批跑大图。
- `--dry-run`: 不调用异常检测模型，只生成树木区域判断、候选 tile 和 dashboard。
- `--llm-scheme`、`--llm-host`、`--llm-port`、`--llm-api-path`: 连接你的多模态模型服务。
- `--llm-model-name`: 指定模型名。
- `--llm-api-key`: 可选 Bearer Token。
- `--label-studio-image-root-url`: 如果 Label Studio 通过 HTTP 提供图片，可设置图片 URL 前缀。

示例：

```bash
uv run python scripts/run_orthomosaic_tree_damage.py \
  --orthomosaic ./data/forest_orthomosaic.tif \
  --output-dir ./outputs/tree_damage_run_001 \
  --region-size 4096 \
  --region-preview-size 512 \
  --tree-region-mode qwen_vl \
  --tile-size 1024 \
  --overlap 128 \
  --llm-host 127.0.0.1 \
  --llm-port 3001 \
  --llm-model-name Qwen/Qwen2.5-VL-32B-Instruct
```

## 输出说明

运行后会在输出目录生成：

- `run_manifest.json`: 当前输出目录对应的断点运行配置。
- `region_status.jsonl`: 当前所有 region 的阶段状态。
- `damage_tile_status.jsonl`: 当前所有细粒度 tile 的阶段状态。
- `tile_artifacts.jsonl`: 实际导出的细粒度 tile 文件路径和元数据。
- `detections.jsonl`: 去重后的检测框结果，包含 tile 坐标、原图像素坐标、源 CRS 和 WGS84 信息。
- `detections_wgs84.geojson`: 便于 GIS 工具查看的 GeoJSON 结果。
- `label_studio_tasks.json`: 可导入 Label Studio 的预标注任务文件。
- `summary.json`: 本次运行的统计摘要。
- `dashboard/index.html`: 本地可打开的进度与结果可视化页面。
- `dashboard/overview.jpg`: dashboard 使用的全图缩略图。
- `damage_tiles/`: 导出的细粒度检测 tile JPG 文件。
- `state/`: 断点继续所需的内部事件日志。

## 推荐工作流

1. 先用 `--tree-region-mode heuristic --dry-run` 快速跑一遍，确认粗粒度 region 尺度和 dashboard 表现是否合理。
2. 再切到 `--tree-region-mode qwen_vl` 或你自己的树木区域模型，提升树木区域筛选质量。
3. 接入异常检测模型，继续在同一个 `output-dir` 上重跑，自动续跑未完成区域。
4. 打开 `dashboard/index.html`，检查全图处理进度和异常分布。
5. 用 `label_studio_tasks.json` 做人工复核，整理训练集。

## 关于树木区域模型

当前代码已经支持：

- `heuristic`: 基于植被占比和纹理的快速树木区域筛选，适合第一轮粗筛。
- `qwen_vl`: 复用同一套多模态接口，用低分辨率 region 做树木区域判断。

如果你后面决定接 `SAM` / `SAM2` / `SAM3` 一类分割模型，建议把它接在“粗筛阶段”，输出 region 级树木掩膜或树木覆盖率，再复用当前的断点状态和 dashboard 输出逻辑。

## 开发方式

安装依赖：

```bash
uv sync --dev
```

运行测试和检查：

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```
