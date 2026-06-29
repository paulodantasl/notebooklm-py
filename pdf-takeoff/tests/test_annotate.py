"""Round-trip: export -> PDF annotations -> re-extract -> identical quantities."""

import fitz

from pdf_takeoff.annotate import color_for, write_annotations
from pdf_takeoff.extract import extract_project

EXPORT = {
    "unit": "ft",
    "sheets": {"p1": {"points_per_foot": 24.0}},
    "measurements": [
        {
            "sheet": "p1",
            "kind": "area",
            "condition": "8in CMU wall",
            "points": [[100, 200], [340, 200], [340, 320], [100, 320]],
        },
        {
            "sheet": "p1",
            "kind": "linear",
            "condition": "2x4 wood stud wall",
            "points": [[100, 420], [580, 420]],
        },
        {
            "sheet": "p1",
            "kind": "count",
            "condition": "Light fixture 2x4 LED",
            "points": [[120, 520], [160, 520], [200, 520]],
        },
    ],
}


def _blank_pdf(path):
    doc = fitz.open()
    doc.new_page(width=612, height=792)
    doc.save(path)
    doc.close()
    return path


def test_roundtrip_quantities(tmp_path):
    base = _blank_pdf(str(tmp_path / "base.pdf"))
    out = str(tmp_path / "annotated.pdf")
    write_annotations(base, EXPORT, out)

    project = extract_project(out)
    from pdf_takeoff.quantities import rollup

    summary = rollup(project.measurements)

    # CAL=1ft scale bar gives 24 pt/ft back.
    assert project.calibrations["p1"].points_per_foot == 24.0
    assert abs(summary.by_condition("8in CMU wall").quantity - 50.0) < 0.05
    assert abs(summary.by_condition("2x4 wood stud wall").quantity - 20.0) < 0.05
    assert summary.by_condition("Light fixture 2x4 LED").quantity == 3.0
    assert project.warnings == []


def test_y_axis_flip_applied(tmp_path):
    base = _blank_pdf(str(tmp_path / "base.pdf"))
    out = str(tmp_path / "annotated.pdf")
    write_annotations(base, EXPORT, out)

    doc = fitz.open(out)
    page = doc[0]
    polys = [a for a in page.annots() if a.type[1] == "Polygon"]
    assert polys, "polygon annotation should be written"
    ys = [v[1] for v in polys[0].vertices]
    # UI y in {200,320}; flipped against height 792 -> {592, 472}
    assert min(ys) > 400 and max(ys) > 400  # placed in lower-PDF-user / upper-page region
    assert any(abs(y - (792 - 200)) < 1 for y in ys)
    doc.close()


def test_color_is_deterministic():
    assert color_for("8in CMU wall") == color_for("8in CMU wall")
    assert color_for("a") != color_for("b")


def test_no_calibration_bar_when_disabled(tmp_path):
    base = _blank_pdf(str(tmp_path / "base.pdf"))
    out = str(tmp_path / "annotated.pdf")
    write_annotations(base, EXPORT, out, include_calibration=False)
    doc = fitz.open(out)
    page = doc[0]
    contents = [(a.info or {}).get("content", "") for a in page.annots()]
    assert not any(c.startswith("CAL=") for c in contents)
    doc.close()
