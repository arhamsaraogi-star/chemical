"""Feature engineering: momentum, acceleration, cost index, margin, spreads, export unit value."""
import numpy as np
import pandas as pd
from .config import COST_WEIGHTS, COST_RECIPE, OTHER_COST_PER_T


def change(s: pd.Series, window: int) -> pd.Series:
    return s.pct_change(window, fill_method=None) if (s.dropna() > 0).all() else s.diff(window)


def price_features(p: pd.Series) -> pd.DataFrame:
    f = pd.DataFrame({"price": p})
    for w in (5, 20, 60, 250):
        f[f"mom{w}"] = p.pct_change(w, fill_method=None)
    f["accel5"] = f["mom5"] - f["mom5"].shift(5)
    f["accel20"] = f["mom20"] - f["mom20"].shift(20)
    f["vol20"] = p.pct_change(fill_method=None).rolling(20).std()
    return f


def cost_index(panel: pd.DataFrame, weights=COST_WEIGHTS):
    """Chain-linked FEEDSTOCK PRICE index (not a production-cost model). Each day the index moves by
    the weighted mean log-change of the inputs that have data on both days, so a series entering
    later (e.g. a newly collected feedstock) cannot create an artificial jump. Weights are equal by
    default because no sourced production coefficients are available (docs/methodology.md)."""
    cols = [c for c in weights if c in panel and panel[c].notna().any()]
    if not cols:
        return None
    w = pd.Series({c: weights[c] for c in cols})
    r = np.log(panel[cols]).diff()
    num = (r * w).sum(axis=1, skipna=True)
    den = (r.notna() * w).sum(axis=1)
    step = (num / den.replace(0, np.nan)).fillna(0)
    started = panel[cols].notna().any(axis=1).cummax()
    idx = 100 * np.exp(step.cumsum())
    return idx.where(started).rename("derived.cost_idx")


def cost_from_recipe(panel: pd.DataFrame, recipe=COST_RECIPE, other=OTHER_COST_PER_T):
    """Absolute cost per tonne from a physical recipe (t input / t H-Acid). None if no recipe."""
    cols = [c for c in recipe if c in panel]
    if not cols:
        return None
    return (sum(panel[c] * recipe[c] for c in cols) + other).rename("derived.cost_abs")


def margins(price: pd.Series, cost_idx: pd.Series = None, cost_abs: pd.Series = None) -> pd.DataFrame:
    out = pd.DataFrame(index=price.index)
    if cost_abs is not None:
        out["margin_abs"] = price - cost_abs
        out["margin_ratio"] = price / cost_abs
    if cost_idx is not None:
        first = pd.concat([price, cost_idx], axis=1).dropna().index[0]
        pi = 100 * price / price.loc[first]
        ci = 100 * cost_idx / cost_idx.loc[first]
        out["spread_idx"] = pi - ci
        out["ratio_idx"] = pi / ci
    return out


def _mirror_uv(panel, tag):
    mv = [c for c in panel if c.startswith("mirror.") and c.endswith(f".{tag}.value")]
    ok = [(a, a.replace(".value", ".qty")) for a in mv if a.replace(".value", ".qty") in panel]
    if not ok:
        return None, None
    val = sum(panel[a].fillna(0) for a, _ in ok)
    qty = sum(panel[b].fillna(0) for _, b in ok)
    has = pd.concat([panel[a] for a, _ in ok], axis=1).notna().any(axis=1)
    return (val / qty.replace(0, np.nan)).where(has), qty.where(has)


def mirror_chain(obs: pd.DataFrame, tag: str, date_col: str = "obs_date"):
    """Like-for-like aggregates of importer-reported trade with China (HS tag 'hacid' / 'rdye').
    Countries report with different lags, so a plain sum jumps when a reporter is missing. Each month's
    change is computed only over reporters present in BOTH months, then chained:
      qty_index  (=100 at the first month)   unit value (USD/t, anchored at the first month's actual value)
    Built from raw monthly records (no carry-forward), placed on `date_col` (economic or known date)."""
    d = obs[obs["series"].astype(str).str.match(rf"mirror\.\w+\.{tag}\.(qty|value)$")].dropna(subset=[date_col])
    if d.empty:
        return None
    d = d.assign(rep=d["series"].str.split(".").str[1], kind=d["series"].str.split(".").str[-1],
                 month=d["obs_date"].dt.to_period("M"))
    q = d[d.kind == "qty"].pivot_table(index="month", columns="rep", values="value", aggfunc="last")
    v = d[d.kind == "value"].pivot_table(index="month", columns="rep", values="value", aggfunc="last").reindex_like(q)
    when = d.groupby("month")[date_col].max()
    rows, qi, uv, prev = [], 100.0, None, None
    for m in q.index:
        cur = q.loc[m].dropna()
        cur = cur[cur > 0]
        if prev is None:
            uv = float(v.loc[m, cur.index].sum() / cur.sum()) if len(cur) else np.nan
        else:
            common = [r for r in cur.index if r in prev.index and pd.notna(v.loc[m, r]) and pd.notna(v.loc[prev.name, r])]
            if common:
                q0, q1 = q.loc[prev.name, common].sum(), q.loc[m, common].sum()
                u0 = v.loc[prev.name, common].sum() / q0
                u1 = v.loc[m, common].sum() / q1
                qi, uv = qi * q1 / q0, uv * u1 / u0
        rows.append((when.loc[m], qi, uv, len(cur)))
        prev = q.loc[m].dropna()
        prev.name = m
    out = pd.DataFrame(rows, columns=["date", "qty_index", "uv", "n_reporters"]).set_index("date")
    return out


def export_unit_value(panel: pd.DataFrame):
    """USD per tonne. H-Acid (HS 292221): importer-reported (mirror) imports from China summed over the
    reporting destinations, because China's own monthly reporting stops in Dec 2024. Reactive dyes
    (HS 320416) the same way, as a downstream-demand proxy. Unit values are labelled as such - never
    presented as a spot price. CNY conversions use ECB daily USD/CNY."""
    out = {}
    v, q = "export.hacid.value", "export.hacid.qty"
    if v in panel and q in panel:
        out["derived.export_uv_china"] = panel[v] / panel[q].replace(0, np.nan)
    uv, qty = _mirror_uv(panel, "hacid")
    if uv is not None:
        out["derived.export_uv"], out["derived.export_qty_mirror"] = uv, qty
    elif "derived.export_uv_china" in out:
        out["derived.export_uv"] = out["derived.export_uv_china"]
    duv, dqty = _mirror_uv(panel, "rdye")
    if duv is not None:
        out["derived.rdye_uv"], out["derived.rdye_qty"] = duv, dqty
    fx = panel.get("fx.usdcny")
    if fx is not None and "derived.export_uv" in out:
        out["derived.export_uv_cny"] = out["derived.export_uv"] * fx.ffill()
    return pd.DataFrame(out) if out else None


def downstream_spread(dye: pd.Series, hacid_cost: pd.Series) -> pd.Series:
    """Reactive dye price minus H-Acid cost-equivalent (needs consistent units)."""
    return (dye - hacid_cost).rename("derived.dye_spread")
