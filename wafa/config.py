"""Paths and business settings."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(__file__).resolve().parent / "data" / "telco_churn.csv"
DATA_SHA256 = "16320c9c1ec72448db59aa0a26a0b95401046bef5d02fd3aeb906448e3055e91"
SQL = Path(__file__).resolve().parent / "sql" / "features.sql"
ARTIFACTS = Path(os.getenv("WAFA_ARTIFACTS", ROOT / "artifacts"))
WEB_DATA = ROOT / "web" / "data"
SEED = 42

# Retention campaign defaults (all adjustable in the planner and the API)
OFFER_COST = 60.0          # cost of one retention offer (e.g. a discount or device credit), in dollars
SAVE_RATE = 0.30           # share of would-be churners an offer keeps (assumption; measure with an A/B test)
VALUE_MONTHS = 12          # months of revenue a saved customer is worth
