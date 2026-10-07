"""Inflection score (0-100). Components use expanding percentiles (no look-ahead). Weights are
point-in-time: refit periodically using ONLY labels that had matured by that date."""
import numpy as np
import pandas as pd
from .config import (COMPONENTS, PRIOR_WEIGHTS, BANDS, TARGET, WEIGHT_REFIT_EVERY,
                     WEIGHT_MIN_TRAIN, SCORE_HORIZON, MIN_COVERAGE)

MIN_HISTORY = 60


def _transform(s, kind, w):
    pos = (s.dropna() > 0).all()
    pc = (lambda x, k: x.pct_change(k, fill_method=None)) if pos else (lambda x, k: x.diff(k))
    if kind == "pct":
        return s / s.shift(w) - 1 if pos else s.diff(w)
    if kind == "diff":
        return s.diff(w)
    if kind == "accel":
        m = s / s.shift(w) - 1 if pos else s.diff(w)
        return m - m.shift(w)
    if kind == "level":
        return s
    raise ValueError(kind)


def _expanding_rank(s):
    """Expanding mid-rank percentile: ties count half, so 'no change' in a mostly-flat step series
    sits near the middle (0) instead of being read as an extreme."""
    return s.expanding(min_periods=MIN_HISTORY).apply(
        lambda x: ((x < x[-1]).sum() + 0.5 * (x == x[-1]).sum()) / len(x), raw=True)


def components(panel: pd.DataFrame) -> pd.DataFrame:
    """Each component in [-1, 1]: +1 = most bullish pressure seen so far. Build `panel` on the
    information axis for any as-of use."""
    out = {}
    for name, (col, kind, w, sign) in COMPONENTS.items():
        if col not in panel or panel[col].dropna().shape[0] < MIN_HISTORY + w:
            continue
        x = sign * _transform(panel[col], kind, w)
        if kind == "level":                  # levels with a meaningful zero (event pressure): squash, no ranking
            out[name] = np.tanh(x).where(panel[col].notna())
            continue
        out[name] = 2 * _expanding_rank(x.dropna()).reindex(panel.index) - 1
    return pd.DataFrame(out)


def band(score):
    """Score -> (state, icon) from config.BANDS. The only mapping from numbers to words."""
    for hi, name, icon in BANDS:
        if score < hi:
            return name, icon
    return BANDS[-1][1], BANDS[-1][2]


def _prior(cols):
    p = pd.Series(PRIOR_WEIGHTS).reindex(cols).fillna(0)
    return p / p.sum()


def fit_weights(panel, comps=None, horizon=SCORE_HORIZON, shrink=0.5, end=None) -> pd.Series:
    """DIAGNOSTIC / building block. Weight ~ non-negative corr(component, forward return), shrunk to
    the prior. With end=None it uses the full sample (look-ahead!) - never feed that to live scoring;
    use vintage_weights(). With `end`, only rows <= end are used (labels must have matured by then)."""
    comps = components(panel) if comps is None else comps
    fwd = np.log(panel[TARGET]).diff(horizon).shift(-horizon)
    if end is not None:
        comps, fwd = comps.loc[:end], fwd.loc[:end]
    with np.errstate(invalid="ignore", divide="ignore"):
        edge = comps.apply(lambda c: c.corr(fwd)).clip(lower=0).fillna(0)
    pr = _prior(comps.columns)
    learned = edge / edge.sum() if edge.sum() > 0 else pr
    w = shrink * pr + (1 - shrink) * learned
    return (w / w.sum()).rename("weight")


def vintage_weights(panel, comps=None, refit_every=WEIGHT_REFIT_EVERY, min_train=WEIGHT_MIN_TRAIN,
                    horizon=SCORE_HORIZON, shrink=0.5) -> pd.DataFrame:
    """Date x component weights as they would have been known on each date. At refit date t the
    training set ends at t-horizon so every forward-return label used had already matured."""
    comps = components(panel) if comps is None else comps
    idx = panel.index
    W = pd.DataFrame(np.nan, index=idx, columns=comps.columns)
    W.iloc[0] = _prior(comps.columns)                       # prior until enough history
    for i in range(min_train, len(idx), refit_every):
        W.iloc[i] = fit_weights(panel, comps, horizon, shrink, end=idx[i - horizon])
    return W.ffill()


def compute_score(panel, weights=None, comps=None, min_coverage=MIN_COVERAGE) -> pd.DataFrame:
    """weights: None (prior), a Series (static), or a date x component DataFrame (vintage).
    Components are first averaged inside their signal block (config.BLOCKS) using these weights; the
    blocks are then combined with config.BLOCK_WEIGHTS. Correlated indicators (spot price, producer
    quote) therefore share one block vote instead of counting as independent confirmations.
    coverage = share of configured block weight with data; below `min_coverage` the row is
    insufficient_evidence and its state is capped at WATCH however high the raw score."""
    from .signals import block_frame, block_pressure, state_for
    comps = components(panel) if comps is None else comps
    comps = comps.reindex(columns=list(COMPONENTS))          # missing components stay visible as NaN
    if isinstance(weights, pd.DataFrame):
        w = weights.reindex(index=comps.index, columns=comps.columns).ffill().fillna(0)
    else:
        ws = _prior(comps.columns) if weights is None else pd.Series(weights).reindex(comps.columns).fillna(0)
        w = pd.DataFrame([ws.to_numpy()] * len(comps), index=comps.index, columns=comps.columns)
    blocks = block_frame(comps, w)
    pressure, coverage = block_pressure(blocks)
    out = pd.DataFrame({"pressure": pressure, "score": pressure.abs() * 100,
                        "direction": np.sign(pressure).map({1.0: "up", -1.0: "down"}).fillna("flat"),
                        "coverage": coverage})
    out["status"] = np.where(out["coverage"] >= min_coverage, "ok", "insufficient_evidence")
    st = [state_for(a, b == "ok") for a, b in zip(out["score"], out["status"])]
    out["state"] = [x[0] if pd.notna(sc) else None for x, sc in zip(st, out["score"])]
    out["state_capped"] = [x[2] for x in st]
    out["band"] = out["state"]
    for b in blocks.columns:
        out[f"block.{b}"] = blocks[b]
    return out
