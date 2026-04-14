from __future__ import annotations

import json
from pathlib import Path

from src.utils.json_io import write_json


def build_dashboard_payload(
    *,
    title: str,
    orthomosaic_path: str,
    overview_image_name: str,
    image_width: int,
    image_height: int,
    summary: dict[str, object],
    regions: list[dict[str, object]],
    detections: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "title": title,
        "orthomosaic_path": orthomosaic_path,
        "overview_image_name": overview_image_name,
        "image": {"width": image_width, "height": image_height},
        "summary": summary,
        "regions": regions,
        "detections": detections,
    }


def write_dashboard(
    output_dir: str | Path,
    payload: dict[str, object],
) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "dashboard_data.json", payload)

    serialized = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = _DASHBOARD_TEMPLATE.replace("__DASHBOARD_DATA__", serialized)
    html_path = output_dir / "index.html"
    html_path.write_text(html, encoding="utf-8")
    return html_path


_DASHBOARD_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Orthomosaic Progress Dashboard</title>
  <style>
    :root {
      --bg: #f4f1e8;
      --panel: rgba(255, 252, 245, 0.94);
      --ink: #182026;
      --muted: #66717e;
      --border: rgba(24, 32, 38, 0.12);
      --shadow: 0 18px 45px rgba(24, 32, 38, 0.12);
      --pending: rgba(100, 116, 139, 0.2);
      --non-tree: rgba(59, 130, 246, 0.34);
      --tree-only: rgba(245, 158, 11, 0.34);
      --running: rgba(251, 191, 36, 0.45);
      --done: rgba(34, 197, 94, 0.28);
      --positive: rgba(239, 68, 68, 0.34);
      --detection: rgba(185, 28, 28, 0.95);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      font-family: "SF Pro Text", "PingFang SC", "Helvetica Neue", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(245, 158, 11, 0.14), transparent 32%),
        radial-gradient(circle at top right, rgba(34, 197, 94, 0.14), transparent 28%),
        linear-gradient(180deg, #fbf7ef 0%, #f4f1e8 100%);
    }

    .layout {
      display: grid;
      grid-template-columns: minmax(320px, 1fr) 360px;
      min-height: 100vh;
      gap: 20px;
      padding: 20px;
    }

    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 22px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }

    .map-panel {
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    .header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      padding: 20px 22px 14px;
      border-bottom: 1px solid var(--border);
    }

    .title {
      margin: 0;
      font-size: 24px;
      line-height: 1.2;
    }

    .subtitle {
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
      word-break: break-all;
    }

    .toolbar {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }

    .toolbar button,
    .toolbar label {
      border: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.8);
      color: var(--ink);
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 13px;
    }

    .toolbar button {
      cursor: pointer;
    }

    .toolbar label {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 12px;
      padding: 18px 22px 0;
    }

    .stat-card {
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 14px 16px;
      background: rgba(255, 255, 255, 0.76);
    }

    .stat-card .label {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    .stat-card .value {
      margin-top: 8px;
      font-size: 28px;
      font-weight: 700;
      line-height: 1;
    }

    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 10px 12px;
      padding: 18px 22px 8px;
    }

    .legend-item {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
    }

    .legend-swatch {
      width: 14px;
      height: 14px;
      border-radius: 999px;
      border: 1px solid rgba(24, 32, 38, 0.18);
    }

    .map-shell {
      flex: 1;
      overflow: auto;
      padding: 14px 22px 22px;
    }

    .scene {
      position: relative;
      transform-origin: top left;
      margin: 0 auto;
      box-shadow: 0 20px 50px rgba(24, 32, 38, 0.16);
      border-radius: 18px;
      overflow: hidden;
      border: 1px solid rgba(24, 32, 38, 0.08);
      background: #d9d2c0;
    }

    .scene img {
      display: block;
      width: 100%;
      height: auto;
      user-select: none;
      pointer-events: none;
    }

    .overlay {
      position: absolute;
      inset: 0;
    }

    .region {
      position: absolute;
      border: 1px solid rgba(24, 32, 38, 0.18);
      cursor: pointer;
      transition: box-shadow 120ms ease, border-color 120ms ease, transform 120ms ease;
    }

    .region:hover,
    .region.selected {
      box-shadow: inset 0 0 0 2px rgba(24, 32, 38, 0.18);
      border-color: rgba(24, 32, 38, 0.45);
      z-index: 3;
    }

    .region.pending { background: var(--pending); }
    .region.non-tree { background: var(--non-tree); }
    .region.tree-only { background: var(--tree-only); }
    .region.running { background: var(--running); }
    .region.done { background: var(--done); }
    .region.positive { background: var(--positive); }

    .detection {
      position: absolute;
      border: 2px solid var(--detection);
      background: rgba(239, 68, 68, 0.06);
      color: #7f1d1d;
      font-size: 11px;
      padding: 2px 4px;
      line-height: 1.1;
      pointer-events: none;
    }

    .sidebar {
      padding: 22px;
      display: flex;
      flex-direction: column;
      gap: 18px;
    }

    .sidebar h2,
    .sidebar h3 {
      margin: 0;
    }

    .detail-card {
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 18px;
      background: rgba(255, 255, 255, 0.78);
    }

    .detail-grid {
      display: grid;
      gap: 10px;
      margin-top: 14px;
    }

    .detail-row {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      font-size: 14px;
    }

    .detail-row .name {
      color: var(--muted);
    }

    .detail-row .value {
      text-align: right;
      word-break: break-word;
    }

    .hint {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }

    .footer-note {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.6;
    }

    @media (max-width: 1200px) {
      .layout {
        grid-template-columns: 1fr;
      }

      .sidebar {
        order: -1;
      }
    }
  </style>
</head>
<body>
  <div class="layout">
    <section class="panel map-panel">
      <div class="header">
        <div>
          <h1 class="title" id="title"></h1>
          <p class="subtitle" id="subtitle"></p>
        </div>
        <div class="toolbar">
          <button type="button" id="zoom-out">缩小</button>
          <button type="button" id="zoom-reset">重置</button>
          <button type="button" id="zoom-in">放大</button>
          <label><input type="checkbox" id="toggle-detections" checked> 显示异常框</label>
        </div>
      </div>

      <div class="stats" id="stats"></div>
      <div class="legend" id="legend"></div>

      <div class="map-shell" id="map-shell">
        <div class="scene" id="scene">
          <img id="overview-image" alt="Orthomosaic overview">
          <div class="overlay" id="region-layer"></div>
          <div class="overlay" id="detection-layer"></div>
        </div>
      </div>
    </section>

    <aside class="panel sidebar">
      <div class="detail-card">
        <h2>区域详情</h2>
        <p class="hint" id="selection-hint">点击左侧任意区域，查看该区域的树木判定与异常检测进度。</p>
        <div class="detail-grid" id="detail-grid"></div>
      </div>

      <div class="detail-card">
        <h3>状态说明</h3>
        <p class="footer-note">
          灰色表示未处理；蓝色表示已判断为非树木区域；金色表示树木区域已确认但异常检测尚未完成；
          绿色表示异常检测已完成且未发现异常；红色表示该区域已发现枯死木或倒伏树。
        </p>
      </div>
    </aside>
  </div>

  <script>
    const DASHBOARD = __DASHBOARD_DATA__;
    const zoomState = { value: 1 };
    let selectedRegionId = null;

    const titleElement = document.getElementById("title");
    const subtitleElement = document.getElementById("subtitle");
    const statsElement = document.getElementById("stats");
    const legendElement = document.getElementById("legend");
    const detailGridElement = document.getElementById("detail-grid");
    const selectionHintElement = document.getElementById("selection-hint");
    const regionLayerElement = document.getElementById("region-layer");
    const detectionLayerElement = document.getElementById("detection-layer");
    const sceneElement = document.getElementById("scene");
    const overviewImageElement = document.getElementById("overview-image");
    const detectionToggleElement = document.getElementById("toggle-detections");

    const legendItems = [
      { label: "未处理", status: "pending" },
      { label: "非树木区域", status: "non-tree" },
      { label: "树木区域待检测", status: "tree-only" },
      { label: "正在处理", status: "running" },
      { label: "已完成无异常", status: "done" },
      { label: "已发现异常", status: "positive" },
    ];

    const legendColors = {
      "pending": "var(--pending)",
      "non-tree": "var(--non-tree)",
      "tree-only": "var(--tree-only)",
      "running": "var(--running)",
      "done": "var(--done)",
      "positive": "var(--positive)",
    };

    const statsConfig = [
      ["总区域数", "total_region_count"],
      ["树木区域", "tree_region_count"],
      ["非树木区域", "non_tree_region_count"],
      ["异常检测完成", "damage_done_region_count"],
      ["发现异常区域", "damage_positive_region_count"],
      ["检测框数量", "detection_count"],
    ];

    function pct(value, total) {
      return `${(value / total) * 100}%`;
    }

    function regionStatus(region) {
      if (region.dashboard_status) {
        return region.dashboard_status;
      }
      return "pending";
    }

    function renderHeader() {
      titleElement.textContent = DASHBOARD.title;
      subtitleElement.textContent = DASHBOARD.orthomosaic_path;
      overviewImageElement.src = DASHBOARD.overview_image_name;
      overviewImageElement.width = DASHBOARD.image.width;
      overviewImageElement.height = DASHBOARD.image.height;
      sceneElement.style.width = `${DASHBOARD.image.width}px`;
    }

    function renderStats() {
      statsElement.innerHTML = "";
      for (const [label, key] of statsConfig) {
        const card = document.createElement("div");
        card.className = "stat-card";
        card.innerHTML = `<div class="label">${label}</div><div class="value">${DASHBOARD.summary[key] ?? 0}</div>`;
        statsElement.appendChild(card);
      }
    }

    function renderLegend() {
      legendElement.innerHTML = "";
      for (const item of legendItems) {
        const el = document.createElement("div");
        el.className = "legend-item";
        el.innerHTML = `<span class="legend-swatch" style="background: ${legendColors[item.status]};"></span>${item.label}`;
        legendElement.appendChild(el);
      }
    }

    function renderRegions() {
      regionLayerElement.innerHTML = "";
      for (const region of DASHBOARD.regions) {
        const element = document.createElement("div");
        element.className = `region ${regionStatus(region)}`;
        if (region.region_id === selectedRegionId) {
          element.classList.add("selected");
        }
        element.style.left = pct(region.col_off, DASHBOARD.image.width);
        element.style.top = pct(region.row_off, DASHBOARD.image.height);
        element.style.width = pct(region.width, DASHBOARD.image.width);
        element.style.height = pct(region.height, DASHBOARD.image.height);
        element.title = `${region.region_id} | ${regionStatus(region)}`;
        element.addEventListener("click", () => {
          selectedRegionId = region.region_id;
          renderRegions();
          renderDetails();
        });
        regionLayerElement.appendChild(element);
      }
    }

    function renderDetections() {
      detectionLayerElement.innerHTML = "";
      if (!detectionToggleElement.checked) {
        return;
      }

      for (const detection of DASHBOARD.detections) {
        const [x0, y0, x1, y1] = detection.orig_px_bbox;
        const element = document.createElement("div");
        element.className = "detection";
        element.style.left = pct(x0, DASHBOARD.image.width);
        element.style.top = pct(y0, DASHBOARD.image.height);
        element.style.width = pct(x1 - x0, DASHBOARD.image.width);
        element.style.height = pct(y1 - y0, DASHBOARD.image.height);
        element.textContent = `${detection.label} ${Number(detection.score).toFixed(2)}`;
        detectionLayerElement.appendChild(element);
      }
    }

    function renderDetails() {
      detailGridElement.innerHTML = "";
      const region = DASHBOARD.regions.find((item) => item.region_id === selectedRegionId);
      if (!region) {
        selectionHintElement.style.display = "block";
        return;
      }

      selectionHintElement.style.display = "none";
      const rows = [
        ["区域 ID", region.region_id],
        ["像素范围", `x=${region.col_off}, y=${region.row_off}, w=${region.width}, h=${region.height}`],
        ["树木阶段", region.tree_stage_status],
        ["树木判定", region.tree_presence === null ? "-" : (region.tree_presence ? "有树木" : "非树木")],
        ["树木得分", region.tree_score ?? "-"],
        ["树木理由", region.tree_reason || "-"],
        ["异常阶段", region.damage_stage_status],
        ["异常进度", `${region.damage_tile_processed}/${region.damage_tile_total}`],
        ["异常数量", region.detection_count],
      ];

      for (const [name, value] of rows) {
        const row = document.createElement("div");
        row.className = "detail-row";
        row.innerHTML = `<span class="name">${name}</span><span class="value">${value}</span>`;
        detailGridElement.appendChild(row);
      }
    }

    function applyZoom() {
      sceneElement.style.transform = `scale(${zoomState.value})`;
    }

    document.getElementById("zoom-in").addEventListener("click", () => {
      zoomState.value = Math.min(zoomState.value + 0.2, 4);
      applyZoom();
    });

    document.getElementById("zoom-out").addEventListener("click", () => {
      zoomState.value = Math.max(zoomState.value - 0.2, 0.4);
      applyZoom();
    });

    document.getElementById("zoom-reset").addEventListener("click", () => {
      zoomState.value = 1;
      applyZoom();
    });

    detectionToggleElement.addEventListener("change", renderDetections);

    renderHeader();
    renderStats();
    renderLegend();
    renderRegions();
    renderDetections();
    renderDetails();
    applyZoom();
  </script>
</body>
</html>
"""
