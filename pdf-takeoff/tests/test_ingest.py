from pdf_takeoff.ingest import project_from_export
from pdf_takeoff.quantities import rollup

# Same geometry as the sample PDF, expressed as a web-UI export (PDF points).
EXPORT = {
    "pdf_name": "web-session",
    "unit": "ft",
    "sheets": {"p1": {"points_per_foot": 24.0, "method": "calibration-line"}},
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


def test_ingest_matches_expected_quantities():
    project = project_from_export(EXPORT)
    by = {m.condition: m for m in project.measurements}
    assert abs(by["8in CMU wall"].quantity - 50.0) < 0.01
    assert abs(by["8in CMU wall"].perimeter - 30.0) < 0.01
    assert abs(by["2x4 wood stud wall"].quantity - 20.0) < 0.01
    assert by["Light fixture 2x4 LED"].quantity == 3.0
    assert by["Light fixture 2x4 LED"].kind == "count"
    assert project.warnings == []


def test_ingest_rollup_totals():
    project = project_from_export(EXPORT)
    summary = rollup(project.measurements)
    assert abs(summary.by_condition("8in CMU wall").quantity - 50.0) < 0.01
    assert summary.by_condition("Light fixture 2x4 LED").quantity == 3.0


def test_uncalibrated_sheet_warns_and_skips():
    export = {
        "unit": "ft",
        "sheets": {},
        "measurements": [
            {"sheet": "p1", "kind": "linear", "condition": "wall", "points": [[0, 0], [240, 0]]}
        ],
    }
    project = project_from_export(export)
    assert project.measurements == []
    assert any("not calibrated" in w for w in project.warnings)


def test_count_without_calibration_still_counts():
    export = {
        "unit": "ft",
        "sheets": {},
        "measurements": [
            {"sheet": "p1", "kind": "count", "condition": "door", "points": [[1, 1], [2, 2]]}
        ],
    }
    project = project_from_export(export)
    assert len(project.measurements) == 1
    assert project.measurements[0].quantity == 2.0
