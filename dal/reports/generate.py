"""Generate a Word study report from manload results (PRD Module E).

Run from project root:   python -m reports.generate
Aggregates by role only — never an individual ranking.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from docx import Document
from docx.shared import Pt, RGBColor
from db.database import SessionLocal
from db.models import Study
from engine.manload import compute_manload

NAVY = RGBColor(0x1E, 0x27, 0x61)


def generate_report(session, study_id, out_path="study_report.docx"):
    study = session.get(Study, study_id)
    results = compute_manload(session, study_id, persist=False)

    doc = Document()
    h = doc.add_heading("Activity Listing — Study Report", level=0)
    h.runs[0].font.color.rgb = NAVY
    doc.add_paragraph(f"Client study: {study.name}")
    doc.add_paragraph(f"Window: {study.start_date} to {study.end_date}")
    doc.add_paragraph(
        "Method: measured activity data + in-the-moment sampling. Required time excludes "
        "non-value-added waste (rework, waiting, over-processing). Figures are reported by "
        "role; no individual is identified or ranked.")

    doc.add_heading("Manload — required vs. actual headcount", level=1)
    overall = [r for r in results if r["period"] == "overall"]
    table = doc.add_table(rows=1, cols=6)
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    for i, t in enumerate(["Role", "Required", "Actual", "Gap", "VA %", "Waste %"]):
        hdr[i].text = t
    for r in overall:
        c = table.add_row().cells
        c[0].text = r["role"]
        c[1].text = f"{r['required_headcount']:.2f}"
        c[2].text = str(r["actual_headcount"])
        c[3].text = f"{r['gap']:+.2f}"
        c[4].text = f"{r['va_pct']:.0f}"
        c[5].text = f"{r['nva_waste_pct']:.0f}"

    cyc = [r for r in results if r["period"] in ("baseline", "peak")]
    if cyc:
        doc.add_heading("Cyclical roles — baseline vs. peak load", level=1)
        doc.add_paragraph(
            "For cyclical functions, headcount is reported as a range across the cycle "
            "rather than a single average. Peak corresponds to month-end close.")
        t2 = doc.add_table(rows=1, cols=4)
        t2.style = "Light Grid Accent 1"
        for i, t in enumerate(["Role", "Period", "Required", "Actual"]):
            t2.rows[0].cells[i].text = t
        for r in sorted(cyc, key=lambda x: (x["role"], x["period"])):
            c = t2.add_row().cells
            c[0].text = r["role"]; c[1].text = r["period"]
            c[2].text = f"{r['required_headcount']:.2f}"; c[3].text = str(r["actual_headcount"])

    doc.add_heading("Recommendations", level=1)
    doc.add_paragraph("[Consultant to complete: process changes to remove the waste identified above, "
                      "and staffing decision for cyclical peaks — staff-to-peak, staff-to-average, or smooth.]")

    doc.save(out_path)
    return out_path


if __name__ == "__main__":
    s = SessionLocal()
    try:
        study = s.query(Study).order_by(Study.created_at.desc()).first()
        path = generate_report(s, study.id)
        print(f"Report written: {path}")
    finally:
        s.close()
