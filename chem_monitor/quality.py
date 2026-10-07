"""Data-quality report: is a score built on many independent, point-in-time signals, or on whatever
happened to be available? Low quality reduces evidence confidence (signals.interpret)."""
import numpy as np
import pandas as pd
from .config import TARGET

GROUPS = {   # name -> (series-name prefixes, weight in the overall quality score)
    "H-Acid price": (("hacid.spot",), .30),
    "Producer quotes": (("hacid.quote",), .10),
    "Feedstocks": (("feed.",), .15),
    "Capacity": ((), .10),
    "Inventory": (("ind.inventory",), .10),
    "Downstream dyes": (("dye.",), .10),
    "Exports": (("export.", "mirror."), .10),
    "Events": ((), .05),
}


def _icon(x, hi=0.9, mid=0.6):
    if x is None or pd.isna(x):
        return "⚪"
    return "🟢" if x >= hi else "🟡" if x >= mid else "🔴"


def data_quality(obs: pd.DataFrame, panel: pd.DataFrame, cap: pd.DataFrame, events: pd.DataFrame,
                 window_days=365, end=None) -> pd.DataFrame:
    """coverage = share of business days in the trailing window on which the group has a usable
    (observed or carried-within-staleness-limit) value. Events: share of quarters with >=1 event."""
    end = pd.Timestamp(end) if end is not None else panel.index.max()
    idx = panel.index[(panel.index > end - pd.Timedelta(days=window_days)) & (panel.index <= end)]
    obs = obs.assign(family=obs["source_family"].where(obs["source_family"].notna(), obs["source"]))
    rows = []
    for name, (prefixes, w) in GROUPS.items():
        if name == "Capacity":
            cov = float(panel["derived.eff_supply"].reindex(idx).notna().mean()) if "derived.eff_supply" in panel else 0.0
            pit = float((cap["vintage_status"] != "unknown").mean()) if len(cap) else np.nan
            conf = float((cap["vintage_status"] == "confirmed").mean()) if len(cap) else np.nan
            fam = int(cap["producer"].nunique()) if len(cap) else 0
            rows.append((name, cov, pit, conf, fam, int(len(cap)), w))
            continue
        if name == "Events":
            if len(events):
                q = pd.period_range(end - pd.Timedelta(days=window_days), end, freq="Q")
                hit = events["event_date"].dt.to_period("Q").isin(q)
                cov = float(len(set(events.loc[hit, "event_date"].dt.to_period("Q"))) / len(q))
                rows.append((name, cov, float((events["vintage_status"] != "unknown").mean()),
                             float((events["vintage_status"] == "confirmed").mean()),
                             int(events["source"].nunique()), int(len(events)), w))
            else:
                rows.append((name, 0.0, np.nan, np.nan, 0, 0, w))
            continue
        cols = [c for c in panel.columns if c.startswith(prefixes)]
        raw = obs[obs["series"].astype(str).str.startswith(prefixes)] if prefixes else obs.iloc[0:0]
        if not cols or raw.empty:
            rows.append((name, 0.0, np.nan, np.nan, 0, 0, w))
            continue
        cov = float(panel[cols].reindex(idx).notna().any(axis=1).mean()) if len(idx) else 0.0
        rows.append((name, cov, float((raw["vintage_status"] != "unknown").mean()),
                     float((raw["vintage_status"] == "confirmed").mean()), int(raw["family"].nunique()),
                     int(len(raw)), w))
    q = pd.DataFrame(rows, columns=["group", "coverage", "pit_coverage", "pit_confirmed",
                                    "independent_families", "n_records", "weight"]).set_index("group")
    vs = obs["vintage_status"].fillna("unknown")
    q.attrs.update({
        "overall_score": float((q["coverage"].fillna(0) * q["weight"]).sum() / q["weight"].sum()),
        "overall_pit_coverage": float((vs != "unknown").mean()) if len(obs) else 0.0,
        "confirmed_share": float((vs == "confirmed").mean()) if len(obs) else 0.0,
        "estimated_share": float((vs == "estimated").mean()) if len(obs) else 0.0,
        "unknown_share": float((vs == "unknown").mean()) if len(obs) else 0.0,
        "independent_families": int(obs["family"].nunique()),
        "price_families": int(obs.loc[obs["series"] == TARGET, "family"].nunique()),
        "window_days": window_days, "window_end": str(end.date())})
    return q


def render(q: pd.DataFrame) -> str:
    lines = ["DATA QUALITY", f"{'group':<20}{'coverage':>10}  {'point-in-time':>14}  {'confirmed':>9}  families"]
    for g, r in q.iterrows():
        pit = "   n/a" if pd.isna(r["pit_coverage"]) else f"{r['pit_coverage']:>6.0%}"
        conf = "   n/a" if pd.isna(r["pit_confirmed"]) else f"{r['pit_confirmed']:>6.0%}"
        lines.append(f"{g:<20}{r['coverage']:>8.0%} {_icon(r['coverage'])}  {pit:>12} {_icon(r['pit_coverage'], .9, .5)}  "
                     f"{conf:>8}  {int(r['independent_families']):>5}")
    a = q.attrs
    lines.append(f"\nOverall quality {a['overall_score']:.0%} {_icon(a['overall_score'], .8, .5)}   "
                 f"point-in-time {a['overall_pit_coverage']:.0%} (confirmed {a['confirmed_share']:.0%}, "
                 f"estimated {a['estimated_share']:.0%}, unknown {a['unknown_share']:.0%})   "
                 f"independent families {a['independent_families']}")
    return "\n".join(lines)
