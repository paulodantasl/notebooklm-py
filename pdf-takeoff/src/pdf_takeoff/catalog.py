"""Load editable JSON catalogs: assemblies, cost database, unit prices, waste."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Catalog not found: {p}")
    with p.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Catalog {p} must be a JSON object at the top level.")
    return data


def division_map_from_assemblies(assemblies: dict[str, Any]) -> dict[str, str]:
    """condition -> CSI division, pulled from the assembly catalog."""
    return {
        cond: spec.get("division", "Unassigned")
        for cond, spec in assemblies.items()
        if isinstance(spec, dict)
    }
