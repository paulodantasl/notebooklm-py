# pdf-takeoff

Onscreen PDF quantity take-off and estimating, exposed to **Claude** as an MCP
server. You mark up plans in the PDF tool you already use (Bluebeam, Adobe,
Preview); this reads the **vector geometry** of those markups, calibrates them to
real-world units, and hands Claude **exact** quantities to build the executive
quantity summary and the estimate.

## Why this is accurate

Take-off accuracy never depends on Claude "reading" the drawing. It depends on
two things this library handles deterministically:

1. **Scale calibration** — a known points↔feet ratio per sheet.
2. **Vector geometry** — annotation coordinates converted with that scale.

Claude only ever reasons over the resulting numbers (LF / SF / EA), so the
quantities, summary, and pricing are reproducible, not eyeballed.

## Pipeline

```
PDF markups ──extract──> measurements ──rollup──> quantity summary ──price──> estimate
  (you draw)            (vector + scale)         (by condition/CSI)        (assemblies/costs)
```

| Module | Role |
|---|---|
| `extract.py` | Read PyMuPDF annotations → calibrated `Measurement`s |
| `quantities.py` | Roll up by condition + CSI division, apply waste |
| `estimate.py` | Price via assemblies + cost DB, or direct unit prices |
| `report.py` | Markdown / CSV output |
| `mcp_server.py` | Tools Claude calls in Claude Desktop |

## Two ways to measure

1. **Browser measuring UI** (`web/`) — draw measurements directly on the PDF,
   see live quantities, export a `*.takeoff.json` that the pipeline ingests. No
   separate markup tool needed. See [Measure in the browser](#measure-in-the-browser).
2. **Extract from existing PDF markups** — mark up in Bluebeam / Adobe / Preview
   and let `extract.py` read the annotation geometry. See the convention below.

Both routes feed the **same** quantity/estimate code and produce identical
numbers, because geometry is always stored as vectors + a per-sheet scale.

## Markup convention

Draw these in your PDF tool, then save:

- **Calibrate each sheet** — draw one *line* over a known dimension and set its
  comment to `CAL=<length><unit>`, e.g. `CAL=10ft`, `CAL=20'`, `CAL=3.5m`.
  (Or put `SCALE=1/4in=1ft` in any comment to use the drawing scale.)
- **Measure** — the annotation's *comment text is the condition name*
  (e.g. `8in CMU wall`). The geometry decides the kind:
  - line / polyline → **linear** (LF)
  - polygon / rectangle / circle → **area** (SF) + perimeter
  - sticky note / stamp / free text → **count** (1 EA each)
- **Override** the kind with a trailing directive: `@linear`, `@area`, `@count`.

## Install

```bash
cd pdf-takeoff
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest            # 10 tests, builds a sample PDF and verifies exact quantities
```

Generate a sample marked-up PDF to experiment with:

```bash
python examples/make_sample_pdf.py sample_plans.pdf
```

## Use with Claude Desktop

Add to `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "pdf-takeoff": {
      "command": "/absolute/path/pdf-takeoff/.venv/bin/python",
      "args": ["-m", "pdf_takeoff.mcp_server"]
    }
  }
}
```

Restart Claude Desktop. Then in a conversation:

> Load `/Users/me/plans.pdf`, then give me the executive quantity summary.
> Load the assemblies and cost DB from `data/`, set 10% waste on the CMU wall,
> and produce an estimate at 15% overhead & profit.

Claude will call `load_project`, `quantity_summary`, `load_assemblies`,
`load_costdb`, `set_waste`, and `estimate` — and reason over the exact numbers.

### MCP tools

| Tool | Purpose |
|---|---|
| `load_project(pdf_path, unit)` | Extract PDF markups; report sheets, calibration, warnings |
| `load_measurements(json_path)` | Load a `*.takeoff.json` exported by the browser UI |
| `list_measurements(sheet, condition)` | Inspect individual measurements |
| `quantity_summary(fmt)` | Executive QTO by condition + division (md/csv/json) |
| `set_waste(condition, pct)` | Per-condition waste/allowance |
| `set_calibration(sheet, real, points, unit)` | Manual scale when no CAL line |
| `load_assemblies / load_costdb / load_unit_prices` | Load editable JSON catalogs |
| `estimate(markup_pct, fmt)` | Priced estimate with OH&P |
| `write_annotated_pdf(json_path, pdf_in, pdf_out)` | Write UI measurements back into a PDF as Bluebeam/Adobe-readable markups |

## Measure in the browser

A self-contained PDF.js app under `web/` lets you measure on the plan and watch
quantities update live, then export JSON for the pipeline.

```bash
cd pdf-takeoff/web
python -m http.server 8000
# open http://localhost:8000
```

Workflow:

1. **Open PDF** — drag in your plan set (renders locally; nothing is uploaded).
2. **Calibrate** (`C`) — click two points across a known dimension, type its
   real length (`10ft`, `20'`, `3.5m`). Each sheet/page is calibrated separately.
3. **Measure** — pick a tool and type the *condition* in the sidebar first:
   - **Linear** (`L`) — click vertices, double-click / `Enter` to finish → LF
   - **Area** (`A`) — click a polygon, double-click / `Enter` to finish → SF
   - **Count** (`N`) — click each item → EA
   - **Snapping** — the cursor snaps to nearby existing/draft vertices (white
     ring), so shared corners and closed loops line up exactly.
   - **Ortho** — hold **Shift** while drawing to lock the segment to 45°
     increments (horizontal / vertical / diagonal).
   - **Edit** — with **Select** (`V`), click a measurement and drag its vertex
     handles (they snap too); `Del` removes the selected measurement.
4. **Export** → `something.takeoff.json`.
5. In Claude: `load_measurements("/path/something.takeoff.json")` → then
   `quantity_summary()` / `estimate()` exactly as with the markup route.

Shortcuts: `V` select · `C/L/A/N` tools · `Shift` ortho · `Enter` finish ·
`Backspace` undo vertex · `Del` delete selected · `Esc` cancel. The PDF.js
library is loaded from a CDN for rendering only; all measuring and data stay in
your browser.

### Export back to a marked-up PDF

Turn a takeoff into a PDF whose measurements open in Bluebeam / Adobe / Preview
(and re-extract to identical quantities):

```python
from pdf_takeoff import write_annotations
import json
write_annotations("plans.pdf", json.load(open("plans.takeoff.json")), "plans.marked.pdf")
```

or in Claude: `write_annotated_pdf("plans.takeoff.json", "plans.pdf", "plans.marked.pdf")`.
Each condition gets a consistent color; a thin `CAL=1ft` scale bar per sheet
makes the output self-describing.

## Catalogs

Editable JSON under `data/` (examples provided):

- **assemblies** — condition → materials (`factor` = item qty per 1 take-off
  unit, optional `waste`) + CSI `division`.
- **costdb** — item → `material` / `labor` / `equip` unit costs.
- **unit_prices** — condition → single unit price (fallback when no assembly).

## Status & roadmap

Covers the full measure→estimate→back-to-PDF loop two ways (browser UI and
extract-from-markups), with shared quantity/estimate code, snapping + ortho +
vertex editing in the UI, and round-trip annotation export. Natural next steps:
color/layer → condition auto-mapping for imported markups, assembly authoring
helpers, multi-PDF projects, and a cut/cope allowance library.

## License

MIT
