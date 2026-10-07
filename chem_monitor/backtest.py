"""As-of detection backtest: using ONLY information that was public at the time, how many days
before the obvious price move would the system have alerted - and how many false alarms?"""
import numpy as np
import pandas as pd
from .config import TARGET, ALERT_THRESHOLD, BACKTEST_PRE_DAYS, EPISODE_GAP
from .inflections import live_trigger


def alert_episodes(scored: pd.DataFrame, threshold=ALERT_THRESHOLD, gap=EPISODE_GAP) -> pd.DataFrame:
    """First day of each run of score>=threshold (runs closer than `gap` bdays are merged)."""
    hot = scored[(scored["score"] >= threshold) & (scored["status"] == "ok")]
    rows, last_i = [], None
    pos = {d: i for i, d in enumerate(scored.index)}
    for d, r in hot.iterrows():
        if last_i is None or pos[d] - last_i > gap:
            rows.append((d, r["direction"], r["score"]))
        last_i = pos[d]
    return pd.DataFrame(rows, columns=["alert_date", "direction", "score"])


def detection_backtest(infls, pit_panel, scored, threshold=ALERT_THRESHOLD, pre_days=BACKTEST_PRE_DAYS):
    """infls: inflections from the ECONOMIC panel (true starts). pit_panel/scored: INFORMATION axis."""
    price = pit_panel[TARGET]
    rows = []
    for i in infls:
        win = scored.loc[i.start - pd.Timedelta(days=pre_days): i.end]
        ok = win[(win["score"] >= threshold) & (win["direction"] == i.direction) & (win["status"] == "ok")]
        alert = ok.index[0] if len(ok) else pd.NaT
        trig = live_trigger(price, i.start, i.sign)
        rows.append({"inflection": i.id, "direction": i.direction, "true_start": i.start,
                     "score_alert": alert, "price_rule_trigger": trig,
                     "alert_minus_start_days": (alert - i.start).days if pd.notna(alert) else np.nan,
                     "rule_minus_start_days": (trig - i.start).days if pd.notna(trig) else np.nan,
                     "days_earlier_than_price_rule": (trig - alert).days if pd.notna(alert) and pd.notna(trig) else np.nan,
                     "scored_history_available": bool((win["status"] == "ok").any())})
    tbl = pd.DataFrame(rows)
    eps = alert_episodes(scored, threshold)
    def covered(d):
        return any(i.start - pd.Timedelta(days=pre_days) <= d <= i.end + pd.Timedelta(days=EPISODE_GAP) for i in infls)
    false_alarms = eps[~eps["alert_date"].map(covered)] if len(eps) else eps
    evaluable = tbl[tbl["scored_history_available"]]
    summary = {"threshold": threshold, "inflections_evaluable": len(evaluable),
               "detected": int(evaluable["score_alert"].notna().sum()),
               "median_days_earlier_than_price_rule": float(evaluable["days_earlier_than_price_rule"].median()),
               "alert_episodes": len(eps), "false_alarm_episodes": len(false_alarms)}
    return tbl, summary, false_alarms
