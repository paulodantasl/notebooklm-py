"""Tests for manual calibration via the MCP server (re-extraction + in-place)."""

import json

import fitz
import pytest

import pdf_takeoff.mcp_server as srv


@pytest.fixture(autouse=True)
def reset_state():
    srv.STATE.project = None
    srv.STATE.pdf_path = None
    srv.STATE.unit = "ft"
    srv.STATE.manual_calibrations = {}
    yield


def _uncalibrated_pdf(path):
    """A PDF with one area markup but NO CAL line, so extraction skips it."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    wall = page.add_polygon_annot([(100, 200), (340, 200), (340, 320), (100, 320)])
    wall.set_info(content="8in CMU wall")
    wall.update()
    doc.save(path)
    doc.close()
    return path


def test_manual_calibration_reextracts_skipped_measurements(tmp_path):
    pdf = _uncalibrated_pdf(str(tmp_path / "nocal.pdf"))
    summary = json.loads(srv.load_project(pdf))
    assert summary["measurement_count"] == 0
    assert summary["warnings"]  # skipped for missing calibration

    # 240 pt across == 10 ft -> 24 pt/ft
    msg = srv.set_calibration("p1", real_length=10, points_length=240, unit="ft")
    assert "recomputed" in msg
    assert srv.STATE.project is not None
    wall = next(m for m in srv.STATE.project.measurements if m.condition == "8in CMU wall")
    assert abs(wall.quantity - 50.0) < 0.01  # now picked up at 50 SF


def test_set_calibration_rejects_nonpositive(tmp_path):
    pdf = _uncalibrated_pdf(str(tmp_path / "nocal.pdf"))
    srv.load_project(pdf)
    with pytest.raises(ValueError):
        srv.set_calibration("p1", real_length=0, points_length=240)
    with pytest.raises(ValueError):
        srv.set_calibration("p1", real_length=10, points_length=-5)


def test_in_place_recompute_for_web_project(tmp_path):
    export = {
        "unit": "ft",
        "sheets": {"p1": {"points_per_foot": 24.0}},
        "measurements": [
            {
                "sheet": "p1",
                "kind": "area",
                "condition": "slab",
                "points": [[100, 200], [340, 200], [340, 320], [100, 320]],
            }
        ],
    }
    p = tmp_path / "web.takeoff.json"
    p.write_text(json.dumps(export))
    srv.load_measurements(str(p))
    before = srv.STATE.project.measurements[0].quantity
    assert abs(before - 50.0) < 0.01

    # Halve the scale (double pt/ft) -> area quartered.
    srv.set_calibration("p1", real_length=10, points_length=480, unit="ft")
    after = srv.STATE.project.measurements[0].quantity
    assert abs(after - 12.5) < 0.01
