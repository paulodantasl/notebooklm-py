from pathlib import Path

from pdf_takeoff.catalog import division_map_from_assemblies, load_json
from pdf_takeoff.estimate import build_estimate
from pdf_takeoff.extract import extract_project
from pdf_takeoff.quantities import rollup

DATA = Path(__file__).resolve().parents[1] / "data"


def test_rollup_groups_by_condition(sample_pdf):
    project = extract_project(sample_pdf)
    summary = rollup(project.measurements)
    cmu = summary.by_condition("8in CMU wall")
    lights = summary.by_condition("Light fixture 2x4 LED")
    assert abs(cmu.quantity - 50.0) < 0.01
    assert lights.quantity == 3.0  # 3 counts aggregate to 3 EA
    assert lights.count == 3


def test_waste_applied(sample_pdf):
    project = extract_project(sample_pdf)
    summary = rollup(project.measurements, waste={"8in CMU wall": 0.10})
    cmu = summary.by_condition("8in CMU wall")
    assert abs(cmu.quantity_with_waste - 55.0) < 0.01


def test_assembly_estimate(sample_pdf):
    project = extract_project(sample_pdf)
    assemblies = load_json(DATA / "assemblies.example.json")
    costdb = load_json(DATA / "costdb.example.json")
    division_map = division_map_from_assemblies(assemblies)
    summary = rollup(project.measurements, division_map=division_map)
    est = build_estimate(summary, assemblies=assemblies, costdb=costdb, markup_pct=0.15)

    # CMU wall = 50 SF -> 1.125 blocks/SF * 1.05 waste = 59.0625 blocks
    block_line = next(
        l for l in est.lines if l.item == "8in CMU block" and l.condition == "8in CMU wall"
    )
    assert abs(block_line.quantity - 59.0625) < 0.001
    assert abs(block_line.material - round(59.0625 * 2.35, 2)) < 0.01

    assert est.subtotal > 0
    assert abs(est.grand_total - round(est.subtotal * 1.15, 2)) < 0.01
    assert "04 - Masonry" in est.by_division()


def test_unit_price_fallback(sample_pdf):
    project = extract_project(sample_pdf)
    unit_prices = load_json(DATA / "unit_prices.example.json")
    summary = rollup(project.measurements)
    est = build_estimate(summary, unit_prices=unit_prices)
    # Counts are priced via unit price for the light fixtures.
    light = next((l for l in est.lines if l.condition == "Light fixture 2x4 LED"), None)
    assert light is not None
    assert abs(light.quantity - 3.0) < 0.01
    assert abs(light.total - round(3 * (85.0 + 45.0), 2)) < 0.01
