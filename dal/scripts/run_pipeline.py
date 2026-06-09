"""Run classification + manload over the most recent study and print results.

Run from project root:   python -m scripts.run_pipeline
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import SessionLocal
from db.models import Study
from engine.classify import classify_study
from engine.manload import compute_manload
from engine import validity, idle_gaps, ml_classify


def main():
    s = SessionLocal()
    try:
        study = s.query(Study).order_by(Study.created_at.desc()).first()
        if not study:
            print("No study found. Run: python -m scripts.init_db")
            return
        print(f"Study: {study.name}  ({study.start_date} → {study.end_date})\n")

        gaps = idle_gaps.detect_gaps(s, study.id)
        print(f"Idle gaps flagged for attribution: {gaps}")

        c = classify_study(s, study.id, use_ai=True)
        print(f"Classified {c['blocks']} blocks | {c['needs_review']} need review | "
              f"{c['divergences']} divergences\n")

        results = compute_manload(s, study.id, va_efficiency=1.0)
        print(f"{'Role':<20}{'Period':<10}{'Req':>6}{'Actual':>8}{'Gap':>7}"
              f"{'VA%':>7}{'Nec%':>7}{'Waste%':>8}")
        print("-" * 73)
        for r in sorted(results, key=lambda x: (x["role"], x["period"])):
            print(f"{r['role']:<20}{r['period']:<10}{r['required_headcount']:>6}"
                  f"{r['actual_headcount']:>8}{r['gap']:>7}"
                  f"{r['va_pct']:>7}{r['nva_nec_pct']:>7}{r['nva_waste_pct']:>8}")

        outliers = validity.peer_outliers(s, study.id)
        print(f"\nPeer outliers flagged: {len(outliers)}")
        print(f"Divergences flagged:   {len(validity.divergences(s, study.id))}")

        ml = ml_classify.train(s, study.id)
        print(f"ML classifier: {ml}")
    finally:
        s.close()


if __name__ == "__main__":
    main()
