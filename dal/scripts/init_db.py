"""Create tables, seed the activity catalog, and generate a demo study with
synthetic data (including a cyclical accounting month-end peak).

Run from the project root:   python -m scripts.init_db
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import create_all, SessionLocal
from seed.synthetic import generate_demo


def main():
    create_all()
    s = SessionLocal()
    try:
        info = generate_demo(s)
        print("Demo study created.")
        print(f"  study_id        : {info['study_id']}")
        print(f"  consultant login: consultant@demo / demo1234")
        print(f"  client admin    : admin@demo / demo1234")
        print(f"  sample ESM link : {info['sample_esm_url']}")
        print("\nNext:  python -m scripts.run_pipeline   then   streamlit run dashboard/app.py")
    finally:
        s.close()


if __name__ == "__main__":
    main()
