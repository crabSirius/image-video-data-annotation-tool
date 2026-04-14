from __future__ import annotations

import json
from pathlib import Path

from src.utils.json_io import write_json


def build_dashboard_payload(
    *,
    title: str,
    orthomosaic_path: str,
    overview_image_name: str,
    source_image_width: int,
    source_image_height: int,
    overview_width: int,
    overview_height: int,
    summary: dict[str, object],
    regions: list[dict[str, object]],
    detections: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "title": title,
        "orthomosaic_path": orthomosaic_path,
        "overview_image_name": overview_image_name,
        "source_image": {"width": source_image_width, "height": source_image_height},
        "overview_image": {"width": overview_width, "height": overview_height},
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
      --done: rgba(139, 92, 246, 0.22);
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
      height: 100vh;
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
      min-height: 0;
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
      cursor: grab;
      user-select: none;
    }

    .map-shell.dragging {
      cursor: grabbing;
    }

    .scene {
      position: relative;
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

    #detection-layer {
      pointer-events: none;
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

    .region-label {
      position: absolute;
      left: 50%;
      top: 50%;
      transform: translate(-50%, -50%);
      padding: 2px 6px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.9);
      color: #111827;
      font-size: 11px;
      font-weight: 600;
      line-height: 1;
      white-space: nowrap;
      pointer-events: none;
      box-shadow: 0 2px 10px rgba(24, 32, 38, 0.16);
    }

    .sidebar {
      padding: 22px;
      display: flex;
      flex-direction: column;
      gap: 18px;
      overflow-y: auto;
      min-height: 0;
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

    .filter-controls {
      display: grid;
      gap: 12px;
      margin-top: 14px;
    }

    .filter-input {
      width: 100%;
      border: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.92);
      color: var(--ink);
      border-radius: 14px;
      padding: 12px 14px;
      font-size: 14px;
      outline: none;
    }

    .filter-input:focus {
      border-color: rgba(24, 32, 38, 0.35);
      box-shadow: 0 0 0 4px rgba(24, 32, 38, 0.08);
    }

    .filter-actions,
    .filter-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .filter-button,
    .filter-chip {
      border: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.86);
      color: var(--ink);
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 13px;
      cursor: pointer;
    }

    .filter-chip.active {
      background: rgba(24, 32, 38, 0.92);
      color: white;
      border-color: rgba(24, 32, 38, 0.92);
    }

    .filter-meta {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }

    .region-modal-backdrop {
      display: none;
      position: fixed;
      inset: 0;
      z-index: 1000;
      background: rgba(0, 0, 0, 0.62);
      backdrop-filter: blur(6px);
      justify-content: center;
      align-items: center;
    }

    .region-modal-backdrop.open {
      display: flex;
    }

    .region-modal {
      position: relative;
      max-width: 92vw;
      max-height: 92vh;
      display: flex;
      flex-direction: column;
      background: var(--panel);
      border-radius: 22px;
      box-shadow: 0 24px 60px rgba(0, 0, 0, 0.35);
      overflow: hidden;
    }

    .region-modal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 14px 20px;
      border-bottom: 1px solid var(--border);
      gap: 12px;
    }

    .region-modal-header h3 {
      margin: 0;
      font-size: 16px;
    }

    .region-modal-controls {
      display: flex;
      gap: 8px;
      align-items: center;
    }

    .region-modal-controls button {
      border: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.8);
      color: var(--ink);
      border-radius: 999px;
      padding: 6px 14px;
      font-size: 13px;
      cursor: pointer;
    }

    .region-modal-controls button.active {
      background: rgba(24, 32, 38, 0.92);
      color: white;
      border-color: rgba(24, 32, 38, 0.92);
    }

    .region-modal-close {
      border: none;
      background: none;
      font-size: 22px;
      cursor: pointer;
      color: var(--muted);
      padding: 4px 8px;
      line-height: 1;
    }

    .region-modal-body {
      overflow: auto;
      display: flex;
      justify-content: center;
      align-items: flex-start;
      min-height: 200px;
      padding: 12px;
    }

    .region-image-container {
      position: relative;
      display: inline-block;
      line-height: 0;
    }

    .region-image-container img {
      max-width: 100%;
      max-height: 80vh;
      border-radius: 12px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.12);
      display: block;
    }

    .region-det-box {
      position: absolute;
      border: 2px solid rgba(239, 68, 68, 0.9);
      background: rgba(239, 68, 68, 0.08);
      pointer-events: none;
    }

    .region-det-label {
      position: absolute;
      top: -1px;
      left: -1px;
      background: rgba(185, 28, 28, 0.88);
      color: #fff;
      font-size: 11px;
      line-height: 1;
      padding: 2px 5px;
      border-radius: 0 0 4px 0;
      white-space: nowrap;
      pointer-events: none;
    }

    .region-modal-body .loading-hint {
      color: var(--muted);
      font-size: 14px;
    }

    .view-region-btn {
      margin-top: 14px;
      width: 100%;
      border: 1px solid var(--border);
      background: rgba(24, 32, 38, 0.06);
      color: var(--ink);
      border-radius: 14px;
      padding: 10px 14px;
      font-size: 14px;
      cursor: pointer;
      transition: background 120ms ease;
    }

    .view-region-btn:hover {
      background: rgba(24, 32, 38, 0.12);
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
        <h2>区域筛选</h2>
        <div class="filter-controls">
          <input
            id="region-search"
            class="filter-input"
            type="text"
            placeholder="输入区域编号，例如 region_00012"
          >
          <div class="filter-chips">
            <button type="button" class="filter-chip" data-filter="pending">只看未处理</button>
            <button type="button" class="filter-chip" data-filter="tree">只看树木区</button>
            <button type="button" class="filter-chip" data-filter="positive">只看已发现异常</button>
          </div>
          <div class="filter-actions">
            <button type="button" id="focus-first-match" class="filter-button">定位首个匹配区域</button>
            <button type="button" id="clear-filters" class="filter-button">清空筛选</button>
          </div>
          <div class="filter-meta" id="filter-meta">当前显示全部区域。</div>
        </div>
      </div>

      <div class="detail-card">
        <h2>区域详情</h2>
        <p class="hint" id="selection-hint">点击左侧任意区域，查看该区域的树木判定与异常检测进度。</p>
        <div class="detail-grid" id="detail-grid"></div>
      </div>

      <div class="detail-card">
        <h3>状态说明</h3>
        <p class="footer-note">
          灰色表示未处理；蓝色表示已判断为非树木区域；金色表示树木区域已确认但异常检测尚未完成；
          紫色表示异常检测已完成且未发现异常；红色表示该区域已发现枯死木或倒伏树。
        </p>
      </div>
    </aside>
  </div>

  <div class="region-modal-backdrop" id="region-modal-backdrop">
    <div class="region-modal">
      <div class="region-modal-header">
        <h3 id="region-modal-title">区域原图</h3>
        <div class="region-modal-controls" id="region-modal-controls">
          <button type="button" data-size="512">512</button>
          <button type="button" data-size="1024" class="active">1024</button>
          <button type="button" data-size="2048">2048</button>
          <button type="button" data-size="full">原始</button>
        </div>
        <button class="region-modal-close" id="region-modal-close">&times;</button>
      </div>
      <div class="region-modal-body" id="region-modal-body">
        <span class="loading-hint">请先选中一个区域</span>
      </div>
    </div>
  </div>

  <script>
    const DASHBOARD = __DASHBOARD_DATA__;
    const zoomState = { baseScale: 1, userScale: 1 };
    const filterState = {
      query: "",
      pendingOnly: false,
      treeOnly: false,
      positiveOnly: false,
    };
    const dragState = {
      active: false,
      moved: false,
      startX: 0,
      startY: 0,
      startScrollLeft: 0,
      startScrollTop: 0,
      suppressClickUntil: 0,
    };
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
    const mapShellElement = document.getElementById("map-shell");
    const overviewImageElement = document.getElementById("overview-image");
    const detectionToggleElement = document.getElementById("toggle-detections");
    const regionSearchElement = document.getElementById("region-search");
    const filterMetaElement = document.getElementById("filter-meta");
    const filterChipElements = Array.from(document.querySelectorAll(".filter-chip"));
    const focusFirstMatchElement = document.getElementById("focus-first-match");
    const clearFiltersElement = document.getElementById("clear-filters");

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

    function isPendingRegion(region) {
      return region.dashboard_status === "pending";
    }

    function isTreeRegion(region) {
      return region.tree_presence === true;
    }

    function isPositiveRegion(region) {
      return Number(region.detection_count || 0) > 0;
    }

    function matchesFilters(region) {
      const query = filterState.query.trim().toLowerCase();
      if (query && !String(region.region_id).toLowerCase().includes(query)) {
        return false;
      }

      const enabledPredicates = [];
      if (filterState.pendingOnly) {
        enabledPredicates.push(isPendingRegion(region));
      }
      if (filterState.treeOnly) {
        enabledPredicates.push(isTreeRegion(region));
      }
      if (filterState.positiveOnly) {
        enabledPredicates.push(isPositiveRegion(region));
      }

      if (!enabledPredicates.length) {
        return true;
      }
      return enabledPredicates.some(Boolean);
    }

    function getVisibleRegions() {
      return DASHBOARD.regions.filter(matchesFilters);
    }

    function shouldShowRegionLabels(region, visibleRegionCount) {
      const renderedWidth =
        sceneElement.clientWidth * (Number(region.width) / DASHBOARD.source_image.width);
      const renderedHeight =
        sceneElement.clientHeight * (Number(region.height) / DASHBOARD.source_image.height);
      const showByQuery = filterState.query.trim().length > 0;
      const showByCount = visibleRegionCount <= 24;
      const showByGlobalView = zoomState.userScale <= 1.05 && visibleRegionCount <= 80;
      return (
        (showByQuery || showByCount || showByGlobalView || region.region_id === selectedRegionId) &&
        renderedWidth >= 42 &&
        renderedHeight >= 18
      );
    }

    function renderFilterMeta() {
      const visibleCount = getVisibleRegions().length;
      const totalCount = DASHBOARD.regions.length;
      const activeTags = [];
      if (filterState.query.trim()) {
        activeTags.push(`编号包含 "${filterState.query.trim()}"`);
      }
      if (filterState.pendingOnly) {
        activeTags.push("未处理");
      }
      if (filterState.treeOnly) {
        activeTags.push("树木区");
      }
      if (filterState.positiveOnly) {
        activeTags.push("已发现异常");
      }

      if (!activeTags.length) {
        filterMetaElement.textContent = `当前显示全部区域，共 ${totalCount} 个。`;
        return;
      }

      filterMetaElement.textContent =
        `当前显示 ${visibleCount} / ${totalCount} 个区域，筛选条件：${activeTags.join("、")}。`;
    }

    function updateFilterChips() {
      for (const chip of filterChipElements) {
        const key = chip.dataset.filter;
        const active =
          (key === "pending" && filterState.pendingOnly) ||
          (key === "tree" && filterState.treeOnly) ||
          (key === "positive" && filterState.positiveOnly);
        chip.classList.toggle("active", active);
      }
    }

    function renderHeader() {
      titleElement.textContent = DASHBOARD.title;
      subtitleElement.textContent = DASHBOARD.orthomosaic_path;
      overviewImageElement.src = DASHBOARD.overview_image_name;
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
      const visibleRegions = getVisibleRegions();
      for (const region of visibleRegions) {
        const element = document.createElement("div");
        element.className = `region ${regionStatus(region)}`;
        if (region.region_id === selectedRegionId) {
          element.classList.add("selected");
        }
        element.style.left = pct(region.col_off, DASHBOARD.source_image.width);
        element.style.top = pct(region.row_off, DASHBOARD.source_image.height);
        element.style.width = pct(region.width, DASHBOARD.source_image.width);
        element.style.height = pct(region.height, DASHBOARD.source_image.height);
        element.title = `${region.region_id} | ${regionStatus(region)}`;
        element.addEventListener("click", () => {
          if (Date.now() < dragState.suppressClickUntil) {
            return;
          }
          selectedRegionId = region.region_id;
          renderRegions();
          renderDetails();
          focusRegion(region, { minUserScale: 1.8 });
        });

        if (shouldShowRegionLabels(region, visibleRegions.length)) {
          const label = document.createElement("span");
          label.className = "region-label";
          label.textContent = region.region_id.replace("region_", "R");
          element.appendChild(label);
        }
        regionLayerElement.appendChild(element);
      }
      renderFilterMeta();
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
        element.style.left = pct(x0, DASHBOARD.source_image.width);
        element.style.top = pct(y0, DASHBOARD.source_image.height);
        element.style.width = pct(x1 - x0, DASHBOARD.source_image.width);
        element.style.height = pct(y1 - y0, DASHBOARD.source_image.height);
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

      const viewBtn = document.createElement("button");
      viewBtn.className = "view-region-btn";
      viewBtn.textContent = "查看区域原图";
      viewBtn.addEventListener("click", () => openRegionModal(region));
      detailGridElement.appendChild(viewBtn);
    }

    /* ---- 区域原图弹窗 ---- */
    const modalBackdrop = document.getElementById("region-modal-backdrop");
    const modalTitle = document.getElementById("region-modal-title");
    const modalBody = document.getElementById("region-modal-body");
    const modalControls = document.getElementById("region-modal-controls");
    const modalSizeBtns = Array.from(modalControls.querySelectorAll("button[data-size]"));
    let modalCurrentRegionId = null;
    let modalCurrentSize = "1024";

    let modalCurrentRegion = null;

    function openRegionModal(region) {
      modalCurrentRegionId = region.region_id;
      modalCurrentRegion = region;
      const detCount = getRegionDetections(region).length;
      modalTitle.textContent = `区域原图 — ${region.region_id}` + (detCount > 0 ? ` (${detCount} 个异常)` : "");
      modalCurrentSize = "1024";
      updateModalSizeBtns();
      loadRegionImage();
      modalBackdrop.classList.add("open");
    }

    function closeRegionModal() {
      modalBackdrop.classList.remove("open");
      modalBody.innerHTML = "";
      modalCurrentRegionId = null;
      modalCurrentRegion = null;
    }

    function updateModalSizeBtns() {
      for (const btn of modalSizeBtns) {
        btn.classList.toggle("active", btn.dataset.size === modalCurrentSize);
      }
    }

    function getRegionDetections(region) {
      if (!region) return [];
      const rColOff = Number(region.col_off);
      const rRowOff = Number(region.row_off);
      const rW = Number(region.width);
      const rH = Number(region.height);
      return DASHBOARD.detections.filter((d) => {
        if (d.region_id === region.region_id) return true;
        const [x0, y0] = d.orig_px_bbox;
        return x0 >= rColOff && x0 < rColOff + rW && y0 >= rRowOff && y0 < rRowOff + rH;
      });
    }

    function overlayDetections(container, img, region) {
      const dets = getRegionDetections(region);
      if (!dets.length) return;

      const imgW = img.naturalWidth;
      const imgH = img.naturalHeight;
      const regionW = Number(region.width);
      const regionH = Number(region.height);
      const scaleX = imgW / regionW;
      const scaleY = imgH / regionH;
      const rColOff = Number(region.col_off);
      const rRowOff = Number(region.row_off);

      for (const det of dets) {
        const [ox0, oy0, ox1, oy1] = det.orig_px_bbox;
        const lx = (ox0 - rColOff) * scaleX;
        const ly = (oy0 - rRowOff) * scaleY;
        const bw = (ox1 - ox0) * scaleX;
        const bh = (oy1 - oy0) * scaleY;

        const box = document.createElement("div");
        box.className = "region-det-box";
        box.style.left = `${lx}px`;
        box.style.top = `${ly}px`;
        box.style.width = `${bw}px`;
        box.style.height = `${bh}px`;

        const label = document.createElement("span");
        label.className = "region-det-label";
        label.textContent = `${det.label} ${Number(det.score).toFixed(2)}`;
        box.appendChild(label);

        container.appendChild(box);
      }
    }

    function loadRegionImage() {
      if (!modalCurrentRegionId || !modalCurrentRegion) return;
      modalBody.innerHTML = '<span class="loading-hint">加载中…</span>';
      const sizeParam = modalCurrentSize === "full" ? "" : `&max_size=${modalCurrentSize}`;
      const url = `/api/region-image?region_id=${encodeURIComponent(modalCurrentRegionId)}${sizeParam}`;
      const img = new window.Image();
      const region = modalCurrentRegion;
      img.onload = () => {
        modalBody.innerHTML = "";
        const container = document.createElement("div");
        container.className = "region-image-container";
        container.appendChild(img);
        overlayDetections(container, img, region);
        modalBody.appendChild(container);
      };
      img.onerror = () => {
        modalBody.innerHTML = '<span class="loading-hint">加载失败，请确认 serve 服务已启动并指向正确的输出目录。</span>';
      };
      img.src = url;
    }

    document.getElementById("region-modal-close").addEventListener("click", closeRegionModal);
    modalBackdrop.addEventListener("click", (event) => {
      if (event.target === modalBackdrop) closeRegionModal();
    });

    for (const btn of modalSizeBtns) {
      btn.addEventListener("click", () => {
        modalCurrentSize = btn.dataset.size;
        updateModalSizeBtns();
        loadRegionImage();
      });
    }

    function applyZoom() {
      const scale = zoomState.baseScale * zoomState.userScale;
      const width = Math.max(120, DASHBOARD.overview_image.width * scale);
      const height = Math.max(120, DASHBOARD.overview_image.height * scale);
      sceneElement.style.width = `${width}px`;
      sceneElement.style.height = `${height}px`;
      overviewImageElement.style.width = `${width}px`;
      overviewImageElement.style.height = `${height}px`;
      renderRegions();
    }

    function fitToViewport() {
      const widthScale = Math.max(
        0.05,
        (mapShellElement.clientWidth - 16) / DASHBOARD.overview_image.width
      );
      const heightScale = Math.max(
        0.05,
        (mapShellElement.clientHeight - 16) / DASHBOARD.overview_image.height
      );
      zoomState.baseScale = Math.min(widthScale, heightScale, 1);
      applyZoom();
    }

    function centerOnSourcePoint(sourceX, sourceY) {
      const scaleX = sceneElement.clientWidth / DASHBOARD.source_image.width;
      const scaleY = sceneElement.clientHeight / DASHBOARD.source_image.height;
      const targetX = sourceX * scaleX;
      const targetY = sourceY * scaleY;
      mapShellElement.scrollLeft = Math.max(0, targetX - mapShellElement.clientWidth / 2);
      mapShellElement.scrollTop = Math.max(0, targetY - mapShellElement.clientHeight / 2);
    }

    function focusRegion(region, options = {}) {
      const regionOverviewWidth =
        (Number(region.width) / DASHBOARD.source_image.width) * DASHBOARD.overview_image.width;
      const regionOverviewHeight =
        (Number(region.height) / DASHBOARD.source_image.height) * DASHBOARD.overview_image.height;
      const desiredWidthScale =
        (mapShellElement.clientWidth * 0.58) / Math.max(regionOverviewWidth, 1);
      const desiredHeightScale =
        (mapShellElement.clientHeight * 0.58) / Math.max(regionOverviewHeight, 1);
      const desiredAbsoluteScale = Math.min(desiredWidthScale, desiredHeightScale);
      const minUserScale = options.minUserScale || 1;
      zoomState.userScale = Math.min(
        6,
        Math.max(minUserScale, desiredAbsoluteScale / Math.max(zoomState.baseScale, 0.001))
      );
      applyZoom();
      requestAnimationFrame(() => {
        centerOnSourcePoint(
          Number(region.col_off) + Number(region.width) / 2,
          Number(region.row_off) + Number(region.height) / 2
        );
      });
    }

    function focusFirstMatchingRegion() {
      const firstRegion = getVisibleRegions()[0];
      if (!firstRegion) {
        return;
      }
      selectedRegionId = firstRegion.region_id;
      renderDetails();
      focusRegion(firstRegion, { minUserScale: 1.4 });
    }

    document.getElementById("zoom-in").addEventListener("click", () => {
      zoomState.userScale = Math.min(zoomState.userScale + 0.2, 6);
      applyZoom();
    });

    document.getElementById("zoom-out").addEventListener("click", () => {
      zoomState.userScale = Math.max(zoomState.userScale - 0.2, 0.2);
      applyZoom();
    });

    document.getElementById("zoom-reset").addEventListener("click", () => {
      zoomState.userScale = 1;
      fitToViewport();
    });

    regionSearchElement.addEventListener("input", (event) => {
      filterState.query = event.target.value;
      renderRegions();
    });

    regionSearchElement.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        focusFirstMatchingRegion();
        renderRegions();
      }
    });

    for (const chip of filterChipElements) {
      chip.addEventListener("click", () => {
        const key = chip.dataset.filter;
        if (key === "pending") {
          filterState.pendingOnly = !filterState.pendingOnly;
        } else if (key === "tree") {
          filterState.treeOnly = !filterState.treeOnly;
        } else if (key === "positive") {
          filterState.positiveOnly = !filterState.positiveOnly;
        }
        updateFilterChips();
        renderRegions();
      });
    }

    focusFirstMatchElement.addEventListener("click", () => {
      focusFirstMatchingRegion();
      renderRegions();
    });

    clearFiltersElement.addEventListener("click", () => {
      filterState.query = "";
      filterState.pendingOnly = false;
      filterState.treeOnly = false;
      filterState.positiveOnly = false;
      regionSearchElement.value = "";
      updateFilterChips();
      renderRegions();
    });

    mapShellElement.addEventListener("mousedown", (event) => {
      if (event.button !== 0) {
        return;
      }
      dragState.active = true;
      dragState.moved = false;
      dragState.startX = event.clientX;
      dragState.startY = event.clientY;
      dragState.startScrollLeft = mapShellElement.scrollLeft;
      dragState.startScrollTop = mapShellElement.scrollTop;
      mapShellElement.classList.add("dragging");
    });

    window.addEventListener("mousemove", (event) => {
      if (!dragState.active) {
        return;
      }
      const deltaX = event.clientX - dragState.startX;
      const deltaY = event.clientY - dragState.startY;
      if (Math.abs(deltaX) > 3 || Math.abs(deltaY) > 3) {
        dragState.moved = true;
      }
      mapShellElement.scrollLeft = dragState.startScrollLeft - deltaX;
      mapShellElement.scrollTop = dragState.startScrollTop - deltaY;
    });

    window.addEventListener("mouseup", () => {
      if (!dragState.active) {
        return;
      }
      dragState.active = false;
      mapShellElement.classList.remove("dragging");
      if (dragState.moved) {
        dragState.suppressClickUntil = Date.now() + 120;
      }
    });

    mapShellElement.addEventListener("mouseleave", () => {
      if (!dragState.active) {
        return;
      }
      mapShellElement.classList.remove("dragging");
    });

    detectionToggleElement.addEventListener("change", renderDetections);
    window.addEventListener("resize", fitToViewport);

    renderHeader();
    renderStats();
    renderLegend();
    updateFilterChips();
    renderRegions();
    renderDetections();
    renderDetails();
    fitToViewport();
  </script>
</body>
</html>
"""
