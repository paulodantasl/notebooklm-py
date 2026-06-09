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
| `load_project(pdf_path, unit)` | Extract markups; report sheets, calibration, warnings |
| `list_measurements(sheet, condition)` | Inspect individual measurements |
| `quantity_summary(fmt)` | Executive QTO by condition + division (md/csv/json) |
| `set_waste(condition, pct)` | Per-condition waste/allowance |
| `set_calibration(sheet, real, points, unit)` | Manual scale when no CAL line |
| `load_assemblies / load_costdb / load_unit_prices` | Load editable JSON catalogs |
| `estimate(markup_pct, fmt)` | Priced estimate with OH&P |

## Catalogs

Editable JSON under `data/` (examples provided):

- **assemblies** — condition → materials (`factor` = item qty per 1 take-off
  unit, optional `waste`) + CSI `division`.
- **costdb** — item → `material` / `labor` / `equip` unit costs.
- **unit_prices** — condition → single unit price (fallback when no assembly).

## Status & roadmap

MVP (this folder) covers the full markup→estimate path with the
extract-from-markups workflow. Natural next steps: multi-sheet calibration UX,
a PDF.js measuring UI, color/layer→condition mapping, and assembly authoring
helpers.

## License

MIT
