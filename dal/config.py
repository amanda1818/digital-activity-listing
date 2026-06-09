"""Central configuration. Reads from environment, with safe local defaults.

To switch from local SQLite to PostgreSQL, set DATABASE_URL, e.g.:
    export DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/dal
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Local default = a SQLite file in the project root. Zero setup needed.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///dal.db")

# Optional. If unset, the classification engine runs rules-only (still works).
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLASSIFY_MODEL = os.getenv("CLASSIFY_MODEL", "claude-sonnet-4-20250514")

# Engine thresholds (see PRD §C3, §B4, §D)
IDLE_THRESHOLD_MIN = int(os.getenv("IDLE_THRESHOLD_MIN", "10"))
CONFIDENCE_REVIEW_THRESHOLD = float(os.getenv("CONFIDENCE_REVIEW_THRESHOLD", "0.6"))
STANDARD_TIME_PERCENTILE = int(os.getenv("STANDARD_TIME_PERCENTILE", "25"))
PEER_OUTLIER_MULTIPLE = float(os.getenv("PEER_OUTLIER_MULTIPLE", "2.0"))
