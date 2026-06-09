from pdf_takeoff.extract import extract_project


def _by_condition(project):
    return {m.condition: m for m in project.measurements}


def test_calibration_detected(sample_pdf):
    project = extract_project(sample_pdf)
    assert len(project.calibrations) == 1
    cal = next(iter(project.calibrations.values()))
    # 240 pt represents 10 ft -> 24 points/ft
    assert cal.points_per_foot == 24.0
    assert cal.method == "calibration-line"


def test_calibration_line_not_counted_as_measurement(sample_pdf):
    project = extract_project(sample_pdf)
    assert "CAL=10ft" not in _by_condition(project)


def test_area_measurement(sample_pdf):
    project = extract_project(sample_pdf)
    wall = _by_condition(project)["8in CMU wall"]
    assert wall.kind == "area"
    assert wall.unit == "SF"
    assert abs(wall.quantity - 50.0) < 0.01  # 10ft x 5ft
    assert abs(wall.perimeter - 30.0) < 0.01  # 2*(10+5)


def test_linear_measurement(sample_pdf):
    project = extract_project(sample_pdf)
    stud = _by_condition(project)["2x4 wood stud wall"]
    assert stud.kind == "linear"
    assert stud.unit == "LF"
    assert abs(stud.quantity - 20.0) < 0.01  # 480pt / 24


def test_count_measurements(sample_pdf):
    project = extract_project(sample_pdf)
    counts = [m for m in project.measurements if m.condition == "Light fixture 2x4 LED"]
    assert len(counts) == 3
    assert all(m.kind == "count" and m.quantity == 1.0 for m in counts)


def test_no_warnings_when_calibrated(sample_pdf):
    project = extract_project(sample_pdf)
    assert project.warnings == []
