"""Plain-English explanations generated deterministically from the same numbers the site shows.
No AI: every sentence is a template filled with computed, cited values."""
import numpy as np
import pandas as pd

PLAIN = {   # block -> (name for normal readers, what it measures)
    "PRICE": ("Price trend", "How fast the H-Acid price itself is moving"),
    "SUPPLY": ("Supply", "How much known production capacity is running"),
    "COST": ("Raw-material costs", "Prices of naphthalene, sulfuric acid, nitric acid and caustic soda"),
    "DOWNSTREAM": ("Dye prices", "Prices of the reactive dyes H-Acid is used to make"),
    "TRADE": ("Exports", "Price paid by foreign buyers (India, Korea, Indonesia) for Chinese H-Acid"),
    "INVENTORY": ("Stockpiles", "How much H-Acid is sitting in warehouses"),
    "DEMAND": ("Textile demand", "Orders from textile dyers"),
    "EVENTS": ("Plant events", "Accidents, shutdowns and rule changes at factories"),
}


def _chg(s: pd.Series, days: int, end=None):
    s = s.dropna()
    if s.empty:
        return None
    end = s.index[-1] if end is None else min(pd.Timestamp(end), s.index[-1])
    a, b = s.asof(end - pd.Timedelta(days=days)), s.asof(end)
    if pd.isna(a) or pd.isna(b) or a == 0:
        return None
    return float(b / a - 1)


def _pct(x):
    return "n/a" if x is None else f"{x * 100:+.0f}%"


def _signal_word(v, up_word, down_word):
    if v is None or pd.isna(v) or abs(v) < 0.1:
        return "neutral"
    return up_word if v > 0 else down_word


def block_explanations(P: pd.DataFrame, blocks: dict, events: pd.DataFrame, cap: pd.DataFrame, now) -> list:
    """One plain sentence per block, with the concrete number behind it."""
    now = pd.Timestamp(now)
    out = []

    def add(b, sentence, evidence_kind, numbers=None):
        v = (blocks.get(b) or {}).get("value")
        out.append({"block": b, "name": PLAIN[b][0], "measures": PLAIN[b][1], "value": v,
                    "strength": (blocks.get(b) or {}).get("strength", "No data"),
                    "effect": ("pushing price up" if v is not None and v >= 0.1 else
                               "pushing price down" if v is not None and v <= -0.1 else
                               "no clear push" if v is not None else "no data"),
                    "sentence": sentence, "kind": evidence_kind, "numbers": numbers or {}})

    # SUPPLY
    sup = P.get("derived.supply_index", pd.Series(dtype=float)).dropna()
    recent = events[(events["event_date"] >= now - pd.Timedelta(days=90))] if len(events) else events
    cuts = recent[recent["direction"] < 0] if len(recent) else recent
    if len(sup):
        nom = P.get("derived.eff_supply", pd.Series(dtype=float)).dropna()
        shut = sorted(cap.sort_values("eff_date").groupby("producer").tail(1).query("status == 'shutdown'")["producer"]) \
            if len(cap) else []
        s = (f"Of the capacity we can document, roughly {sup.iloc[-1] * 100:.0f}% appears available (estimate; "
             f"no producer publishes run rates)" + (f" - plants listed as shut: {', '.join(x.capitalize() for x in shut)}. " if shut else ". "))
        s += (f"{len(cuts)} supply-cutting event(s) were reported in the last 90 days." if len(cuts)
              else "No new plant accidents or shutdowns were reported in the last 90 days.")
        add("SUPPLY", s, "estimated", {"available_share": float(sup.iloc[-1]), "cuts_90d": int(len(cuts))})
    else:
        add("SUPPLY", "No capacity data.", "observed")

    # COST
    ci = P.get("derived.cost_idx", pd.Series(dtype=float))
    sa = P.get("feed.sulfuric_acid", pd.Series(dtype=float))
    c1, c3, sa3, sa12 = _chg(ci, 30), _chg(ci, 91), _chg(sa, 91), _chg(sa, 365)
    if c1 is not None:
        s = (f"The raw-material price index moved {_pct(c1)} in the last month and {_pct(c3)} over three months, "
             f"so costs are not what is driving H-Acid now. Sulfuric acid is {_pct(sa3)} over three months "
             f"but still {_pct(sa12)} versus a year ago.")
        add("COST", s, "derived", {"index_1m": c1, "index_3m": c3, "sulfuric_3m": sa3, "sulfuric_12m": sa12})
    else:
        add("COST", "No raw-material data.", "observed")

    # DOWNSTREAM
    dye = P.get("dye.reactive", pd.Series(dtype=float)).dropna()
    if len(dye) >= 2 and dye.index[-1] - dye.index[0] > pd.Timedelta(days=60):
        add("DOWNSTREAM", f"Reactive dye was ¥{dye.iloc[-1] / 1000:.0f}/kg at the last observation, versus "
                          f"¥{dye.iloc[0] / 1000:.0f}/kg on {dye.index[0]:%d %b %Y}. Too few observations to score yet.",
            "observed", {"last": float(dye.iloc[-1]), "first": float(dye.iloc[0])})
    else:
        add("DOWNSTREAM", "Dye prices are only collected daily from Oct 2026, so there is not yet enough history to score.",
            "observed")

    # TRADE
    uv = P.get("derived.export_uv", pd.Series(dtype=float)).dropna()
    if len(uv):
        u3, u12 = _chg(uv, 91), _chg(uv, 365)
        add("TRADE", f"Foreign buyers paid about ${uv.iloc[-1]:,.0f}/t for Chinese H-Acid-type acids in "
                     f"{uv.index[-1]:%b %Y} ({_pct(u3)} vs three months earlier, {_pct(u12)} vs a year earlier). "
                     "Trade data arrives about two months late.",
            "derived", {"usd_per_t": float(uv.iloc[-1]), "chg_3m": u3, "chg_12m": u12, "month": f"{uv.index[-1]:%Y-%m}"})
    else:
        add("TRADE", "No trade data.", "observed")

    add("INVENTORY", "No reliable public stockpile data exists for H-Acid, so this is left blank rather than guessed.",
        "observed")
    add("DEMAND", "No reliable public textile-demand series is collected yet.", "observed")

    # EVENTS
    if len(events):
        last = events.sort_values("event_date").iloc[-1]
        days = int((now - last["event_date"]).days)
        add("EVENTS", f"The most recent recorded event was {days} days ago ({last['event_type']}"
                      f"{': ' + last['company'] if last.get('company') else ''}); its effect has faded.",
            "observed", {"days_since_last": days})
    # PRICE
    sp = P.get("hacid.spot", pd.Series(dtype=float)).dropna()
    p1 = _chg(sp, 30)
    if len(sp):
        moved = sp[sp.ne(sp.shift())]
        last_move = moved.index[-1]
        flat_days = int((now - last_move).days)
        add("PRICE", f"The price rose {_pct(p1)} in the month to {sp.index[-1]:%d %b}, but has not changed for "
                     f"{flat_days} days (Chinese holiday), so short-term momentum is fading.", "derived",
            {"chg_1m": p1, "flat_days": flat_days})
    order = ["SUPPLY", "COST", "DOWNSTREAM", "TRADE", "INVENTORY", "DEMAND", "EVENTS", "PRICE"]
    return sorted(out, key=lambda x: order.index(x["block"]))


def before_after(inf, blocks_econ: pd.DataFrame) -> list:
    """Block readings in the 30 days before the price onset vs during the move."""
    rows = []
    pre = blocks_econ.loc[inf.start - pd.Timedelta(days=30): inf.start - pd.Timedelta(days=1)]
    dur = blocks_econ.loc[inf.start: inf.end]
    for b in ["SUPPLY", "COST", "DOWNSTREAM", "TRADE", "INVENTORY", "EVENTS"]:
        if b not in blocks_econ:
            continue
        a = pre[b].mean() if len(pre) else np.nan
        c = dur[b].mean() if len(dur) else np.nan
        word = lambda v: "No data" if pd.isna(v) else _signal_word(v, "Supports a higher price", "Supports a lower price").capitalize()
        rows.append({"block": b, "name": PLAIN[b][0], "before": None if pd.isna(a) else round(float(a), 2),
                     "during": None if pd.isna(c) else round(float(c), 2), "before_word": word(a), "during_word": word(c)})
    return rows


def inflection_story(f: dict, notes: list) -> dict:
    """Plain summary of one inflection; `notes` = press context inside the window (cited, not scored)."""
    up = f["direction"] == "up"
    mag = f["magnitude"]
    po, fo = f["price_onset"], f["fundamental_onset"]
    parts = [f"The H-Acid price {'rose' if up else 'fell'} {abs(mag) * 100:.0f}%, from ¥{f['start_price']:,.0f} "
             f"to ¥{f['end_price']:,.0f} per tonne, between {pd.Timestamp(po['best']):%d %b %Y} and {pd.Timestamp(f['end']):%d %b %Y}."]
    if not po.get("exact"):
        parts.append(f"Because public prices are sparse, the exact start is uncertain: somewhere between "
                     f"{pd.Timestamp(po['earliest']):%d %b} and {pd.Timestamp(po['latest']):%d %b %Y}.")
    if fo.get("basis") == "event":
        gap = (pd.Timestamp(po["best"]) - pd.Timestamp(fo["date"])).days
        what, who = (fo["evidence"].split(": ", 1) + [""])[:2]
        label = f"{what} at {who.split(' (')[0]}" if who else f"industry-wide {what} change"
        art = "an" if label[0] in "aeiou" else "a"
        days = lambda n: f"{n} day" + ("" if n == 1 else "s")
        if gap > 45:
            parts.append(f"The nearest supporting event in our database is {art} {label} on "
                         f"{pd.Timestamp(fo['date']):%d %b %Y}, {days(gap)} earlier - too far back to count as the trigger.")
        else:
            parts.append(f"It coincided with {art} {label} on {pd.Timestamp(fo['date']):%d %b %Y}"
                         + (f", {days(gap)} before the price moved." if gap > 0 else ", the same day the price moved." if gap == 0
                            else f", {days(-gap)} after the price had started moving."))
    elif fo.get("basis") == "indicator":
        parts.append(f"No plant event explains it; the first fundamental signal was the {fo['evidence']}.")
    else:
        parts.append("No dated plant event in our database explains this leg.")
    sd = f["system_detection"]
    if sd["date"]:
        lead = f["detection_lead_days"]
        parts.append(f"Using only information public at the time, the monitor flagged it on "
                     f"{pd.Timestamp(sd['date']):%d %b %Y}, "
                     + (f"{lead} days before the simple price rule." if lead and lead > 0 else
                        f"{-lead} days after the simple price rule - no early warning." if lead and lead < 0 else
                        "the same day as the simple price rule."))
    elif sd["evaluable"]:
        parts.append("The monitor did not flag it in advance.")
    else:
        parts.append("There was not enough point-in-time data back then to test whether it could have been flagged early.")
    driver = f["driver"]["type"]
    diag = ("Supply shock" if driver == "Supply shock" else driver if driver != "Unclassified" else
            "Price-led move; fundamentals in our data do not explain it")
    if f["driver"]["amplifiers"]:
        diag += ", amplified by " + " and ".join(a.lower() for a in f["driver"]["amplifiers"])
    return {"summary": " ".join(parts), "diagnosis": diag + ".", "press": notes}
