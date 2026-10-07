"""Formal inflection detection + trend-acceleration vs regime-change shape test."""
from dataclasses import dataclass, asdict
import numpy as np
import pandas as pd
from .config import MOVE_RULES, EPISODE_GAP, LOOKBACK, START_BAND


@dataclass
class Inflection:
    id: str
    direction: str          # "up" | "down"
    start: pd.Timestamp     # earliest turning point (T for event studies)
    trigger: pd.Timestamp   # first date a threshold rule fired (earliest *live-detectable* date)
    end: pd.Timestamp
    start_price: float
    end_price: float
    magnitude: float
    rule: str
    shape: str              # regime_change | acceleration | trend_move
    z: float                # move size in units of pre-move volatility

    @property
    def sign(self):
        return 1 if self.direction == "up" else -1

    @property
    def detection_lag_days(self):
        return (self.trigger - self.start).days

    def as_dict(self):
        d = asdict(self)
        d["detection_lag_days"] = self.detection_lag_days
        return d


def detect(price: pd.Series, rules=MOVE_RULES, gap=EPISODE_GAP, lookback=LOOKBACK, band_frac=START_BAND,
           observed=None):
    """Threshold triggers on the business-day panel. Returns are computed WITHOUT bridging NaN, so a
    change across an unobserved gap (longer than the carry-forward limit) can never trigger: with
    sparse data we do not pretend to know when inside the gap the price moved.
    `observed`: dates of real observations; the move end is snapped to one of them (never to a
    carried-forward value)."""
    p = price.astype(float)
    obs_idx = None if observed is None else pd.DatetimeIndex(observed)
    n = len(p)
    trig = []
    for w, thr in rules:
        r = p / p.shift(w) - 1
        trig += [(d, 1, w, thr, v) for d, v in r[r >= thr].items()]
        trig += [(d, -1, w, thr, v) for d, v in r[r <= -thr].items()]
    trig.sort(key=lambda t: t[0])
    loc = lambda d: p.index.get_loc(d)
    raw = []
    for sign in (1, -1):
        clusters = []
        for t in (x for x in trig if x[1] == sign):
            if clusters and loc(t[0]) - loc(clusters[-1][-1][0]) <= gap:
                clusters[-1].append(t)
            else:
                clusters.append([t])
        for c in clusters:
            i0, i1 = loc(c[0][0]), loc(c[-1][0])
            seg = p.iloc[max(0, i0 - lookback): i0 + 1].dropna()
            # stay inside the contiguous observed stretch that contains the trigger
            gaps = seg.index.to_series().diff().dt.days > 7
            if gaps.any():
                seg = seg[seg.index >= gaps[gaps].index[-1]]
            if seg.empty:
                continue
            ext = seg.min() if sign == 1 else seg.max()          # extreme in the lookback window
            band = ext + band_frac * (seg.iloc[-1] - ext)              # "still near the extreme" band
            near = seg[seg <= band] if sign == 1 else seg[seg >= band]
            start = near.index[-1]                                # LAST date near the extreme = move start
            seg2 = p.iloc[i1: min(n, i1 + 20 + 1)].dropna()
            if obs_idx is not None:
                real = seg2[seg2.index.isin(obs_idx)]
                if real.empty:                    # last real observation at/before the trigger cluster
                    prior = p.loc[:p.index[i1]].dropna()
                    real = prior[prior.index.isin(obs_idx)].iloc[-1:]
                seg2 = real
            if seg2.empty:
                continue
            end = seg2.idxmax() if sign == 1 else seg2.idxmin()
            if loc(end) <= loc(start):
                continue
            w, thr = c[0][2], c[0][3]
            raw.append((start, c[0][0], end, sign, f"{w}d>={thr:.0%}"))
    raw.sort(key=lambda x: x[0])
    out = []
    for k, (start, trigger, end, sign, rule) in enumerate(raw, 1):
        i = loc(start)
        mag = p[end] / p[start] - 1
        base = p.iloc[max(0, i - 30)]
        pre30 = p[start] / base - 1 if pd.notna(base) else 0.0
        vol = p.pct_change(fill_method=None).iloc[max(1, i - 90): i + 1].std()
        nd = max(1, loc(end) - i)
        z = abs(mag) / (vol * np.sqrt(nd) + 1e-9) if pd.notna(vol) else np.nan
        if sign * pre30 >= 0.02:
            shape = "acceleration"            # already trending the same way
        elif pd.notna(z) and z >= 3:
            shape = "regime_change"           # large move out of a flat/opposite pre-trend
        else:
            shape = "trend_move"
        out.append(Inflection(f"I{k:02d}", "up" if sign == 1 else "down", start, trigger, end,
                              float(p[start]), float(p[end]), float(mag), rule, shape, float(z)))
    return out


def to_frame(infls) -> pd.DataFrame:
    return pd.DataFrame([i.as_dict() for i in infls])


def live_trigger(price: pd.Series, start, sign, rules=MOVE_RULES, horizon_bdays=65):
    """First date on/after `start` when a threshold rule fires on the (information-axis) price:
    the earliest moment a price-only monitor could have flagged the move."""
    p = price.astype(float)
    first = pd.NaT
    for w, thr in rules:
        r = (p / p.shift(w) - 1).loc[start:].iloc[:horizon_bdays]
        m = r[r >= thr] if sign == 1 else r[r <= -thr]
        if len(m) and (pd.isna(first) or m.index[0] < first):
            first = m.index[0]
    return first


def start_sensitivity(price: pd.Series, bands=(0.10, 0.25, 0.40), **kw) -> pd.DataFrame:
    """How much does the 'true start' date move with the near-extreme band? Episodes are matched on
    their trigger date (which does not depend on the band). Large spreads = start is soft."""
    cols = {}
    for b in bands:
        cols[f"start_band_{b:.2f}"] = pd.Series({i.trigger: i.start for i in detect(price, band_frac=b, **kw)})
    df = pd.DataFrame(cols).sort_index()
    df["spread_days"] = (df.max(axis=1) - df.min(axis=1)).dt.days
    return df.rename_axis("trigger")
