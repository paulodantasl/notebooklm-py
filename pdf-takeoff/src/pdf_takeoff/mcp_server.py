"""MCP server exposing the PDF takeoff pipeline to Claude Desktop.

Run (configured in Claude Desktop, see README):
    python -m pdf_takeoff.mcp_server

The server holds one active project in memory. A typical Claude conversation:

    load_project("/path/plans.pdf")        -> extraction summary + any warnings
    quantity_summary()                     -> executive QTO (Markdown)
    load_assemblies("data/assemblies.json")
    load_costdb("data/costdb.json")
    estimate(markup_pct=0.15)              -> priced estimate (Markdown)

All numbers come from vector geometry + calibration, so Claude reasons over
exact quantities rather than reading the drawing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from .catalog import division_map_from_assemblies, load_json
from .estimate import build_estimate
from .extract import extract_project
from .ingest import project_from_export
from .model import Project
from .quantities import rollup, summary_to_rows
from .report import estimate_markdown, summary_csv, summary_markdown

mcp = FastMCP("pdf-takeoff")


@dataclass
class _State:
    project: Optional[Project] = None
    pdf_path: Optional[str] = None  # set only for the PDF-extraction route
    unit: str = "ft"
    manual_calibrations: dict[str, float] = field(default_factory=dict)
    assemblies: dict[str, Any] = field(default_factory=dict)
    costdb: dict[str, Any] = field(default_factory=dict)
    unit_prices: dict[str, Any] = field(default_factory=dict)
    waste: dict[str, float] = field(default_factory=dict)


STATE = _State()


def _require_project() -> Project:
    if STATE.project is None:
        raise ValueError(
            "No project loaded. Call load_project(pdf_path) or load_measurements(json_path) first."
        )
    return STATE.project


def _project_summary(project: Project) -> str:
    summary = {
        "pdf_path": project.pdf_path,
        "sheets": project.sheets(),
        "calibrations": {
            s: {"points_per_foot": round(c.points_per_foot, 4), "method": c.method}
            for s, c in project.calibrations.items()
        },
        "conditions": project.conditions(),
        "measurement_count": len(project.measurements),
        "warnings": project.warnings,
    }
    return json.dumps(summary, indent=2)


@mcp.tool()
def load_project(pdf_path: str, unit: str = "ft") -> str:
    """Extract measurements from a marked-up PDF and make it the active project.

    Args:
        pdf_path: Absolute path to the PDF containing markup annotations.
        unit: Real-world base unit for calibration (default "ft").

    Returns a JSON summary: sheets, calibration status, condition list, counts,
    and any warnings (e.g. measurements skipped for missing calibration).
    """
    if pdf_path != STATE.pdf_path:
        STATE.manual_calibrations = {}  # stale manual cals don't carry to a new file
    STATE.pdf_path = pdf_path
    STATE.unit = unit
    project = extract_project(pdf_path, unit=unit, manual_calibrations=STATE.manual_calibrations)
    STATE.project = project
    return _project_summary(project)


@mcp.tool()
def load_measurements(json_path: str) -> str:
    """Load a measurements JSON exported by the web measuring UI as the active project.

    The export carries raw vector geometry (in PDF points) plus per-sheet
    calibration; quantities are computed with the same geometry helpers the PDF
    markup extractor uses, so both routes agree exactly.
    """
    data = load_json(json_path)
    project = project_from_export(data)
    STATE.project = project
    STATE.pdf_path = None  # no source PDF to re-extract from
    return _project_summary(project)


@mcp.tool()
def list_measurements(sheet: Optional[str] = None, condition: Optional[str] = None) -> str:
    """List individual measurements, optionally filtered by sheet and/or condition."""
    project = _require_project()
    rows = [
        m.to_dict()
        for m in project.measurements
        if (sheet is None or m.sheet == sheet)
        and (condition is None or m.condition == condition)
    ]
    return json.dumps(rows, indent=2)


@mcp.tool()
def quantity_summary(fmt: str = "markdown") -> str:
    """Executive quantity take-off rolled up by condition and CSI division.

    Args:
        fmt: "markdown" (default), "csv", or "json".
    """
    project = _require_project()
    division_map = division_map_from_assemblies(STATE.assemblies)
    summary = rollup(project.measurements, waste=STATE.waste, division_map=division_map)
    if fmt == "csv":
        return summary_csv(summary)
    if fmt == "json":
        return json.dumps(summary_to_rows(summary), indent=2)
    return summary_markdown(summary)


@mcp.tool()
def set_waste(condition: str, waste_pct: float) -> str:
    """Set a waste/allowance factor (e.g. 0.10 for 10%) for one condition."""
    STATE.waste[condition] = float(waste_pct)
    return f"Waste for '{condition}' set to {waste_pct * 100:.1f}%."


@mcp.tool()
def set_calibration(sheet: str, real_length: float, points_length: float, unit: str = "ft") -> str:
    """Manually calibrate a sheet when no CAL line was drawn.

    Provide a real-world length and the matching distance in PDF points. For a
    PDF-extraction project this re-extracts with the manual scale applied, so
    measurements that were previously skipped for lack of calibration are picked
    up and existing ones are recomputed.
    """
    from .model import Calibration, TO_FEET, normalize_unit

    if real_length <= 0 or points_length <= 0:
        raise ValueError("real_length and points_length must both be positive.")

    ppf = points_length / (real_length * TO_FEET[normalize_unit(unit)])
    STATE.manual_calibrations[sheet] = ppf

    if STATE.pdf_path is not None:
        STATE.project = extract_project(
            STATE.pdf_path, unit=STATE.unit, manual_calibrations=STATE.manual_calibrations
        )
        return (
            f"Sheet '{sheet}' calibrated at {ppf:.4f} points/ft; PDF re-extracted "
            f"and measurements recomputed."
        )

    # No source PDF (web-import project): set the scale and recompute in place
    # from each measurement's stored raw geometry.
    project = _require_project()
    project.calibrations[sheet] = Calibration(
        sheet=sheet, points_per_foot=ppf, method="manual", source_unit=unit
    )
    recomputed = _recompute_sheet(project, sheet, ppf)
    return (
        f"Sheet '{sheet}' calibrated at {ppf:.4f} points/ft; recomputed {recomputed} "
        f"measurement(s). Measurements dropped on import for missing scale cannot be "
        f"recovered — re-export from the measuring UI with the sheet calibrated."
    )


def _recompute_sheet(project: Project, sheet: str, ppf: float) -> int:
    """Recompute linear/area quantities for a sheet from stored raw geometry."""
    count = 0
    for m in project.measurements:
        if m.sheet != sheet or m.raw_points is None:
            continue
        if m.kind == "linear":
            m.quantity = m.raw_points / ppf
            count += 1
        elif m.kind == "area":
            m.quantity = m.raw_points / (ppf * ppf)
            count += 1
    return count


@mcp.tool()
def load_assemblies(path: str) -> str:
    """Load the assembly catalog (condition -> materials + CSI division)."""
    STATE.assemblies = load_json(path)
    return f"Loaded {len(STATE.assemblies)} assemblies."


@mcp.tool()
def load_costdb(path: str) -> str:
    """Load the cost database (item -> material/labor/equip unit costs)."""
    STATE.costdb = load_json(path)
    return f"Loaded {len(STATE.costdb)} cost items."


@mcp.tool()
def load_unit_prices(path: str) -> str:
    """Load direct unit prices (condition -> price), used when no assembly exists."""
    STATE.unit_prices = load_json(path)
    return f"Loaded {len(STATE.unit_prices)} unit prices."


@mcp.tool()
def estimate(markup_pct: float = 0.0, fmt: str = "markdown") -> str:
    """Price the current quantities into an estimate.

    Args:
        markup_pct: Overhead & profit as a fraction (e.g. 0.15 for 15%).
        fmt: "markdown" (default) or "json".
    """
    project = _require_project()
    division_map = division_map_from_assemblies(STATE.assemblies)
    summary = rollup(project.measurements, waste=STATE.waste, division_map=division_map)
    est = build_estimate(
        summary,
        assemblies=STATE.assemblies,
        costdb=STATE.costdb,
        unit_prices=STATE.unit_prices,
        markup_pct=markup_pct,
    )
    if fmt == "json":
        return json.dumps(
            {
                "lines": [
                    {
                        "division": l.division,
                        "condition": l.condition,
                        "item": l.item,
                        "quantity": l.quantity,
                        "unit": l.unit,
                        "total": l.total,
                    }
                    for l in est.lines
                ],
                "subtotal": est.subtotal,
                "markup": est.markup,
                "grand_total": est.grand_total,
                "by_division": est.by_division(),
                "warnings": est.warnings,
            },
            indent=2,
        )
    return estimate_markdown(est)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
