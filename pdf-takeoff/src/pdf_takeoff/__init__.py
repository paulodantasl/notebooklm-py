"""pdf-takeoff: onscreen PDF quantity take-off + estimating for Claude (via MCP).

Pipeline: extract markup geometry -> calibrate -> quantities -> estimate.
"""

from .annotate import write_annotations
from .estimate import Estimate, build_estimate
from .extract import extract_project
from .ingest import project_from_export
from .model import Calibration, Measurement, Project
from .quantities import QuantitySummary, rollup

__all__ = [
    "Calibration",
    "Measurement",
    "Project",
    "QuantitySummary",
    "Estimate",
    "extract_project",
    "project_from_export",
    "write_annotations",
    "rollup",
    "build_estimate",
]

__version__ = "0.1.0"
