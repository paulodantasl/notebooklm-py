"""Write takeoff measurements back into a PDF as standard markup annotations.

This closes the loop: measurements drawn in the browser UI (or any export in the
same shape, see :mod:`pdf_takeoff.ingest`) become real PDF annotations that open
in Bluebeam / Adobe / Preview and re-extract through :mod:`pdf_takeoff.extract`.

Coordinate note: the UI stores geometry in **PDF user space** (origin bottom-left,
y up — what ``PDF.js`` ``convertToPdfPoint`` returns). PyMuPDF places annotations
in **top-left** space (y down), so every point is flipped ``y -> page_height - y``.
Distances/areas are flip-invariant, but placement is not, hence the flip.

A thin 1-foot scale bar labelled ``CAL=1ft`` is added per calibrated sheet so the
output PDF is self-describing and round-trips back to identical quantities.
"""

from __future__ import annotations

import colorsys
from typing import Any

try:
    import fitz  # PyMuPDF
except ImportError as exc:  # pragma: no cover
    raise ImportError("PyMuPDF is required. Install with: pip install pymupdf") from exc

from .model import normalize_unit


def _hue(condition: str) -> int:
    """Mirror the web UI's deterministic hue hash so colors match."""
    h = 0
    for ch in condition or "":
        h = (h * 31 + ord(ch)) % 360
    return h


def color_for(condition: str) -> tuple[float, float, float]:
    """Deterministic RGB (0-1) for a condition, matching the UI's hsl(h,70%,60%)."""
    if not condition:
        return (0.31, 0.61, 1.0)
    r, g, b = colorsys.hls_to_rgb(_hue(condition) / 360.0, 0.60, 0.70)
    return (round(r, 4), round(g, 4), round(b, 4))


def _group_by_sheet(measurements: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for m in measurements:
        out.setdefault(str(m.get("sheet", "p1")), []).append(m)
    return out


def write_annotations(
    pdf_in: str,
    export: dict[str, Any],
    pdf_out: str,
    include_calibration: bool = True,
) -> str:
    """Annotate ``pdf_in`` from an export dict and save to ``pdf_out``.

    ``export`` is the web-UI shape (see :mod:`pdf_takeoff.ingest`). Returns the
    output path.
    """
    if not isinstance(export, dict):
        raise ValueError("export must be a dict (web-UI takeoff JSON).")

    sheets = export.get("sheets") or {}
    _ = normalize_unit(export.get("unit", "ft"))
    by_sheet = _group_by_sheet(export.get("measurements") or [])

    doc = fitz.open(pdf_in)
    try:
        for page in doc:
            sheet = f"p{page.number + 1}"
            height = page.rect.height

            def flip(p: Any) -> tuple[float, float]:
                return (float(p[0]), height - float(p[1]))

            cal = sheets.get(sheet) if isinstance(sheets.get(sheet), dict) else None
            if include_calibration and cal and float(cal.get("points_per_foot", 0)) > 0:
                ppf = float(cal["points_per_foot"])
                # A 1-ft horizontal scale bar near the top-left corner.
                bar = page.add_line_annot((36, 36), (36 + ppf, 36))
                bar.set_info(content="CAL=1ft")
                bar.set_colors(stroke=(1, 0, 0))
                bar.set_border(width=1)
                bar.update()

            for m in by_sheet.get(sheet, []):
                kind = str(m.get("kind", "")).lower()
                condition = (m.get("condition") or "").strip() or "(untitled)"
                color = color_for(condition)
                pts = [flip(p) for p in (m.get("points") or []) if len(p) >= 2]

                if kind == "count":
                    for p in pts:
                        note = page.add_text_annot(p, condition)
                        note.set_info(content=condition)
                        note.update()
                elif kind == "linear" and len(pts) >= 2:
                    a = page.add_polyline_annot(pts)
                    a.set_info(content=condition)
                    a.set_colors(stroke=color)
                    a.set_border(width=2)
                    a.update()
                elif kind == "area" and len(pts) >= 3:
                    a = page.add_polygon_annot(pts)
                    a.set_info(content=condition)
                    a.set_colors(stroke=color, fill=color)
                    a.set_opacity(0.25)
                    a.set_border(width=2)
                    a.update()

        doc.save(pdf_out)
    finally:
        doc.close()
    return pdf_out
