"""Turn quantities into a priced estimate.

Two modes, both driven by editable JSON catalogs:

* **Assembly mode** — a condition expands into material/labor line items via an
  *assembly* (factor = qty of item per 1 unit of takeoff quantity). Costs come
  from a *cost database* keyed by item.
* **Unit-cost mode** — a condition maps directly to a single unit price.

The assembly catalog also supplies the CSI ``division`` used by the executive
summary, so quantities and dollars stay aligned.

Waste is modelled in two intentional, compounding layers:

* **Condition waste** (``set_waste`` / ``rollup``) is a measurement/design
  allowance applied to the take-off quantity itself — it inflates *every* item
  derived from that condition.
* **Item waste** (``materials[].waste`` in an assembly) is per-material cutting
  loss applied on top, only in assembly mode.

So an assembly item's quantity is ``qty * (1 + condition_waste) * factor *
(1 + item_waste)``. Unit-price mode has no items, so only condition waste
applies there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .quantities import QuantitySummary


@dataclass
class EstimateLine:
    condition: str
    item: str
    division: str
    unit: str
    quantity: float  # item quantity after factor + waste
    unit_material: float
    unit_labor: float
    unit_equip: float

    @property
    def material(self) -> float:
        return round(self.quantity * self.unit_material, 2)

    @property
    def labor(self) -> float:
        return round(self.quantity * self.unit_labor, 2)

    @property
    def equip(self) -> float:
        return round(self.quantity * self.unit_equip, 2)

    @property
    def total(self) -> float:
        return round(self.material + self.labor + self.equip, 2)


@dataclass
class Estimate:
    lines: list[EstimateLine] = field(default_factory=list)
    markup_pct: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @property
    def subtotal(self) -> float:
        return round(sum(l.total for l in self.lines), 2)

    @property
    def markup(self) -> float:
        return round(self.subtotal * self.markup_pct, 2)

    @property
    def grand_total(self) -> float:
        return round(self.subtotal + self.markup, 2)

    def by_division(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for l in self.lines:
            out[l.division] = round(out.get(l.division, 0.0) + l.total, 2)
        return out


def _cost(costdb: dict, item: str) -> tuple[float, float, float, str]:
    c = costdb.get(item, {})
    return (
        float(c.get("material", c.get("material_cost", 0.0)) or 0.0),
        float(c.get("labor", c.get("labor_cost", 0.0)) or 0.0),
        float(c.get("equip", c.get("equip_cost", 0.0)) or 0.0),
        str(c.get("unit", "")),
    )


def build_estimate(
    summary: QuantitySummary,
    assemblies: Optional[dict] = None,
    costdb: Optional[dict] = None,
    unit_prices: Optional[dict] = None,
    markup_pct: float = 0.0,
) -> Estimate:
    """Price a quantity summary.

    Resolution order per condition: assembly (if present) -> unit price (if
    present) -> warning. ``unit_prices[condition]`` may be a number or a dict
    ``{material, labor, equip, division}``.
    """
    assemblies = assemblies or {}
    costdb = costdb or {}
    unit_prices = unit_prices or {}
    est = Estimate(markup_pct=markup_pct)

    for t in summary.totals:
        base_qty = t.quantity_with_waste
        asm = assemblies.get(t.condition)
        if asm:
            division = asm.get("division", t.division or "Unassigned")
            for mat in asm.get("materials", []):
                factor = float(mat.get("factor", 1.0))
                item_waste = float(mat.get("waste", 0.0))
                qty = round(base_qty * factor * (1.0 + item_waste), 4)
                um, ul, ue, _unit = _cost(costdb, mat["item"])
                if (um, ul, ue) == (0.0, 0.0, 0.0):
                    est.warnings.append(f"No cost found for item '{mat['item']}'.")
                est.lines.append(
                    EstimateLine(
                        condition=t.condition,
                        item=mat["item"],
                        division=division,
                        unit=mat.get("unit", _unit),
                        quantity=qty,
                        unit_material=um,
                        unit_labor=ul,
                        unit_equip=ue,
                    )
                )
            continue

        price = unit_prices.get(t.condition)
        if price is not None:
            if isinstance(price, dict):
                um = float(price.get("material", 0.0))
                ul = float(price.get("labor", 0.0))
                ue = float(price.get("equip", 0.0))
                division = price.get("division", t.division or "Unassigned")
            else:
                um, ul, ue = float(price), 0.0, 0.0
                division = t.division or "Unassigned"
            if (um, ul, ue) == (0.0, 0.0, 0.0):
                est.warnings.append(f"Unit price for '{t.condition}' is zero.")
            est.lines.append(
                EstimateLine(
                    condition=t.condition,
                    item=t.condition,
                    division=division,
                    unit=t.unit,
                    quantity=base_qty,
                    unit_material=um,
                    unit_labor=ul,
                    unit_equip=ue,
                )
            )
            continue

        est.warnings.append(
            f"Condition '{t.condition}' not priced — add an assembly or unit price."
        )

    return est
