/* PDF Takeoff — in-browser measuring surface.
 *
 * Measurements are stored as raw vector geometry in PDF points (resolution- and
 * zoom-independent) plus a per-sheet calibration. Export produces JSON that the
 * Python pipeline ingests with the same geometry math, so the UI and the markup
 * route yield identical quantities. Everything runs locally; no PDF leaves the
 * browser. PDF.js is loaded from a CDN only to render the page image.
 */
(() => {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const TO_FEET = {
    ft: 1, "'": 1, feet: 1, foot: 1,
    in: 1 / 12, '"': 1 / 12, inch: 1 / 12,
    yd: 3, yard: 3,
    m: 3.280839895, cm: 0.032808399, mm: 0.0032808399,
  };
  const UNIT_ABBR = { linear: "LF", area: "SF", count: "EA" };

  const state = {
    pdfDoc: null,
    pageNum: 1,
    numPages: 0,
    zoom: 1.5,
    page: null,
    viewport: null,
    renderToken: 0,
    tool: "select",
    unit: "ft",
    currentCondition: "",
    measurements: [], // {id, sheet, page, kind, condition, points:[[x,y]], color}
    calibrations: {}, // sheet -> {points_per_foot, method, source_unit}
    conditionColors: {},
    draft: null, // {kind, points:[[x,y]]}
    cursorPdf: null,
    selectedId: null,
    pdfName: "",
    idSeq: 0,
  };

  // ---- element refs ----
  const $ = (id) => document.getElementById(id);
  const canvas = $("pdf-canvas");
  const overlay = $("overlay");
  const committedLayer = mkSvg("g");
  const draftLayer = mkSvg("g");
  overlay.append(committedLayer, draftLayer);

  // ---------------------------------------------------------------- geometry
  const dist = (a, b) => Math.hypot(b[0] - a[0], b[1] - a[1]);
  function pathLen(pts) {
    let s = 0;
    for (let i = 1; i < pts.length; i++) s += dist(pts[i - 1], pts[i]);
    return s;
  }
  function polyArea(pts) {
    if (pts.length < 3) return 0;
    let s = 0;
    for (let i = 0; i < pts.length; i++) {
      const [a, b] = pts[i];
      const [c, d] = pts[(i + 1) % pts.length];
      s += a * d - c * b;
    }
    return Math.abs(s) / 2;
  }
  function polyPerim(pts) {
    if (pts.length < 2) return 0;
    return pathLen(pts) + dist(pts[pts.length - 1], pts[0]);
  }

  function sheetKey() {
    return "p" + state.pageNum;
  }
  function toFeet(unit) {
    const u = (unit || "ft").trim().toLowerCase();
    return TO_FEET[u] != null ? TO_FEET[u] : (TO_FEET[unit] != null ? TO_FEET[unit] : 1);
  }

  // quantity of a single measurement in real units (LF/SF/EA)
  function measQuantity(m) {
    if (m.kind === "count") return m.points.length || 1;
    const cal = state.calibrations[m.sheet];
    if (!cal) return null;
    const ppf = cal.points_per_foot;
    if (m.kind === "linear") return pathLen(m.points) / ppf;
    if (m.kind === "area") return polyArea(m.points) / (ppf * ppf);
    return null;
  }

  // ---------------------------------------------------------------- colors
  function colorFor(condition) {
    if (!condition) return "#4f9cff";
    if (state.conditionColors[condition]) return state.conditionColors[condition];
    let h = 0;
    for (let i = 0; i < condition.length; i++) h = (h * 31 + condition.charCodeAt(i)) % 360;
    const color = `hsl(${h}, 70%, 60%)`;
    state.conditionColors[condition] = color;
    return color;
  }

  // ---------------------------------------------------------------- svg utils
  function mkSvg(tag, attrs) {
    const el = document.createElementNS(SVG_NS, tag);
    if (attrs) for (const k in attrs) el.setAttribute(k, attrs[k]);
    return el;
  }
  function toView(pt) {
    return state.viewport.convertToViewportPoint(pt[0], pt[1]); // [x,y] css px
  }
  function ptsToViewStr(pts) {
    return pts.map((p) => { const v = toView(p); return v[0] + "," + v[1]; }).join(" ");
  }
  function centroidView(pts) {
    let x = 0, y = 0;
    for (const p of pts) { const v = toView(p); x += v[0]; y += v[1]; }
    return [x / pts.length, y / pts.length];
  }

  // ---------------------------------------------------------------- rendering
  async function renderPage() {
    if (!state.pdfDoc) return;
    const token = ++state.renderToken;
    const page = await state.pdfDoc.getPage(state.pageNum);
    if (token !== state.renderToken) return;
    const viewport = page.getViewport({ scale: state.zoom });

    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(viewport.width * dpr);
    canvas.height = Math.floor(viewport.height * dpr);
    canvas.style.width = viewport.width + "px";
    canvas.style.height = viewport.height + "px";
    overlay.setAttribute("width", viewport.width);
    overlay.setAttribute("height", viewport.height);
    overlay.style.width = viewport.width + "px";
    overlay.style.height = viewport.height + "px";

    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    await page.render({
      canvasContext: ctx,
      viewport,
      transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null,
    }).promise;
    if (token !== state.renderToken) return;

    // Commit page/viewport state only once this render has won the race, so an
    // older overlapping render can't leave a stale viewport over a newer canvas.
    state.page = page;
    state.viewport = viewport;

    drawCommitted();
    drawDraft();
    updateChrome();
  }

  function clearLayer(layer) {
    while (layer.firstChild) layer.removeChild(layer.firstChild);
  }

  function drawCommitted() {
    if (!state.viewport) return;
    clearLayer(committedLayer);
    for (const m of state.measurements) {
      if (m.sheet !== sheetKey() || !m.points || !m.points.length) continue;
      const color = m.color || colorFor(m.condition);
      const selected = m.id === state.selectedId;

      if (m.kind === "count") {
        for (const p of m.points) {
          const v = toView(p);
          const c = mkSvg("circle", {
            cx: v[0], cy: v[1], r: 6, fill: color,
            class: "m-count" + (selected ? " selected" : ""),
          });
          c.dataset.id = m.id;
          c.addEventListener("click", onShapeClick);
          committedLayer.appendChild(c);
        }
      } else {
        const tag = m.kind === "area" ? "polygon" : "polyline";
        const shape = mkSvg(tag, {
          points: ptsToViewStr(m.points),
          stroke: color, fill: m.kind === "area" ? color : "none",
          class: "m-shape" + (m.kind === "area" ? " m-area" : "") + (selected ? " selected" : ""),
        });
        shape.dataset.id = m.id;
        shape.addEventListener("click", onShapeClick);
        committedLayer.appendChild(shape);
      }

      // label at centroid
      const q = measQuantity(m);
      const c = centroidView(m.points);
      const label = mkSvg("text", { x: c[0], y: c[1], class: "m-label", "text-anchor": "middle" });
      label.textContent = q == null
        ? m.condition + " (no scale)"
        : `${m.condition} · ${fmt(q)} ${UNIT_ABBR[m.kind]}`;
      committedLayer.appendChild(label);
    }
  }

  function drawDraft() {
    clearLayer(draftLayer);
    if (!state.draft || !state.viewport) return;
    const d = state.draft;
    const live = state.cursorPdf ? d.points.concat([state.cursorPdf]) : d.points;
    const color = d.kind === "calibrate" ? "#ffd166" : colorFor(state.currentCondition);

    if (live.length >= 2) {
      const tag = d.kind === "area" ? "polygon" : "polyline";
      draftLayer.appendChild(mkSvg(tag, {
        points: ptsToViewStr(live),
        stroke: color, fill: "none",
        class: "m-shape m-draft",
      }));
    }
    for (const p of d.points) {
      const v = toView(p);
      draftLayer.appendChild(mkSvg("circle", { cx: v[0], cy: v[1], r: 3.5, fill: color, class: "m-vertex" }));
    }
  }

  // ---------------------------------------------------------------- interaction
  function eventToPdf(e) {
    const rect = overlay.getBoundingClientRect();
    const cssX = e.clientX - rect.left;
    const cssY = e.clientY - rect.top;
    return state.viewport.convertToPdfPoint(cssX, cssY);
  }

  function onShapeClick(e) {
    if (state.tool !== "select") return;
    e.stopPropagation();
    state.selectedId = e.currentTarget.dataset.id;
    drawCommitted();
    renderSidebar();
  }

  overlay.addEventListener("click", (e) => {
    if (!state.viewport) return;
    const pdf = eventToPdf(e);
    const t = state.tool;

    if (t === "select") {
      state.selectedId = null;
      drawCommitted();
      renderSidebar();
      return;
    }
    if (t === "count") {
      const m = newMeasurement("count", [pdf]);
      state.measurements.push(m);
      commitChange();
      return;
    }
    if (t === "calibrate") {
      if (!state.draft) state.draft = { kind: "calibrate", points: [] };
      state.draft.points.push(pdf);
      if (state.draft.points.length === 2) finishCalibration();
      else drawDraft();
      return;
    }
    // linear / area
    if (!state.draft || state.draft.kind !== t) state.draft = { kind: t, points: [] };
    state.draft.points.push(pdf);
    drawDraft();
  });

  overlay.addEventListener("mousemove", (e) => {
    if (!state.viewport || !state.draft) return;
    state.cursorPdf = eventToPdf(e);
    drawDraft();
  });

  overlay.addEventListener("dblclick", (e) => {
    if (state.draft && (state.draft.kind === "linear" || state.draft.kind === "area")) {
      e.preventDefault();
      // The second click of the double-click already pushed a near-duplicate
      // vertex; drop it so a mouse-jitter copy can't survive dedupe().
      if (state.draft.points.length > 1) state.draft.points.pop();
      finishShape();
    }
  });

  function finishShape() {
    const d = state.draft;
    if (!d) return;
    const pts = dedupe(d.points);
    const min = d.kind === "area" ? 3 : 2;
    if (pts.length >= min) {
      state.measurements.push(newMeasurement(d.kind, pts));
      commitChange();
    }
    state.draft = null;
    state.cursorPdf = null;
    drawDraft();
  }

  function finishCalibration() {
    const [a, b] = state.draft.points;
    const pts = dist(a, b);
    state.draft = null;
    drawDraft();
    const answer = window.prompt(
      "Known real length of the line you drew (e.g. 10ft, 20', 3.5m):",
      "10ft"
    );
    if (!answer) return;
    const match = answer.match(/([0-9]*\.?[0-9]+)\s*([a-zA-Z'"]*)/);
    if (!match) { alert("Could not parse length."); return; }
    const value = parseFloat(match[1]);
    const unit = match[2] || state.unit;
    const realFeet = value * toFeet(unit);
    if (!(realFeet > 0) || !(pts > 0)) { alert("Invalid calibration."); return; }
    state.calibrations[sheetKey()] = {
      points_per_foot: pts / realFeet,
      method: "calibration-line",
      source_unit: unit,
    };
    commitChange();
  }

  function dedupe(points) {
    const out = [];
    for (const p of points) {
      const last = out[out.length - 1];
      if (!last || dist(last, p) > 0.5) out.push(p);
    }
    return out;
  }

  function newMeasurement(kind, points) {
    const condition = state.currentCondition.trim() || "(untitled)";
    return {
      id: "m" + (++state.idSeq),
      sheet: sheetKey(),
      page: state.pageNum - 1,
      kind,
      condition,
      points,
      color: colorFor(condition),
    };
  }

  function commitChange() {
    drawCommitted();
    renderSidebar();
  }

  // ---------------------------------------------------------------- sidebar
  function fmt(n) {
    if (n == null) return "—";
    return n.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 });
  }

  function renderSidebar() {
    // condition datalist + color chip
    const dl = $("condition-list");
    clearLayer(dl);
    const conds = new Set(state.measurements.map((m) => m.condition));
    conds.forEach((c) => { const o = document.createElement("option"); o.value = c; dl.appendChild(o); });
    $("condition-color").style.background = colorFor(state.currentCondition || "");

    // live quantities grouped by condition
    const groups = {};
    for (const m of state.measurements) {
      const q = measQuantity(m);
      const g = (groups[m.condition] = groups[m.condition] || { kind: m.kind, qty: 0, color: m.color, missing: false });
      if (q == null) g.missing = true; else g.qty += q;
    }
    const qWrap = $("quantities");
    qWrap.textContent = "";
    const keys = Object.keys(groups).sort();
    if (!keys.length) {
      const p = document.createElement("p");
      p.className = "muted";
      p.textContent = "No measurements yet.";
      qWrap.appendChild(p);
    } else {
      const table = document.createElement("table");
      for (const c of keys) {
        const g = groups[c];
        const tr = document.createElement("tr");
        const td1 = document.createElement("td");
        const sw = document.createElement("span");
        sw.className = "swatch";
        sw.style.background = g.color || colorFor(c);
        td1.appendChild(sw);
        td1.appendChild(document.createTextNode(c));
        const td2 = document.createElement("td");
        td2.className = "num";
        td2.textContent = (g.missing ? "⚠ " : "") + fmt(g.qty) + " " + UNIT_ABBR[g.kind];
        tr.append(td1, td2);
        table.appendChild(tr);
      }
      qWrap.appendChild(table);
    }

    // measurement list
    const list = $("measurement-list");
    list.textContent = "";
    $("meas-count").textContent = state.measurements.length ? `(${state.measurements.length})` : "";
    for (const m of state.measurements) {
      const row = document.createElement("div");
      row.className = "measurement-row" + (m.id === state.selectedId ? " selected" : "");
      const sw = document.createElement("span");
      sw.className = "swatch";
      sw.style.background = m.color || colorFor(m.condition);
      const label = document.createElement("span");
      label.className = "label";
      label.textContent = `${m.sheet} · ${m.condition}`;
      const qty = document.createElement("span");
      qty.className = "qty";
      const q = measQuantity(m);
      qty.textContent = (q == null ? "—" : fmt(q)) + " " + UNIT_ABBR[m.kind];
      row.append(sw, label, qty);
      row.addEventListener("click", () => {
        state.selectedId = m.id;
        if (m.page + 1 !== state.pageNum) { state.pageNum = m.page + 1; renderPage(); }
        else { drawCommitted(); }
        renderSidebar();
      });
      list.appendChild(row);
    }
  }

  function updateChrome() {
    $("page-label").textContent = state.numPages ? `${state.pageNum} / ${state.numPages}` : "— / —";
    $("zoom-label").textContent = Math.round(state.zoom * 100) + "%";
    const cal = state.calibrations[sheetKey()];
    const el = $("cal-status");
    if (cal) {
      el.textContent = `${sheetKey()}: ${cal.points_per_foot.toFixed(2)} pt/ft`;
      el.classList.add("ok");
    } else {
      el.textContent = `${sheetKey()}: not calibrated`;
      el.classList.remove("ok");
    }
    $("prev-page").disabled = state.pageNum <= 1;
    $("next-page").disabled = state.pageNum >= state.numPages;
  }

  // ---------------------------------------------------------------- toolbar
  function setTool(tool) {
    state.tool = tool;
    // Abandon any in-progress draft whose kind no longer matches the active tool
    // (also covers switching to select/count, which have no draft).
    if (!state.draft || state.draft.kind !== tool) {
      state.draft = null;
      state.cursorPdf = null;
      drawDraft();
    }
    document.querySelectorAll(".tool").forEach((b) =>
      b.classList.toggle("active", b.dataset.tool === tool)
    );
    overlay.classList.toggle("select-mode", tool === "select");
  }
  document.querySelectorAll(".tool").forEach((b) =>
    b.addEventListener("click", () => setTool(b.dataset.tool))
  );

  $("finish-btn").addEventListener("click", finishShape);
  $("undo-btn").addEventListener("click", () => {
    if (state.draft && state.draft.points.length) { state.draft.points.pop(); drawDraft(); }
  });
  $("delete-btn").addEventListener("click", deleteSelected);
  $("prev-page").addEventListener("click", () => { if (state.pageNum > 1) { state.pageNum--; state.selectedId = null; renderPage(); } });
  $("next-page").addEventListener("click", () => { if (state.pageNum < state.numPages) { state.pageNum++; state.selectedId = null; renderPage(); } });
  $("zoom-in").addEventListener("click", () => { state.zoom = Math.min(6, state.zoom * 1.25); renderPage(); });
  $("zoom-out").addEventListener("click", () => { state.zoom = Math.max(0.25, state.zoom / 1.25); renderPage(); });

  $("condition-input").addEventListener("input", (e) => {
    state.currentCondition = e.target.value;
    $("condition-color").style.background = colorFor(state.currentCondition || "");
  });
  $("apply-condition").addEventListener("click", () => {
    if (!state.selectedId) return;
    const m = state.measurements.find((x) => x.id === state.selectedId);
    if (!m) return;
    m.condition = state.currentCondition.trim() || m.condition;
    m.color = colorFor(m.condition);
    commitChange();
  });

  function deleteSelected() {
    if (!state.selectedId) return;
    state.measurements = state.measurements.filter((m) => m.id !== state.selectedId);
    state.selectedId = null;
    commitChange();
  }

  // ---------------------------------------------------------------- files
  $("file-input").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    state.pdfName = file.name;
    const buf = await file.arrayBuffer();
    state.pdfDoc = await pdfjsLib.getDocument({ data: buf }).promise;
    state.numPages = state.pdfDoc.numPages;
    state.pageNum = 1;
    $("empty-hint").style.display = "none";
    await renderPage();
    renderSidebar();
  });

  $("export-btn").addEventListener("click", () => {
    const data = {
      pdf_name: state.pdfName || "(web)",
      unit: state.unit,
      sheets: state.calibrations,
      measurements: state.measurements.map((m) => ({
        sheet: m.sheet, page: m.page, kind: m.kind,
        condition: m.condition, points: m.points, color: m.color,
      })),
      condition_colors: state.conditionColors,
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = (state.pdfName ? state.pdfName.replace(/\.pdf$/i, "") : "takeoff") + ".takeoff.json";
    a.click();
    URL.revokeObjectURL(a.href);
  });

  $("import-input").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      state.unit = data.unit || "ft";
      state.calibrations = data.sheets || {};
      state.conditionColors = data.condition_colors || {};
      state.measurements = (data.measurements || []).map((m) => ({
        id: "m" + (++state.idSeq),
        sheet: m.sheet, page: m.page || 0, kind: m.kind,
        condition: m.condition || "(untitled)",
        points: m.points || [],
        color: m.color || colorFor(m.condition || ""),
      }));
      state.selectedId = null;
      if (state.viewport) drawCommitted();
      renderSidebar();
      updateChrome();
      alert("Imported. Open the matching PDF if it isn't already loaded.");
    } catch (err) {
      alert("Could not read JSON: " + err.message);
    }
  });

  // ---------------------------------------------------------------- keyboard
  document.addEventListener("keydown", (e) => {
    const typing = ["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName);
    if (typing) return;
    const map = { v: "select", c: "calibrate", l: "linear", a: "area", n: "count" };
    if (map[e.key.toLowerCase()]) { setTool(map[e.key.toLowerCase()]); return; }
    if (e.key === "Enter") finishShape();
    else if (e.key === "Escape") { state.draft = null; state.cursorPdf = null; drawDraft(); }
    else if (e.key === "Backspace") {
      if (state.draft && state.draft.points.length) { e.preventDefault(); state.draft.points.pop(); drawDraft(); }
    } else if (e.key === "Delete") deleteSelected();
  });

  // ---------------------------------------------------------------- init
  if (window.pdfjsLib) {
    pdfjsLib.GlobalWorkerOptions.workerSrc =
      "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
  }
  setTool("select");
  renderSidebar();
})();
