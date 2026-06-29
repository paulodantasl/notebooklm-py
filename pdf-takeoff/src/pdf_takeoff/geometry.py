"""Pure geometry helpers shared by the markup extractor and the JSON ingest path.

Operating in PDF points: distances and areas are invariant to the PDF's y-axis
orientation, so the same math serves both the PyMuPDF route and the web UI.
"""

from __future__ import annotations

import math
from typing import Sequence

Point = Sequence[float]


def seg_length(points: Sequence[Point]) -> float:
    """Total length of an open polyline through ``points``."""
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        total += math.hypot(x2 - x1, y2 - y1)
    return total


def polygon_area(points: Sequence[Point]) -> float:
    """Shoelace area of a polygon (auto-closes if the ring is open)."""
    if len(points) < 3:
        return 0.0
    pts = list(points)
    if tuple(pts[0]) != tuple(pts[-1]):
        pts.append(pts[0])
    s = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def polygon_perimeter(points: Sequence[Point]) -> float:
    """Perimeter of a polygon (auto-closes if the ring is open)."""
    if len(points) < 2:
        return 0.0
    pts = list(points)
    if tuple(pts[0]) != tuple(pts[-1]):
        pts.append(pts[0])
    return seg_length(pts)


def ellipse_perimeter(width: float, height: float) -> float:
    """Ramanujan approximation of an ellipse perimeter from a bounding box."""
    a, b = width / 2.0, height / 2.0
    return math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))
