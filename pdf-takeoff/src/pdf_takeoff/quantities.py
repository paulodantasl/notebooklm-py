"""Roll measurements up into quantity summaries (the executive QTO).

Pure functions over ``Measurement`` records — no PDF, no I/O. This is the layer
Claude leans on to answer "how much of X is there?" with exact numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional


@dataclass
class ConditionTotal:
    condition: str
    kind: str
    unit: str
    quantity: float
    count: int  # number of source measurements
    perimeter: Optional[float] = None
    division: Optional[str] = None
    waste_pct: float = 0.0

    @property
    def quantity_with_waste(self) -> float:
        return round(self.quantity * (1.0 + self.waste_pct), 4)


@dataclass
class QuantitySummary:
    totals: list[ConditionTotal] = field(default_factory=list)

    def by_condition(self, condition: str) -> Optional[ConditionTotal]:
        for t in self.totals:
            if t.condition == condition:
                return t
        return None

    def group_by_division(self) -> dict[str, list[ConditionTotal]]:
        out: dict[str, list[ConditionTotal]] = {}
        for t in self.totals:
            out.setdefault(t.division or "Unassigned", []).append(t)
        return out


def rollup(
    measurements: Iterable["object"],
    waste: Optional[dict[str, float]] = None,
    division_map: Optional[dict[str, str]] = None,
) -> QuantitySummary:
    """Aggregate measurements by condition.

    ``waste`` and ``division_map`` are keyed by condition name and are optional.
    """
    waste = waste or {}
    division_map = division_map or {}
    acc: dict[str, ConditionTotal] = {}
    for m in measurements:
        key = m.condition
        if key not in acc:
            acc[key] = ConditionTotal(
                condition=m.condition,
                kind=m.kind,
                unit=m.unit,
                quantity=0.0,
                count=0,
                perimeter=0.0 if m.kind == "area" else None,
                division=division_map.get(m.condition),
                waste_pct=waste.get(m.condition, 0.0),
            )
        t = acc[key]
        t.quantity += float(m.quantity)
        t.count += 1
        if t.perimeter is not None and getattr(m, "perimeter", None):
            t.perimeter += float(m.perimeter)

    for t in acc.values():
        t.quantity = round(t.quantity, 4)
        if t.perimeter is not None:
            t.perimeter = round(t.perimeter, 4)

    # Stable, readable ordering: by division then condition.
    totals = sorted(acc.values(), key=lambda x: ((x.division or "~"), x.condition))
    return QuantitySummary(totals=totals)


def summary_to_rows(summary: QuantitySummary) -> list[dict]:
    """Flatten to plain dict rows (for CSV / tables / tool output)."""
    rows = []
    for t in summary.totals:
        rows.append(
            {
                "division": t.division or "Unassigned",
                "condition": t.condition,
                "kind": t.kind,
                "unit": t.unit,
                "quantity": t.quantity,
                "waste_pct": t.waste_pct,
                "quantity_with_waste": t.quantity_with_waste,
                "perimeter_lf": t.perimeter,
                "measurements": t.count,
            }
        )
    return rows
