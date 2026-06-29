"""Render quantity summaries and estimates as Markdown or CSV."""

from __future__ import annotations

import csv
import io

from .estimate import Estimate
from .quantities import QuantitySummary, summary_to_rows


def _fmt(n: float | None) -> str:
    if n is None:
        return ""
    return f"{n:,.2f}"


def summary_markdown(summary: QuantitySummary, title: str = "Executive Quantity Summary") -> str:
    lines = [f"# {title}", ""]
    grouped = summary.group_by_division()
    for division in sorted(grouped):
        lines.append(f"## {division}")
        lines.append("")
        lines.append("| Condition | Qty | Unit | Waste % | Qty + Waste | Perimeter (LF) | # |")
        lines.append("|---|---:|:--:|---:|---:|---:|---:|")
        for t in grouped[division]:
            lines.append(
                f"| {t.condition} | {_fmt(t.quantity)} | {t.unit} | "
                f"{t.waste_pct * 100:.0f}% | {_fmt(t.quantity_with_waste)} | "
                f"{_fmt(t.perimeter)} | {t.count} |"
            )
        lines.append("")
    return "\n".join(lines)


def summary_csv(summary: QuantitySummary) -> str:
    rows = summary_to_rows(summary)
    buf = io.StringIO()
    fields = [
        "division",
        "condition",
        "kind",
        "unit",
        "quantity",
        "waste_pct",
        "quantity_with_waste",
        "perimeter_lf",
        "measurements",
    ]
    w = csv.DictWriter(buf, fieldnames=fields)
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def estimate_markdown(est: Estimate, title: str = "Estimate") -> str:
    lines = [f"# {title}", ""]
    lines.append("| Division | Condition | Item | Qty | Unit | Material | Labor | Equip | Total |")
    lines.append("|---|---|---|---:|:--:|---:|---:|---:|---:|")
    for l in sorted(est.lines, key=lambda x: (x.division, x.condition, x.item)):
        lines.append(
            f"| {l.division} | {l.condition} | {l.item} | {_fmt(l.quantity)} | {l.unit} | "
            f"{_fmt(l.material)} | {_fmt(l.labor)} | {_fmt(l.equip)} | {_fmt(l.total)} |"
        )
    lines.append("")
    lines.append("## Totals by division")
    lines.append("")
    lines.append("| Division | Total |")
    lines.append("|---|---:|")
    for div, total in sorted(est.by_division().items()):
        lines.append(f"| {div} | {_fmt(total)} |")
    lines.append("")
    lines.append(f"**Subtotal:** {_fmt(est.subtotal)}  ")
    lines.append(f"**Markup ({est.markup_pct * 100:.0f}%):** {_fmt(est.markup)}  ")
    lines.append(f"**Grand total:** {_fmt(est.grand_total)}")
    if est.warnings:
        lines.append("")
        lines.append("## Warnings")
        for w in est.warnings:
            lines.append(f"- {w}")
    return "\n".join(lines)
