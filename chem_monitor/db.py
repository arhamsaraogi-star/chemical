"""SQLite store with point-in-time (vintage) fields.

Two clocks everywhere:
  economic time    obs_date / event_date / eff_date      - when it happened
  information time pub_date / announce_date / published_at - when an analyst could have known it
`known_date` (derived at load) = max(economic, information) and is what as-of backtests must use.
"""
import sqlite3
import warnings
from contextlib import contextmanager
from pathlib import Path
import numpy as np
import pandas as pd
from .config import DB_PATH

# value_kind: observed | derived | estimated | inferred | ai_extracted   (never blurred - see docs/methodology.md)
OBS_COLS = ["obs_date", "pub_date", "source", "source_family", "tier", "series", "product", "grade",
            "location", "value", "currency", "unit", "price_type", "market", "quote_kind", "url",
            "confidence", "raw_text", "vintage_status", "value_kind", "date_precision", "republisher",
            "chemical_id"]
EVENT_COLS = ["event_date", "announce_date", "event_ts", "event_type", "company", "capacity_t",
              "direction", "severity", "source", "url", "note", "event_date_precision", "vintage_status",
              "plant", "location", "source_family", "value_kind", "confidence", "raw_text", "chemical_id"]
CAP_COLS = ["producer", "eff_date", "published_at", "location", "nominal_t", "utilization",
            "availability", "status", "note", "value_kind", "url", "chemical_id"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations(
  obs_date TEXT NOT NULL, pub_date TEXT, source TEXT NOT NULL, source_family TEXT, tier INTEGER NOT NULL,
  series TEXT NOT NULL, product TEXT, grade TEXT, location TEXT NOT NULL DEFAULT '',
  value REAL NOT NULL, currency TEXT, unit TEXT, price_type TEXT, market TEXT, quote_kind TEXT,
  url TEXT, confidence REAL DEFAULT 1.0, raw_text TEXT, vintage_status TEXT, value_kind TEXT DEFAULT 'observed',
  date_precision TEXT DEFAULT 'day', republisher TEXT, chemical_id TEXT DEFAULT 'hacid',
  PRIMARY KEY (obs_date, source, series, location));
CREATE TABLE IF NOT EXISTS events(
  event_id INTEGER PRIMARY KEY AUTOINCREMENT, event_date TEXT NOT NULL, announce_date TEXT, event_ts TEXT,
  event_type TEXT NOT NULL, company TEXT NOT NULL DEFAULT '', capacity_t REAL,
  direction INTEGER NOT NULL,  -- effect on SUPPLY: +1 / -1
  severity INTEGER DEFAULT 1, source TEXT, url TEXT, note TEXT, event_date_precision TEXT DEFAULT 'day',
  vintage_status TEXT, plant TEXT, location TEXT, source_family TEXT, value_kind TEXT DEFAULT 'observed',
  confidence REAL DEFAULT 1.0, raw_text TEXT, chemical_id TEXT DEFAULT 'hacid',
  UNIQUE(event_date, event_type, company));
CREATE TABLE IF NOT EXISTS capacity(
  producer TEXT NOT NULL, eff_date TEXT NOT NULL, published_at TEXT, location TEXT, nominal_t REAL NOT NULL,
  utilization REAL DEFAULT 1.0, availability REAL DEFAULT 1.0, status TEXT DEFAULT 'operating',
  note TEXT, value_kind TEXT DEFAULT 'observed', url TEXT, chemical_id TEXT DEFAULT 'hacid',
  PRIMARY KEY (producer, eff_date));
"""
_EXTRA = {"observations": {"source_family": "TEXT", "vintage_status": "TEXT", "value_kind": "TEXT",
                           "date_precision": "TEXT", "republisher": "TEXT", "chemical_id": "TEXT"},
          "events": {"announce_date": "TEXT", "event_ts": "TEXT", "event_date_precision": "TEXT",
                     "vintage_status": "TEXT", "plant": "TEXT", "location": "TEXT", "source_family": "TEXT",
                     "value_kind": "TEXT", "confidence": "REAL", "raw_text": "TEXT", "chemical_id": "TEXT"},
          "capacity": {"published_at": "TEXT", "value_kind": "TEXT", "url": "TEXT", "chemical_id": "TEXT"}}


@contextmanager
def connect(path=DB_PATH):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db(path=DB_PATH):
    with connect(path) as con:
        con.executescript(SCHEMA)
        for t, cols in _EXTRA.items():            # migrate databases created by v0.1
            have = {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
            for c, typ in cols.items():
                if c not in have:
                    con.execute(f"ALTER TABLE {t} ADD COLUMN {c} {typ}")


def _prep(df, cols, required, defaults=None):
    df = df.copy()
    for c, v in (defaults or {}).items():
        if c not in df:
            df[c] = v
    missing = [c for c in required if c not in df]
    if missing:
        raise ValueError(f"missing required columns: {missing}")
    for c in cols:
        if c not in df:
            df[c] = None
    return df[cols]


def _iso(df, col):
    s = pd.to_datetime(df[col])
    df[col] = s.dt.strftime("%Y-%m-%d").where(s.notna(), None)


def _upsert(table, df, cols, path):
    init_db(path)
    df = df.astype(object).where(df.notna(), None)
    q = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
    with connect(path) as con:
        con.executemany(q, df.values.tolist())
    return len(df)


def upsert_observations(df, path=DB_PATH):
    df = _prep(df, OBS_COLS, ["obs_date", "source", "tier", "series", "value"],
               {"confidence": 1.0, "location": "", "value_kind": "observed", "date_precision": "day",
                "chemical_id": "hacid"})
    for c in ("obs_date", "pub_date"):
        _iso(df, c)
    df["location"] = df["location"].fillna("")
    df["confidence"] = df["confidence"].fillna(1.0)
    # vintage_status: confirmed = source gave a publication date; estimated = assumed lag (explicit
    # opt-in); unknown = no publication date -> excluded from as-of work by default
    derived = pd.Series(np.where(df["pub_date"].notna(), "confirmed", "unknown"), index=df.index)
    df["vintage_status"] = df["vintage_status"].where(df["vintage_status"].notna(), derived)
    return _upsert("observations", df, OBS_COLS, path)


def upsert_events(df, path=DB_PATH):
    df = _prep(df, EVENT_COLS, ["event_date", "event_type", "direction"],
               {"severity": 1, "company": "", "event_date_precision": "day", "value_kind": "observed",
                "chemical_id": "hacid"})
    for c in ("event_date", "announce_date"):
        _iso(df, c)
    df["company"] = df["company"].fillna("")
    derived = pd.Series(np.where(df["announce_date"].notna(), "confirmed", "unknown"), index=df.index)
    df["vintage_status"] = df["vintage_status"].where(df["vintage_status"].notna(), derived)
    return _upsert("events", df, EVENT_COLS, path)


def upsert_capacity(df, path=DB_PATH):
    df = _prep(df, CAP_COLS, ["producer", "eff_date", "nominal_t"],
               {"utilization": None, "availability": None, "status": "operating", "value_kind": "observed",
                "chemical_id": "hacid"})
    for c in ("eff_date", "published_at"):
        _iso(df, c)
    return _upsert("capacity", df, CAP_COLS, path)


def _load(table, date_cols, path):
    init_db(path)
    with connect(path) as con:
        df = pd.read_sql(f"SELECT * FROM {table}", con)
    for c in date_cols:
        df[c] = pd.to_datetime(df[c])
    return df


def _known(econ: pd.Series, info: pd.Series) -> pd.Series:
    """Information date = max(economic, information). If the information date is MISSING the result
    is NaT (unknown vintage) - never silently the economic date. See apply_vintage_policy()."""
    return econ.where(econ >= info, info)


def _status(info: pd.Series) -> pd.Series:
    return pd.Series(np.where(info.notna(), "confirmed", "unknown"), index=info.index)


def load_observations(path=DB_PATH):
    df = _load("observations", ["obs_date", "pub_date"], path)
    df["known_date"] = _known(df["obs_date"], df["pub_date"])
    df["vintage_status"] = df["vintage_status"].where(df["vintage_status"].notna(), _status(df["pub_date"]))
    return df


def load_events(path=DB_PATH):
    df = _load("events", ["event_date", "announce_date"], path)
    df["known_date"] = _known(df["event_date"], df["announce_date"])
    df["vintage_status"] = df["vintage_status"].where(df["vintage_status"].notna(), _status(df["announce_date"]))
    return df


def load_capacity(path=DB_PATH):
    df = _load("capacity", ["eff_date", "published_at"], path)
    df["known_date"] = _known(df["eff_date"], df["published_at"])
    df["vintage_status"] = _status(df["published_at"])
    return df


def apply_vintage_policy(df: pd.DataFrame, econ_col: str, policy="exclude"):
    """What to do with records whose publication date is unknown on the information axis.
      'exclude'          (default) they do not exist for as-of work: less data, no fake precision
      'assume_economic'  pretend they were known on their economic date (explicit opt-in, warns)
    Returns (frame, n_unknown)."""
    unk = df["known_date"].isna()
    n = int(unk.sum())
    if policy == "exclude":
        return df[~unk].copy(), n
    if policy == "assume_economic":
        if n:
            warnings.warn(f"{n} records with unknown vintage assumed known on their economic date; "
                          "as-of results are optimistic", stacklevel=2)
        d = df.copy()
        d.loc[unk, "known_date"] = d.loc[unk, econ_col]
        return d, n
    raise ValueError("vintage policy must be 'exclude' or 'assume_economic'")
