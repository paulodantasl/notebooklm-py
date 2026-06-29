"""Extract measurements from PDF markup annotations using PyMuPDF.

Markup convention (what you draw in Bluebeam / Adobe / Preview):

* **Calibrate a sheet** — draw one *line* and set its comment to
  ``CAL=<length><unit>`` (e.g. ``CAL=10ft``, ``CAL=20'``, ``CAL=3.5m``).
  The drawn line is treated as that real length, fixing the sheet scale.
  Alternatively put ``SCALE=1/4in=1ft`` in any annotation's comment.
* **Tag a measurement** — the annotation's comment text is the *condition*
  (e.g. ``8in CMU wall``). Geometry decides the kind:
    - line / polyline  -> linear (LF)
    - rectangle / polygon / circle -> area (SF) + perimeter
    - sticky-note / stamp / free-text -> count (1 EA each)
  Override with a trailing directive: ``@linear`` / ``@area`` / ``@count``.

Accuracy comes from vector geometry + calibration here — never from reading
pixels. Each measurement keeps its raw point magnitude for auditing.
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable, Optional

try:
    import fitz  # PyMuPDF
except ImportError as exc:  # pragma: no cover - exercised only without the dep
    raise ImportError(
        "PyMuPDF is required for extraction. Install with: pip install pymupdf"
    ) from exc

from .geometry import (
    ellipse_perimeter,
    polygon_area as _polygon_area,
    polygon_perimeter as _polygon_perimeter,
    seg_length as _seg_length,
)
from .model import KIND_UNIT, TO_FEET, Calibration, Measurement, Project, normalize_unit

_CAL_RE = re.compile(r"CAL\s*=\s*([0-9]*\.?[0-9]+)\s*([a-zA-Z'\"]*)", re.IGNORECASE)
_SCALE_RE = re.compile(
    r"SCALE\s*=\s*([0-9]*\.?[0-9/]+)\s*([a-zA-Z'\"]+)\s*=\s*([0-9]*\.?[0-9]+)\s*([a-zA-Z'\"]+)",
    re.IGNORECASE,
)
_DIRECTIVE_RE = re.compile(r"@(linear|area|count)\b", re.IGNORECASE)

# Annotation subtype name -> default measurement kind.
_KIND_BY_TYPE = {
    "Line": "linear",
    "PolyLine": "linear",
    "Polygon": "area",
    "Square": "area",
    "Circle": "area",
    "Text": "count",
    "FreeText": "count",
    "Stamp": "count",
}


def _unit_to_feet(token: str, default_unit: str) -> float:
    token = (token or "").strip()
    if token in TO_FEET:
        return TO_FEET[token]
    low = token.lower()
    if low in TO_FEET:
        return TO_FEET[low]
    return TO_FEET[normalize_unit(default_unit)]


def parse_scale_directive(text: str, default_unit: str) -> Optional[float]:
    """Parse ``SCALE=1/4in=1ft`` -> points_per_foot, or None."""
    m = _SCALE_RE.search(text or "")
    if not m:
        return None
    paper_val, paper_unit, real_val, real_unit = m.groups()
    paper = _eval_fraction(paper_val)
    real = float(real_val)
    if paper <= 0 or real <= 0:
        return None
    paper_pts = paper * _unit_to_feet(paper_unit, default_unit) * 12.0 * 6.0  # ft->pt: 72pt/in,12in/ft
    real_ft = real * _unit_to_feet(real_unit, default_unit)
    # paper distance (points) representing real_ft feet:
    return paper_pts / real_ft if real_ft else None


def _eval_fraction(token: str) -> float:
    token = token.strip()
    if "/" in token:
        num, _, den = token.partition("/")
        try:
            return float(num) / float(den)
        except (ValueError, ZeroDivisionError):
            return 0.0
    try:
        return float(token)
    except ValueError:
        return 0.0


def _annot_vertices(annot: Any) -> list[tuple[float, float]]:
    verts = annot.vertices
    if verts:
        # PyMuPDF returns either a flat list of points or pairs depending on type.
        if isinstance(verts[0], (list, tuple)) and len(verts[0]) == 2:
            return [(float(x), float(y)) for x, y in verts]
        return [(float(verts[i]), float(verts[i + 1])) for i in range(0, len(verts) - 1, 2)]
    r = annot.rect
    return [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]


def _is_rect_or_ellipse(type_name: str) -> bool:
    return type_name in ("Square", "Circle")


def extract_project(
    pdf_path: str,
    unit: str = "ft",
    manual_calibrations: Optional[dict[str, float]] = None,
) -> Project:
    """Open a PDF, read every markup annotation, return a populated Project.

    ``manual_calibrations`` maps a sheet label (e.g. ``"p1"``) to a
    points-per-foot value and takes precedence over any ``CAL=`` line found in
    the PDF — this is how a manually calibrated sheet survives re-extraction.
    """
    project = Project(pdf_path=str(pdf_path), unit=normalize_unit(unit))
    doc = fitz.open(pdf_path)
    try:
        # First pass: calibrations per sheet.
        for page in doc:
            sheet = _sheet_label(page)
            _collect_calibration(page, sheet, project)
        # Manual calibrations override anything detected in the PDF.
        for sheet, ppf in (manual_calibrations or {}).items():
            if ppf and float(ppf) > 0:
                project.calibrations[sheet] = Calibration(
                    sheet=sheet, points_per_foot=float(ppf), method="manual"
                )
        # Second pass: measurements.
        counter = 0
        for page in doc:
            sheet = _sheet_label(page)
            cal = project.calibrations.get(sheet)
            for annot in _iter_annots(page):
                content = (annot.info or {}).get("content", "") or ""
                if _CAL_RE.search(content) or _SCALE_RE.search(content):
                    continue  # calibration markers are not measurements
                type_name = annot.type[1]
                m = _build_measurement(annot, type_name, content, sheet, page.number, cal, project)
                if m is not None:
                    counter += 1
                    m.id = f"m{counter:04d}"
                    project.measurements.append(m)
    finally:
        doc.close()
    return project


def _sheet_label(page: Any) -> str:
    label = getattr(page, "get_label", lambda: "")()
    if label:
        return label
    return f"p{page.number + 1}"


def _iter_annots(page: Any) -> Iterable[Any]:
    annots = page.annots()
    if annots is None:
        return []
    return list(annots)


def _collect_calibration(page: Any, sheet: str, project: Project) -> None:
    for annot in _iter_annots(page):
        content = (annot.info or {}).get("content", "") or ""
        scale_ppf = parse_scale_directive(content, project.unit)
        if scale_ppf:
            project.calibrations[sheet] = Calibration(
                sheet=sheet, points_per_foot=scale_ppf, method="drawing-scale"
            )
            return
        m = _CAL_RE.search(content)
        if m:
            length_val = float(m.group(1))
            length_ft = length_val * _unit_to_feet(m.group(2), project.unit)
            pts = _seg_length(_annot_vertices(annot))
            if length_ft > 0 and pts > 0:
                project.calibrations[sheet] = Calibration(
                    sheet=sheet,
                    points_per_foot=pts / length_ft,
                    method="calibration-line",
                    source_unit=m.group(2) or project.unit,
                )
                return


def _build_measurement(
    annot: Any,
    type_name: str,
    content: str,
    sheet: str,
    page_number: int,
    cal: Optional[Calibration],
    project: Project,
) -> Optional[Measurement]:
    directive = _DIRECTIVE_RE.search(content)
    kind = directive.group(1).lower() if directive else _KIND_BY_TYPE.get(type_name)
    if kind is None:
        return None  # annotation type we don't measure (highlight, link, ...)

    condition = _DIRECTIVE_RE.sub("", content).strip() or f"(untitled {type_name})"
    info = annot.info or {}
    author = info.get("title") or None
    color = None
    try:
        colors = annot.colors or {}
        color = tuple(colors.get("stroke") or colors.get("fill") or ()) or None
    except Exception:  # pragma: no cover - color is best-effort metadata
        color = None

    if kind == "count":
        return Measurement(
            id="",
            sheet=sheet,
            page=page_number,
            kind="count",
            condition=condition,
            quantity=1.0,
            unit=KIND_UNIT["count"],
            author=author,
            color=color,
        )

    if cal is None:
        project.warnings.append(
            f"Sheet '{sheet}': measurement '{condition}' skipped — no calibration "
            f"(add a line with comment CAL=<length><unit>)."
        )
        return None

    ppf = cal.points_per_foot
    verts = _annot_vertices(annot)

    if kind == "linear":
        raw = _seg_length(verts)
        return Measurement(
            id="",
            sheet=sheet,
            page=page_number,
            kind="linear",
            condition=condition,
            quantity=raw / ppf,
            unit=KIND_UNIT["linear"],
            raw_points=raw,
            author=author,
            color=color,
        )

    # area
    if _is_rect_or_ellipse(type_name) and not annot.vertices:
        r = annot.rect
        w, h = abs(r.x1 - r.x0), abs(r.y1 - r.y0)
        if type_name == "Circle":
            raw_area = math.pi * (w / 2.0) * (h / 2.0)
            raw_perim = ellipse_perimeter(w, h)
        else:
            raw_area = w * h
            raw_perim = 2 * (w + h)
    else:
        raw_area = _polygon_area(verts)
        raw_perim = _polygon_perimeter(verts)

    return Measurement(
        id="",
        sheet=sheet,
        page=page_number,
        kind="area",
        condition=condition,
        quantity=raw_area / (ppf * ppf),
        unit=KIND_UNIT["area"],
        perimeter=raw_perim / ppf,
        raw_points=raw_area,
        author=author,
        color=color,
    )
