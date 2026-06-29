"""Generate a sample marked-up PDF for testing and demos.

Geometry is chosen so quantities are exact and easy to verify:

* Calibration line: 240 pt long, comment ``CAL=10ft`` -> 24 points/ft.
* Area polygon: 240 x 120 pt -> 10 ft x 5 ft = 50 SF ("8in CMU wall").
* Linear line: 480 pt -> 20 LF ("2x4 wood stud wall").
* 3 sticky notes -> 3 EA ("Light fixture 2x4 LED").
"""

from __future__ import annotations

import sys

import fitz


def build(path: str) -> str:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)

    cal = page.add_line_annot((72, 72), (312, 72))  # 240 pt
    cal.set_info(content="CAL=10ft")
    cal.update()

    # Area measurements come through as polygons (Bluebeam/Adobe style) so the
    # vertices are exact: 240 x 120 pt -> 10 ft x 5 ft = 50 SF.
    wall = page.add_polygon_annot([(100, 200), (340, 200), (340, 320), (100, 320)])
    wall.set_info(content="8in CMU wall")
    wall.update()

    stud = page.add_line_annot((100, 420), (580, 420))  # 480 pt
    stud.set_info(content="2x4 wood stud wall")
    stud.update()

    for i in range(3):
        note = page.add_text_annot((120 + i * 40, 520), "Light fixture 2x4 LED")
        note.set_info(content="Light fixture 2x4 LED")
        note.update()

    doc.save(path)
    doc.close()
    return path


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "sample_plans.pdf"
    print("Wrote", build(out))
