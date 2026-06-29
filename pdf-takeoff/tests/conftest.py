import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))


@pytest.fixture
def sample_pdf(tmp_path):
    from make_sample_pdf import build

    out = tmp_path / "sample_plans.pdf"
    build(str(out))
    return str(out)
