"""Core data model for the PDF takeoff system.

Everything downstream of extraction works on these structured records, never on
pixels. Quantities are stored in real-world units (feet / square feet / each) so
that Claude — or any consumer — reasons over exact numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# Linear-unit -> feet conversion. Areas use the square of these factors.
TO_FEET: dict[str, float] = {
    "ft": 1.0,
    "'": 1.0,
    "feet": 1.0,
    "foot": 1.0,
    "in": 1.0 / 12.0,
    '"': 1.0 / 12.0,
    "inch": 1.0 / 12.0,
    "yd": 3.0,
    "yard": 3.0,
    "m": 3.280839895,
    "cm": 0.032808399,
    "mm": 0.0032808399,
}

# Quantity-unit labels per measurement kind (internal unit is always feet).
KIND_UNIT = {"linear": "LF", "area": "SF", "count": "EA"}


def normalize_unit(unit: str) -> str:
    """Map a user-supplied unit token to a TO_FEET key, defaulting to feet."""
    u = (unit or "").strip().lower()
    return u if u in TO_FEET else "ft"


@dataclass
class Calibration:
    """Maps PDF points to real-world feet for one sheet.

    ``points_per_foot`` is the single source of truth for converting geometry.
    """

    sheet: str
    points_per_foot: float
    method: str  # "calibration-line" | "drawing-scale" | "manual"
    source_unit: str = "ft"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Measurement:
    """A single quantity pulled from a PDF markup annotation."""

    id: str
    sheet: str
    page: int
    kind: str  # "linear" | "area" | "count"
    condition: str
    quantity: float  # real-world: LF, SF, or EA
    unit: str  # "LF" | "SF" | "EA"
    perimeter: Optional[float] = None  # LF, for area measurements
    raw_points: Optional[float] = None  # raw geometric magnitude (audit trail)
    author: Optional[str] = None
    color: Optional[tuple[float, ...]] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["color"] = list(self.color) if self.color else None
        return d


@dataclass
class Project:
    """An extracted takeoff: the PDF, its calibrations, and all measurements."""

    pdf_path: str
    unit: str = "ft"
    calibrations: dict[str, Calibration] = field(default_factory=dict)
    measurements: list[Measurement] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def sheets(self) -> list[str]:
        seen: dict[str, None] = {}
        for m in self.measurements:
            seen.setdefault(m.sheet, None)
        return list(seen)

    def conditions(self) -> list[str]:
        seen: dict[str, None] = {}
        for m in self.measurements:
            seen.setdefault(m.condition, None)
        return list(seen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pdf_path": self.pdf_path,
            "unit": self.unit,
            "calibrations": {k: v.to_dict() for k, v in self.calibrations.items()},
            "measurements": [m.to_dict() for m in self.measurements],
            "warnings": list(self.warnings),
        }
