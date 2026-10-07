"""Rule-based driver labelling (A-E) using only information available at the move's start, plus a
separate HINDSIGHT outcome field. Nothing in this module may feed the live score."""
import numpy as np
import pandas as pd
from .config import SUPPLY_EVENT_TYPES, POLICY_EVENT_TYPES
from .event_study import events_around

LABELS = {"A": "Supply shock", "B": "Demand shock", "C": "Cost-push", "D": "Policy shock",
          "E": "Inventory cycle", "?": "Unclassified"}


def _aligned(panel, col, T, days, sign):
    if col not in panel or panel[col].dropna().empty:
        return np.nan
    a, b = panel[col].asof(T - pd.Timedelta(days=days)), panel[col].asof(T)
    if pd.isna(a) or pd.isna(b):
        return np.nan
    ch = (b / a - 1) if (a > 0 and b > 0) else (b - a)
    return sign * ch


def classify(inf, panel, events, thresholds=None, post_days=30):
    th = {"cost": 0.05, "dye": 0.03, "inv": 0.05, "retrace": 0.5, **(thresholds or {})}
    T, s = inf.start, inf.sign
    ev = events_around(events, T, before=60, after=14)
    ev_sup = ev[ev.event_type.isin(SUPPLY_EVENT_TYPES) & (ev.direction * s < 0)] if len(ev) else ev
    ev_pol = ev[ev.event_type.isin(POLICY_EVENT_TYPES) & (ev.direction * s < 0)] if len(ev) else ev
    cost = _aligned(panel, "derived.cost_idx", T, 30, s)
    dye = _aligned(panel, "dye.reactive", T, 30, s)
    inv = _aligned(panel, "ind.inventory", T, 30, -s)
    flags = {"D": len(ev_pol) > 0, "A": len(ev_sup) > 0,
             "C": bool(pd.notna(cost) and cost >= th["cost"]),
             "B": bool(pd.notna(dye) and dye >= th["dye"]),
             "E": bool(pd.notna(inv) and inv >= th["inv"])}
    # a direct supply event outranks a broad policy catalyst; policy is then an amplifier
    label = next((k for k in "ADCBE" if flags[k]), "?")
    amplifiers = "".join(k for k in "ABCDE" if flags[k] and k != label)
    reasons = []
    if flags["D"]:
        reasons.append(f"{len(ev_pol)} policy/environmental event(s)")
    if flags["A"]:
        reasons.append("supply events: " + "; ".join(f"{r.company or r.event_type} ({r.days_from_T:+d}d)" for r in ev_sup.itertuples()))
    if flags["C"]:
        reasons.append(f"cost index {cost:+.1%} in prior 30d")
    if flags["B"]:
        reasons.append(f"reactive dye {dye:+.1%} in prior 30d")
    if flags["E"]:
        reasons.append(f"inventory drawdown {inv:+.1%} in prior 30d")

    # ---- HINDSIGHT field: uses prices AFTER the move. Descriptive only, never a real-time signal.
    outcome, retr = "unknown (too recent)", np.nan
    after_t = inf.end + pd.Timedelta(days=post_days)
    if after_t <= panel.index[-1] and inf.end_price != inf.start_price:
        retr = (inf.end_price - panel["hacid.spot"].asof(after_t)) / (inf.end_price - inf.start_price)
        outcome = "false_breakout" if retr >= th["retrace"] else "sustained"
    return {"inflection": inf.id, "label": label, "type": LABELS[label], "amplifiers": amplifiers,
            "evidence": " | ".join(reasons),
            "historical_outcome": outcome,
            "hindsight_retrace_frac": float(retr) if pd.notna(retr) else np.nan}


def classify_all(infls, panel, events, **kw) -> pd.DataFrame:
    return pd.DataFrame([classify(i, panel, events, **kw) for i in infls])
