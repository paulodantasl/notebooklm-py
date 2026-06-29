"""Build a Project from the web measuring UI's exported JSON.

The browser app records raw vector geometry **in PDF points** plus a per-sheet
calibration, then exports this shape::

    {
      "pdf_name": "plans.pdf",
      "unit": "ft",
      "sheets": {"p1": {"points_per_foot": 24.0, "method": "calibration-line"}},
      "measurements": [
        {"sheet": "p1", "kind": "linear", "condition": "2x4 wall",
         "points": [[x, y], [x, y]]},
        {"sheet": "p1", "kind": "area",   "condition": "slab",
         "points": [[x, y], ...]},
        {"sheet": "p1", "kind": "count",  "condition": "light",
         "points": [[x, y], [x, y], [x, y]]}
      ]
    }

Quantities are computed here with the *same* geometry helpers the PyMuPDF
extractor uses, so the UI route and the markup route yield identical numbers.
"""

from __future__ import annotations

from typing import Any

from .geometry import polygon_area, polygon_perimeter, seg_length
from .model import KIND_UNIT, Calibration, Measurement, Project, normalize_unit


def _coerce_points(raw: Any) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for p in raw or []:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            pts.append((float(p[0]), float(p[1])))
    return pts


def project_from_export(data: dict[str, Any]) -> Project:
    """Construct a Project from a web-UI export dict."""
    if not isinstance(data, dict):
        raise ValueError("Export must be a JSON object.")

    unit = normalize_unit(data.get("unit", "ft"))
    project = Project(pdf_path=str(data.get("pdf_name", "(web)")), unit=unit)

    for sheet, spec in (data.get("sheets") or {}).items():
        if not isinstance(spec, dict):
            continue
        ppf = spec.get("points_per_foot")
        if ppf is None or float(ppf) <= 0:
            continue
        project.calibrations[sheet] = Calibration(
            sheet=sheet,
            points_per_foot=float(ppf),
            method=str(spec.get("method", "calibration-line")),
            source_unit=str(spec.get("source_unit", unit)),
        )

    counter = 0
    for m in data.get("measurements") or []:
        sheet = str(m.get("sheet", "p1"))
        kind = str(m.get("kind", "")).lower()
        condition = (m.get("condition") or "").strip() or "(untitled)"
        page = int(m.get("page", 0))
        pts = _coerce_points(m.get("points"))
        counter += 1
        mid = f"m{counter:04d}"

        if kind == "count":
            qty = float(m.get("count", len(pts) or 1))
            project.measurements.append(
                Measurement(
                    id=mid, sheet=sheet, page=page, kind="count",
                    condition=condition, quantity=qty, unit=KIND_UNIT["count"],
                )
            )
            continue

        cal = project.calibrations.get(sheet)
        if cal is None:
            project.warnings.append(
                f"Sheet '{sheet}': measurement '{condition}' skipped — sheet not calibrated."
            )
            continue
        ppf = cal.points_per_foot

        if kind == "linear":
            if len(pts) < 2:
                continue
            raw = seg_length(pts)
            project.measurements.append(
                Measurement(
                    id=mid, sheet=sheet, page=page, kind="linear",
                    condition=condition, quantity=raw / ppf, unit=KIND_UNIT["linear"],
                    raw_points=raw,
                )
            )
        elif kind == "area":
            if len(pts) < 3:
                continue
            raw = polygon_area(pts)
            project.measurements.append(
                Measurement(
                    id=mid, sheet=sheet, page=page, kind="area",
                    condition=condition, quantity=raw / (ppf * ppf), unit=KIND_UNIT["area"],
                    perimeter=polygon_perimeter(pts) / ppf, raw_points=raw,
                )
            )
        else:
            project.warnings.append(f"Unknown measurement kind '{kind}' skipped.")

    return project
