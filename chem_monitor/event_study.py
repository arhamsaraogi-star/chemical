"""Standardised event windows (T-90 ... T+90) around every inflection."""
import numpy as np
import pandas as pd
from .config import EVENT_OFFSETS


def _chg(a, b):
    if pd.isna(a) or pd.isna(b):
        return np.nan
    return (b / a - 1) if (a > 0 and b > 0) else (b - a)


def event_windows(panel: pd.DataFrame, infls, offsets=EVENT_OFFSETS, anchor="start") -> pd.DataFrame:
    """Long table: inflection x variable x offset -> value and the change over the interval between
    the offset date and T, oriented forward in time (offset<0: offset->T, offset>0: T->offset)."""
    rows = []
    for inf in infls:
        T = getattr(inf, anchor)
        vT = panel.asof(T)
        for off in offsets:
            ts = T + pd.Timedelta(days=off)
            if ts < panel.index[0] or ts > panel.index[-1]:
                continue
            v = panel.asof(ts)
            for col in panel.columns:
                if off < 0:
                    c = _chg(v[col], vT[col])
                elif off > 0:
                    c = _chg(vT[col], v[col])
                else:
                    c = 0.0
                rows.append((inf.id, inf.direction, col, off, v[col], c))
    return pd.DataFrame(rows, columns=["inflection", "direction", "variable", "offset", "value", "chg"])


def pre_move_table(windows: pd.DataFrame) -> pd.DataFrame:
    """Variable x offset(<0) mean change *into* T from T-k, by inflection direction."""
    w = windows[windows.offset < 0]
    return w.pivot_table(index=["direction", "variable"], columns="offset", values="chg", aggfunc="mean")


def events_around(events: pd.DataFrame, T, before=90, after=30) -> pd.DataFrame:
    if events.empty:
        return events
    m = (events.event_date >= T - pd.Timedelta(days=before)) & (events.event_date <= T + pd.Timedelta(days=after))
    return events[m].assign(days_from_T=lambda d: (d.event_date - T).dt.days)
