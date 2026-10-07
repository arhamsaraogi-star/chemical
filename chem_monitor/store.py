"""The git-tracked CSV store is the source of truth; the SQLite DB is rebuilt from it on every run.

  data/observations/<source_id>.csv     collector output (append/update only)
  data/curated/hacid_price_points.csv   cited price points from news / broker notes
  data/curated/events.csv               plant / policy events with event & announcement dates
  data/curated/capacity.csv             producer status timeline
"""
from pathlib import Path
import pandas as pd
from . import db
from .config import DATA_DIR, DB_PATH


def load_observation_csvs(data_dir=DATA_DIR) -> pd.DataFrame:
    data_dir = Path(data_dir)
    files = sorted((data_dir / "observations").glob("*.csv"))
    files = [f for f in files if not f.stem.endswith("_destinations")]
    cur = data_dir / "curated" / "hacid_price_points.csv"
    if cur.exists():
        files.append(cur)
    frames = [pd.read_csv(f, dtype={"location": str}) for f in files]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=db.OBS_COLS)


def rebuild(db_path=DB_PATH, data_dir=DATA_DIR) -> dict:
    data_dir, db_path = Path(data_dir), Path(db_path)
    db_path.unlink(missing_ok=True)
    db.init_db(db_path)
    obs = load_observation_csvs(data_dir)
    n = {"observations": db.upsert_observations(obs, db_path) if len(obs) else 0}
    ev, cap = data_dir / "curated" / "events.csv", data_dir / "curated" / "capacity.csv"
    n["events"] = db.upsert_events(pd.read_csv(ev), db_path) if ev.exists() else 0
    n["capacity"] = db.upsert_capacity(pd.read_csv(cap), db_path) if cap.exists() else 0
    return n
