"""Raw observations -> reconciled master series; supply & event layers. All builders take
time_axis='economic' (research: when it happened) or 'information' (as-of: when it was knowable)."""
import numpy as np
import pandas as pd
from .config import TIER_WEIGHT, MAX_FFILL_DAYS, FFILL_LIMITS, EVENT_HALFLIFE_DAYS, STATUS_AVAILABILITY


def _wmedian(v, w):
    o = np.argsort(v)
    v, w = v[o], w[o]
    c = np.cumsum(w)
    return v[np.searchsorted(c, c[-1] / 2)]


def _axis_col(time_axis, econ, info):
    if time_axis not in ("economic", "information"):
        raise ValueError("time_axis must be 'economic' or 'information'")
    return econ if time_axis == "economic" else info


def build_master(obs: pd.DataFrame, series: str, time_axis="economic", as_of=None) -> pd.DataFrame:
    """Tier/confidence-weighted median per date. Sources in the same `source_family` (copies of one
    original) share one vote. Source dispersion is kept as a signal."""
    d = obs[obs["series"] == series].copy()
    if as_of is not None:
        d = d[d["known_date"] <= pd.Timestamp(as_of)]
    d["date"] = d[_axis_col(time_axis, "obs_date", "known_date")]
    d["family"] = d["source_family"].where(d["source_family"].notna(), d["source"])
    d["w"] = d["tier"].map(TIER_WEIGHT).fillna(0) * d["confidence"].fillna(1.0)
    d = d[d["w"] > 0]
    d["w"] = d["w"] / d.groupby(["date", "family"])["w"].transform("size")
    rows = []
    for dt, g in d.groupby("date"):
        v, w = g["value"].to_numpy(float), g["w"].to_numpy(float)
        rows.append((dt, _wmedian(v, w), len(g), g["family"].nunique(), v.min(), v.max(),
                     (v.std() / v.mean()) if len(v) > 1 else np.nan))
    out = pd.DataFrame(rows, columns=["date", "value", "n_sources", "n_families", "lo", "hi", "cv"])
    return out.set_index("date").sort_index()


def build_panel(obs: pd.DataFrame, time_axis="economic", as_of=None, index_end=None):
    if obs.empty:
        raise ValueError("no observations in database")
    cols, disp = {}, {}
    for s in sorted(obs["series"].unique()):
        m = build_master(obs, s, time_axis, as_of)
        if m.empty:
            continue
        cols[s] = m["value"]
        disp[s] = m[["n_sources", "n_families", "lo", "hi", "cv"]]
    panel = pd.DataFrame(cols)
    end = pd.Timestamp(index_end) if index_end is not None else panel.index.max()
    idx = pd.bdate_range(panel.index.min(), end)
    # observations on weekends/holidays are moved to the next business day before carrying forward
    panel = panel.groupby(idx[idx.searchsorted(panel.index).clip(max=len(idx) - 1)]).last()
    panel = panel.reindex(idx)
    for c in panel.columns:
        panel[c] = panel[c].ffill(limit=ffill_limit(c))
    return panel, disp


def ffill_limit(col: str) -> int:
    for prefix, lim in FFILL_LIMITS.items():
        if col.startswith(prefix):
            return lim
    return MAX_FFILL_DAYS


def effective_supply(cap: pd.DataFrame, index: pd.DatetimeIndex, time_axis="economic") -> pd.DataFrame:
    """Effective supply = nominal x utilization x availability, step function per producer.
    Where no utilisation is published it is NOT invented: the result is 'available capacity'
    (nominal x availability) and availability falls back to the documented status table
    (config.STATUS_AVAILABILITY) - an ESTIMATE that the site labels as such."""
    if cap.empty:
        return pd.DataFrame(index=index)
    dcol = _axis_col(time_axis, "eff_date", "known_date")
    parts_eff, parts_nom = [], []
    for p, g in cap.sort_values([dcol, "eff_date"]).groupby("producer"):
        g = g.drop_duplicates(dcol, keep="last").set_index(dcol)
        avail = g["availability"].astype(float).fillna(g["status"].map(STATUS_AVAILABILITY).astype(float)).fillna(1.0)
        avail = avail.where(~g["status"].isin(["shutdown", "retired"]), 0.0)
        eff = g["nominal_t"] * g["utilization"].astype(float).fillna(1.0) * avail
        nom = g["nominal_t"].where(g["status"] != "retired", 0.0)
        step = lambda s: s.reindex(s.index.union(index)).ffill().reindex(index)
        parts_eff.append(step(eff))
        parts_nom.append(step(nom))
    eff = pd.concat(parts_eff, axis=1).sum(axis=1, min_count=1)
    nom = pd.concat(parts_nom, axis=1).sum(axis=1, min_count=1)
    out = pd.DataFrame({"eff_supply_t": eff, "nominal_t": nom})
    # availability ratio of the KNOWN producer set (0..1); robust to producers entering the dataset
    out["supply_index"] = eff / nom.replace(0, np.nan)
    return out


def event_pressure(events: pd.DataFrame, index: pd.DatetimeIndex, total_nominal=None,
                   halflife=EVENT_HALFLIFE_DAYS, time_axis="economic") -> pd.Series:
    """Decayed event pressure on PRICE (positive = bullish). Supply-down events push price up.
    On the information axis an event only starts to count on its public announcement date."""
    out = pd.Series(0.0, index=index)
    if events.empty:
        return out
    dcol = _axis_col(time_axis, "event_date", "known_date")
    t = (index - index[0]).days.to_numpy(float)
    for _, e in events.iterrows():
        share = 1.0
        if total_nominal is not None and pd.notna(e.get("capacity_t")):
            # Series => nominal capacity AS KNOWN on that date (no look-ahead); scalar also accepted
            tn = total_nominal.asof(e[dcol]) if isinstance(total_nominal, pd.Series) else total_nominal
            if tn and pd.notna(tn):
                share = min(1.0, float(e["capacity_t"]) / float(tn))
        sev = float(e.get("severity") or 1)
        t0 = (e[dcol] - index[0]).days
        decay = np.where(t >= t0, np.exp(-np.log(2) * (t - t0) / halflife), 0.0)
        out += -float(e["direction"]) * sev * (0.5 + share) * decay
    return out
