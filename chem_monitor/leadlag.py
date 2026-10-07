"""Leading-indicator research: which variables moved BEFORE the target?"""
import numpy as np
import pandas as pd
from .config import LEAD_DAYS, PRESSURE_SIGN, TARGET
from .features import change


def _weekly_changes(panel, freq):
    """Resample to a common grid FIRST, then difference each column on that shared index."""
    return panel.resample(freq).last().apply(lambda c: change(c, 1))


def lead_lag_table(panel: pd.DataFrame, target=TARGET, lags_days=(0, 7, 14, 30, 60), freq="W-FRI"):
    """corr( change in X at t-L , change in target at t ) on a weekly grid. Positive lag = X leads."""
    ch = _weekly_changes(panel, freq)
    y = ch[target]
    rows = []
    for c in ch.columns:
        if c == target or ch[c].notna().sum() < 30:
            continue
        for L in lags_days:
            k = int(round(L / 7))
            df = pd.concat([ch[c].shift(k), y], axis=1).dropna()
            if len(df) < 30:
                continue
            if df.iloc[:, 0].std() == 0 or df.iloc[:, 1].std() == 0:
                continue
            rows.append((c, L, float(df.iloc[:, 0].corr(df.iloc[:, 1])), len(df)))
    t = pd.DataFrame(rows, columns=["variable", "lead_days", "corr", "n"])
    return t.pivot(index="variable", columns="lead_days", values="corr") if len(t) else t


def best_leads(tbl: pd.DataFrame, min_abs=0.15):
    """For each variable the lead (>0) with the strongest absolute correlation."""
    if tbl.empty:
        return tbl
    lead_cols = [c for c in tbl.columns if c > 0]
    t = tbl[lead_cols].dropna(how="all")          # variables with no estimable lead (constant / sparse)
    if t.empty:
        return pd.DataFrame(columns=["best_lead_days", "corr"])
    best = t.abs().idxmax(axis=1)
    out = pd.DataFrame({"best_lead_days": best, "corr": [t.loc[v, best[v]] for v in t.index]})
    return out[out["corr"].abs() >= min_abs].sort_values("corr", key=lambda s: -s.abs())


def granger(panel: pd.DataFrame, target=TARGET, max_lag_weeks=8, freq="W-FRI"):
    """PREDICTIVE LEAD test (not causation): min Granger p-value across lags. Needs statsmodels."""
    try:
        from statsmodels.tsa.stattools import grangercausalitytests
    except ImportError:
        return None
    ch = _weekly_changes(panel, freq)
    y = ch[target]
    rows = []
    for c in ch.columns:
        if c == target or ch[c].notna().sum() < 60:
            continue
        df = pd.concat([y, ch[c]], axis=1).dropna()
        if len(df) < 60:
            continue
        try:
            res = grangercausalitytests(df.to_numpy(), maxlag=max_lag_weeks, verbose=False)
            p = {k: v[0]["ssr_ftest"][1] for k, v in res.items()}
            k = min(p, key=p.get)
            rows.append((c, k * 7, p[k]))
        except Exception:
            continue
    return pd.DataFrame(rows, columns=["variable", "best_lag_days", "min_p"]).sort_values("min_p")


def inflection_hit_rates(panel, infls, variables=None, leads=LEAD_DAYS, z=1.0):
    """Share of inflections preceded (within `lead` days) by a >=z-sigma move of the variable in the
    bullish/bearish direction, vs the base rate on random dates. lift>1 => informative."""
    variables = variables or [c for c in panel.columns if c != TARGET]
    rows = []
    for v in variables:
        s = panel[v].dropna()
        if len(s) < 120:
            continue
        sg = PRESSURE_SIGN.get(v, 1)
        for L in leads:
            bd = max(1, int(L * 5 / 7))
            c = change(s, bd).dropna()
            sd = c.std()
            if not sd or np.isnan(sd):
                continue
            base = ((c.abs() / sd) >= z).mean() / 2
            hits = n = 0
            for inf in infls:
                t0, tm = inf.start, inf.start - pd.Timedelta(days=L)
                if tm < s.index[0]:
                    continue
                a, b = s.asof(tm), s.asof(t0)
                if pd.isna(a) or pd.isna(b):
                    continue
                ch = (b / a - 1) if (a > 0 and b > 0) else (b - a)
                n += 1
                hits += (sg * inf.sign * ch / sd) >= z
            if n:
                rows.append((v, L, n, int(hits), hits / n, base, (hits / n) / base if base else np.nan))
    return pd.DataFrame(rows, columns=["variable", "lead_days", "n_inflections", "hits",
                                       "hit_rate", "base_rate", "lift"]).sort_values("lift", ascending=False)
