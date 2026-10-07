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


def export_unit_value(panel: pd.DataFrame):
    """USD per tonne, HS 292221. Primary signal = importer-reported (mirror) imports from China, summed
    over the reporting destinations, because China's own monthly reporting stops in Dec 2024. Labelled
    'unit value' - never an H-Acid spot price."""
    out = {}
    v, q = "export.hacid.value", "export.hacid.qty"
    if v in panel and q in panel:
        out["derived.export_uv_china"] = panel[v] / panel[q].replace(0, np.nan)
    mv = [c for c in panel if c.startswith("mirror.") and c.endswith(".value")]
    if mv:
        mq = [c.replace(".value", ".qty") for c in mv]
        ok = [(a, b) for a, b in zip(mv, mq) if b in panel]
        val = sum(panel[a].fillna(0) for a, _ in ok)
        qty = sum(panel[b].fillna(0) for _, b in ok)
        has = pd.concat([panel[a] for a, _ in ok], axis=1).notna().any(axis=1)
        out["derived.export_uv"] = (val / qty.replace(0, np.nan)).where(has)
        out["derived.export_qty_mirror"] = qty.where(has)
    elif "derived.export_uv_china" in out:
        out["derived.export_uv"] = out["derived.export_uv_china"]
    return pd.DataFrame(out) if out else None


def downstream_spread(dye: pd.Series, hacid_cost: pd.Series) -> pd.Series:
    """Reactive dye price minus H-Acid cost-equivalent (needs consistent units)."""
    return (dye - hacid_cost).rename("derived.dye_spread")
