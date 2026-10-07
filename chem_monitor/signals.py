"""Signal blocks, state logic and the human-readable interpretation.

Design rules (docs/methodology.md):
  * the state text is a pure function of the score (config.BANDS) - text can never contradict score
  * driver attribution ("what is pushing") is reported separately from confidence ("how sure")
  * correlated indicators are averaged inside a block; blocks are what get counted as confirmations
  * an old event is reported as 'last known event'; only residual pressure counts as 'active'
  * analogues below a similarity threshold are suppressed; small samples are labelled
"""
import numpy as np
import pandas as pd
from .config import (BANDS, BLOCKS, BLOCK_WEIGHTS, BLOCK_STRENGTH, CONFIRM_MIN, EVENT_ACTIVE_MIN,
                     ANALOGUE_BANDS, ANALOGUE_MIN_SHOW, SAMPLE_LABELS, START_BAND)

DRIVER_TEXT = {  # block -> (text when pushing price up, text when pushing price down)
    "SUPPLY": ("Supply tightening", "Supply easing"),
    "COST": ("Cost push", "Cost relief"),
    "DOWNSTREAM": ("Downstream dye strength", "Downstream dye weakness"),
    "DEMAND": ("Demand strengthening", "Demand weakening"),
    "INVENTORY": ("Inventory drawdown", "Inventory build"),
    "TRADE": ("Export demand firming", "Export demand softening"),
    "EVENTS": ("Supply-disruption events", "Supply-restoring events"),
    "PRICE": ("Price-led", "Price-led"),
}
STATE_SENTENCE = {
    "NORMAL": "No statistically significant price inflection detected.",
    "WATCH": "Pressure is building but has not reached inflection strength.",
    "DEVELOPING INFLECTION": "A price inflection is developing.",
    "STRONG INFLECTION": "A strong price inflection is under way.",
    "MAJOR INFLECTION": "A major price inflection is under way.",
}


# ------------------------------------------------------------------ state
def state_for(score, alert_grade=True):
    """-> (state, icon, capped). Insufficient evidence caps the state at WATCH (never alert-grade)."""
    if score is None or pd.isna(score):
        return "NO DATA", "⚪", False
    for hi, name, icon in BANDS:
        if score < hi:
            break
    if not alert_grade and score >= BANDS[1][0]:
        return "WATCH", "🟡", True
    return name, icon, False


def strength(v):
    if v is None or pd.isna(v):
        return "No data"
    for lo, name in BLOCK_STRENGTH:
        if abs(v) >= lo:
            return name
    return "Neutral"


def sample_label(n):
    for lo, name in SAMPLE_LABELS:
        if n >= lo:
            return name
    return SAMPLE_LABELS[-1][1]


# ------------------------------------------------------------------ blocks
def block_frame(comps: pd.DataFrame, weights=None) -> pd.DataFrame:
    """date x block: weighted mean of member components (weights = within-block component weights)."""
    out = {}
    for b, members in BLOCKS.items():
        cols = [c for c in members if c in comps]
        if not cols:
            out[b] = pd.Series(np.nan, index=comps.index)
            continue
        if isinstance(weights, pd.DataFrame):
            w = weights.reindex(index=comps.index, columns=cols).ffill().fillna(1.0)
        else:
            w = pd.DataFrame(1.0, index=comps.index, columns=cols)
        w = w.where(w > 0, 1e-6)
        num = (comps[cols].fillna(0) * w).sum(axis=1)
        den = (comps[cols].notna() * w).sum(axis=1).replace(0, np.nan)
        out[b] = num / den
    return pd.DataFrame(out)


def block_pressure(blocks: pd.DataFrame):
    """-> (pressure in [-1,1], coverage = share of configured block weight with data)."""
    w = pd.Series(BLOCK_WEIGHTS).reindex(blocks.columns).fillna(0)
    num = (blocks.fillna(0) * w).sum(axis=1)
    den = (blocks.notna() * w).sum(axis=1)
    return num / den.replace(0, np.nan), den / w.sum()


def confirmation(blocks_row: pd.Series, sign: int):
    """Non-price blocks with data, and how many agree with the direction (independent families)."""
    nonprice = blocks_row.drop("PRICE", errors="ignore").dropna()
    agree = [b for b, v in nonprice.items() if sign * v >= CONFIRM_MIN]
    against = [b for b, v in nonprice.items() if sign * v <= -CONFIRM_MIN]
    return {"available": len(nonprice), "confirming": len(agree), "confirming_blocks": agree,
            "contradicting_blocks": against, "configured": len(BLOCKS) - 1}


def primary_driver(blocks_row: pd.Series, sign: int):
    nonprice = blocks_row.drop("PRICE", errors="ignore").dropna()
    nonprice = nonprice[sign * nonprice >= CONFIRM_MIN]
    if nonprice.empty:
        return "PRICE", ("Price-led (fundamentals not confirming)" if not pd.isna(blocks_row.get("PRICE"))
                         else "No dominant driver")
    b = (sign * nonprice).idxmax()
    return b, DRIVER_TEXT[b][0 if sign > 0 else 1]


def interpret(score_row: pd.Series, blocks_row: pd.Series, quality_score=None) -> dict:
    """The one place where live text is generated. State comes ONLY from the score."""
    alert_grade = score_row.get("status") == "ok"
    state, icon, capped = state_for(score_row.get("score"), alert_grade)
    sign = 1 if score_row.get("pressure", 0) >= 0 else -1
    drv_block, drv_text = primary_driver(blocks_row, sign)
    conf = confirmation(blocks_row, sign)
    # evidence confidence: about the reading, never upgrades the state
    pts = (conf["confirming"] >= 2) + bool(alert_grade) + (quality_score is not None and quality_score >= 0.7)
    confidence = "High" if pts == 3 else "Medium" if pts == 2 else "Low"
    sentence = STATE_SENTENCE.get(state, "Insufficient data.")
    if capped:
        sentence = ("Raw score is elevated, but evidence coverage is below the minimum, so the state is "
                    "capped at WATCH.")
    if state == "NORMAL" and drv_block != "PRICE":
        sentence += f" Underlying pressure: {drv_text.lower()} (below inflection strength)."
    return {"state": state, "icon": icon, "state_capped": capped, "direction": "up" if sign > 0 else "down",
            "driver_block": drv_block, "driver": drv_text, "sentence": sentence,
            "confirmation": conf, "evidence_confidence": confidence,
            "blocks": {b: {"value": None if pd.isna(v) else round(float(v), 3), "strength": strength(v),
                           "direction": None if pd.isna(v) or abs(v) < 0.1 else ("up" if v > 0 else "down")}
                       for b, v in blocks_row.items()}}


# ------------------------------------------------------------------ events
def event_context(events: pd.DataFrame, pressure: pd.Series, ts, axis_col="known_date"):
    """Last known event (as of ts on the chosen axis) kept separate from residual pressure."""
    ts = pd.Timestamp(ts)
    resid = float(pressure.asof(ts)) if len(pressure) and pd.notna(pressure.asof(ts)) else 0.0
    last = None
    if len(events):
        e = events[events[axis_col].notna() & (events[axis_col] <= ts)].sort_values([axis_col, "event_date"])
        if len(e):
            r = e.iloc[-1]
            last = {"event_date": str(r["event_date"].date()), "announce_date":
                    None if pd.isna(r.get("announce_date")) else str(pd.Timestamp(r["announce_date"]).date()),
                    "event_type": r["event_type"], "company": r.get("company") or "",
                    "days_ago": int((ts - r["event_date"]).days)}
    return {"last_event": last, "residual_pressure": round(resid, 3),
            "active": abs(resid) >= EVENT_ACTIVE_MIN,
            "text": ("Active event pressure" if abs(resid) >= EVENT_ACTIVE_MIN else
                     "No active event pressure (last event has decayed)" if last else "No events recorded")}


# ------------------------------------------------------------------ analogues
def analogue(now_vec: pd.Series, blocks: pd.DataFrame, infls, ts, min_gap_days=30):
    """Closest earlier inflection by cosine similarity of block fingerprints (14d before its start).
    Only inflections that ENDED before ts - min_gap_days are eligible (no peeking at the present)."""
    ts = pd.Timestamp(ts)
    v = now_vec.fillna(0).to_numpy(float)
    best, bs = None, -2.0
    for i in infls:
        if i.end >= ts - pd.Timedelta(days=min_gap_days):
            continue
        w = blocks.loc[i.start - pd.Timedelta(days=14): i.start]
        if w.empty:
            continue
        u = w.mean().reindex(now_vec.index).fillna(0).to_numpy(float)
        d = np.linalg.norm(u) * np.linalg.norm(v)
        if d == 0:
            continue
        cs = float(u @ v / d)
        if cs > bs:
            best, bs = i, cs
    sim = None if best is None else round(max(bs, 0) * 100, 1)
    label = "No useful analogue"
    for lo, name in ANALOGUE_BANDS:
        if sim is not None and sim >= lo:
            label = name
            break
    shown = sim is not None and sim >= ANALOGUE_MIN_SHOW
    return {"id": best.id if shown else None, "start": str(best.start.date()) if shown else None,
            "magnitude": round(best.magnitude, 4) if shown else None,
            "similarity": sim, "label": label if shown else "No strong historical analogue",
            "candidates": sum(1 for i in infls if i.end < ts - pd.Timedelta(days=min_gap_days))}


# ------------------------------------------------------------------ onset windows
def onset_window(inf, sens_row, obs_dates: pd.DatetimeIndex, gap_days=30, price: pd.Series = None):
    """Best estimate + plausible window for the price-regime onset.
    The window spans (a) the start-date sensitivity range and (b) the real observations bracketing the
    best estimate: with sparse data the move happened somewhere between two observations."""
    best = inf.start
    cands = [best] + [pd.Timestamp(x) for x in sens_row.dropna().tolist()] if sens_row is not None else [best]
    before = obs_dates[obs_dates <= best]
    after = obs_dates[(obs_dates > best) & (obs_dates <= inf.trigger)]
    if len(before):
        cands.append(before[-1])
    if len(after):
        cands.append(after[0] - pd.Timedelta(days=1))
    # if the best estimate is the first observation after an unobserved gap, the move may have
    # started anywhere inside that gap: the window reaches back to the previous observation
    prev = obs_dates[obs_dates < best]
    after_gap = bool(len(prev) and (best - prev[-1]).days > gap_days)
    if after_gap and price is not None:
        # only if the price actually moved in the move's direction during the gap
        p0 = price.asof(prev[-1])
        moved = pd.notna(p0) and p0 > 0 and inf.sign * (inf.start_price / p0 - 1) > 0.02
        after_gap = bool(moved)
    if after_gap:
        cands.append(prev[-1])
    lo, hi = min(cands), max(cands)
    spread = int((hi - lo).days)
    conf = "High" if spread <= 5 else "Medium" if spread <= 20 else "Low"
    return {"best": str(best.date()), "earliest": str(lo.date()), "latest": str(hi.date()),
            "spread_days": spread, "confidence": conf, "exact": spread == 0, "after_unobserved_gap": after_gap}


def fundamental_onset(inf, events: pd.DataFrame, blocks_econ: pd.DataFrame, lookback_days=120):
    """Earliest fundamental evidence (economic time) supporting the move, and when it became public."""
    lo, hi = inf.start - pd.Timedelta(days=lookback_days), inf.start + pd.Timedelta(days=5)
    ev = events[(events["event_date"] >= lo) & (events["event_date"] <= hi) &
                (events["direction"] * inf.sign < 0)] if len(events) else events
    if len(ev):
        e = ev.sort_values("event_date").iloc[0]
        prec = e.get("event_date_precision") or "day"
        pad = {"day": 0, "week": 3, "month": 15, "early-month": 5, "mid-month": 5}.get(prec, 0)
        return {"basis": "event", "date": str(e["event_date"].date()),
                "earliest": str((e["event_date"] - pd.Timedelta(days=pad)).date()),
                "latest": str((e["event_date"] + pd.Timedelta(days=pad)).date()),
                "precision": prec, "public_date": None if pd.isna(e.get("announce_date")) else
                str(pd.Timestamp(e["announce_date"]).date()),
                "evidence": f"{e['event_type']}: {e.get('company') or ''}".strip(": "), "n_events": int(len(ev))}
    fb = blocks_econ.drop(columns=["PRICE", "EVENTS"], errors="ignore")
    above = (fb * inf.sign) >= 0.3
    crossed = (above & ~above.shift(1, fill_value=False)).loc[lo:hi]   # a genuine turn, not a level
    hit = crossed[crossed.any(axis=1)]
    if len(hit):
        d = hit.index[0]
        blk = hit.iloc[0][hit.iloc[0]].index[0]
        return {"basis": "indicator", "date": str(d.date()), "earliest": str(d.date()), "latest": str(d.date()),
                "precision": "day", "public_date": None, "evidence": f"{blk} block turned", "n_events": 0}
    return {"basis": None, "date": None, "evidence": "No fundamental evidence identified in the 120 days before onset",
            "n_events": 0}


__all__ = ["state_for", "strength", "sample_label", "block_frame", "block_pressure", "confirmation",
           "primary_driver", "interpret", "event_context", "analogue", "onset_window", "fundamental_onset",
           "START_BAND"]
