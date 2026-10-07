"""Run collectors safely.

Guarantees (tested in tests/test_ingestion.py):
  * a failing collector never touches its existing CSV - yesterday's valid data survives
  * rows are validated before merge; rejected rows are counted with reasons, never written
  * merge is append/update only: an existing observation is never deleted by a collection run
  * every attempt updates data/status/source_status.json (last_attempt, last_success,
    failure_reason, last_observation_date ...) so the site can say "unavailable since ..."
"""
import json
import math
from pathlib import Path
import pandas as pd
from ..config import DATA_DIR
from ..db import OBS_COLS

KEY = ["obs_date", "source", "series", "location"]
SERIES_PREFIXES = ("hacid.", "feed.", "dye.", "export.", "mirror.", "ind.", "fx.")
MAX_JUMP = 3.0          # reject a value > 3x or < 1/3 of the previous value of the same series


def obs_path(source_id, data_dir=DATA_DIR) -> Path:
    return Path(data_dir) / "observations" / f"{source_id}.csv"


def status_path(data_dir=DATA_DIR) -> Path:
    return Path(data_dir) / "status" / "source_status.json"


def read_status(data_dir=DATA_DIR) -> dict:
    p = status_path(data_dir)
    return json.loads(p.read_text()) if p.exists() else {}


def write_status(st: dict, data_dir=DATA_DIR):
    p = status_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def read_store(source_id, data_dir=DATA_DIR) -> pd.DataFrame:
    p = obs_path(source_id, data_dir)
    if not p.exists():
        return pd.DataFrame(columns=OBS_COLS)
    df = pd.read_csv(p, dtype={"location": str})
    for c in ("obs_date", "pub_date"):
        df[c] = pd.to_datetime(df[c])
    df["location"] = df["location"].fillna("")
    return df


def validate(df: pd.DataFrame, existing: pd.DataFrame, now=None):
    """-> (valid rows, list of rejection reasons)."""
    now = pd.Timestamp(now or pd.Timestamp.now()).normalize() + pd.Timedelta(days=1)
    df = df.copy()
    reasons = []

    def drop(mask, why):
        nonlocal df
        n = int(mask.sum())
        if n:
            reasons.append(f"{n} row(s): {why}")
            df = df[~mask]

    for c in ("obs_date", "series", "value"):
        if c not in df:
            raise ValueError(f"collector output missing column {c!r}")
    df["obs_date"] = pd.to_datetime(df["obs_date"], errors="coerce")
    df["pub_date"] = pd.to_datetime(df.get("pub_date"), errors="coerce") if "pub_date" in df else pd.NaT
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["location"] = df.get("location", "").fillna("") if "location" in df else ""
    drop(df["obs_date"].isna(), "unparseable observation date")
    drop(~df["value"].map(lambda v: isinstance(v, float) and math.isfinite(v) and v > 0), "non-positive / missing value")
    drop(df["obs_date"] > now, "observation date in the future")
    drop(df["pub_date"].notna() & (df["pub_date"] > now), "publication date in the future")
    drop(df["pub_date"].notna() & (df["pub_date"] < df["obs_date"] - pd.Timedelta(days=1)),
         "published before the observation date")
    drop(~df["series"].astype(str).str.startswith(SERIES_PREFIXES), "unknown series namespace")
    if len(existing) and len(df):
        last = existing.sort_values("obs_date").groupby("series")["value"].last()
        prev = df["series"].map(last)
        ratio = df["value"] / prev
        drop(prev.notna() & ((ratio > MAX_JUMP) | (ratio < 1 / MAX_JUMP)), f"jump > {MAX_JUMP}x vs last stored value")
    return df, reasons


def merge(existing: pd.DataFrame, new: pd.DataFrame):
    """Union on KEY; a re-collected observation replaces the stored one (revision), nothing is deleted."""
    if existing.empty:
        out, revised = new, 0
    else:
        e = existing.assign(obs_date=pd.to_datetime(existing["obs_date"]))[KEY + ["value"]]
        j = new[KEY + ["value"]].merge(e.drop_duplicates(KEY, keep="last"), on=KEY, suffixes=("", "_old"))
        revised = int((~pd.Series([math.isclose(a, b) for a, b in zip(j["value"], j["value_old"])], dtype=bool)).sum())
        out = pd.concat([existing, new], ignore_index=True).drop_duplicates(KEY, keep="last")
    cols = [c for c in OBS_COLS if c in out.columns] + [c for c in out.columns if c not in OBS_COLS]
    return out[cols].sort_values(["series", "obs_date", "location"]).reset_index(drop=True), revised


def run_collector(c, mode="live", data_dir=DATA_DIR, now=None) -> dict:
    st_all = read_status(data_dir)
    st = st_all.get(c.name, {})
    st["last_attempt"] = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    st["mode"] = mode
    existing = read_store(c.name, data_dir)
    try:
        raw = c.fetch(mode)
        raw = raw.assign(source=raw.get("source", c.name)) if "source" in raw else raw.assign(source=c.name)
        if "tier" not in raw:
            raw["tier"] = c.tier
        good, reasons = validate(raw, existing, now)
        if good.empty:
            raise RuntimeError("no valid rows after validation: " + "; ".join(reasons))
        merged, revised = merge(existing, good)
        p = obs_path(c.name, data_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        out = merged.copy()
        for col in ("obs_date", "pub_date"):
            out[col] = pd.to_datetime(out[col]).dt.strftime("%Y-%m-%d")
        out.to_csv(p, index=False)
        st.update({"status": "partial" if raw.attrs.get("errors") else "ok",
                   "last_success": st["last_attempt"], "failure_reason": None,
                   "rows_fetched": int(len(raw)), "rows_new": int(len(merged) - len(existing)),
                   "rows_revised": revised, "rows_rejected": reasons, "warnings": raw.attrs.get("errors", [])[:10],
                   "last_observation_date": str(pd.to_datetime(merged["obs_date"]).max().date()),
                   "rows_total": int(len(merged))})
        dest = getattr(c, "destinations", None)
        if isinstance(dest, pd.DataFrame) and len(dest):
            dp = Path(data_dir) / "observations" / f"{c.name}_destinations.csv"
            old = pd.read_csv(dp, dtype={"period": str}) if dp.exists() else pd.DataFrame()
            pd.concat([old, dest.astype({"period": str})]).drop_duplicates(["period", "partner_code"], keep="last") \
              .sort_values(["period", "partner_code"]).to_csv(dp, index=False)
    except Exception as e:                         # noqa: BLE001 - recorded, previous data kept
        st.update({"status": "failed", "failure_reason": f"{type(e).__name__}: {e}"[:500]})
        if len(existing):
            st["last_observation_date"] = str(pd.to_datetime(existing["obs_date"]).max().date())
    st_all = read_status(data_dir)           # re-read: another collector may have written meanwhile
    st_all[c.name] = st
    write_status(st_all, data_dir)
    return st


def run_all(collectors, mode="live", data_dir=DATA_DIR) -> dict:
    out = {}
    for c in collectors:
        st = run_collector(c, mode, data_dir)
        out[c.name] = st
        print(f"[ingest] {c.name:<18} {st['status']:<8} new={st.get('rows_new', 0)} "
              f"last_obs={st.get('last_observation_date')} {st.get('failure_reason') or ''}")
    return out
