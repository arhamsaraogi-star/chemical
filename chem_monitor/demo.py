"""Synthetic end-to-end demo. The numbers are INVENTED - it only proves the plumbing works and
shows the expected input shapes. Replace with real data via the import-* commands."""
import shutil
from pathlib import Path
import numpy as np
import pandas as pd
from . import db, pipeline


def synth(seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-10-02", "2026-10-07")
    n = len(idx)
    shocks = [("2024-05-06", .25, 25), ("2025-04-14", .30, 20), ("2025-06-23", .14, 5),
              ("2025-10-06", -.18, 30), ("2026-05-04", .40, 30)]
    drift = np.zeros(n)
    for d, mag, days in shocks:
        i = idx.searchsorted(pd.Timestamp(d))
        drift[i:i + days] += mag / days
    base = 18000 * np.exp(np.cumsum(drift) + np.cumsum(rng.normal(0, .003, n)))
    P = pd.Series(base, idx)
    lead = lambda s, k: s.shift(-k).ffill()          # series that moves k bdays BEFORE P
    lag = lambda s, k: s.shift(k).bfill()
    noise = lambda s, sd: s * np.exp(rng.normal(0, sd, n))
    rows = []

    def add(series, s, source, tier, **kw):
        rows.append(pd.DataFrame({"obs_date": s.index, "value": s.values, "series": series,
                                  "source": source, "tier": tier, **kw}))
    add("hacid.spot", noise(P, .004), "guidechem", 2, price_type="spot", market="domestic")
    add("hacid.spot", noise(P, .006), "baiinfo", 2, price_type="spot", market="domestic")
    add("hacid.spot", noise(P, .010), "chemanalyst", 3, price_type="index", market="domestic")
    add("hacid.quote", noise(lead(P, 5), .005), "producer_A", 1, quote_kind="quotation")
    add("hacid.fob", noise(lag(P, 3) / 7.2 * 1.05, .006), "pricewatch", 3, market="export", currency="USD")
    naph = 5000 * (lead(P, 12) / 18000) ** .5
    add("feed.naphthalene_refined", noise(naph, .004), "sunsirs", 2)
    add("feed.caustic_soda", noise(pd.Series(800.0, idx), .01), "sunsirs", 2)
    add("dye.reactive", noise(lag(P, 10) ** .6, .004), "sunsirs", 2)
    util = 0.75 - 0.5 * (np.log(lead(P, 10)).diff(20).fillna(0)).clip(lower=0)
    add("ind.utilization", util * 100, "baiinfo", 2, unit="%")
    inv = 100 * (18000 / lead(P, 14)) ** .8
    add("ind.inventory", noise(inv, .01), "baiinfo", 2, unit="idx")
    m = pd.date_range("2023-10-31", "2026-09-30", freq="ME")
    qty = pd.Series(rng.normal(400, 20, len(m)), m)
    add("export.hacid.qty", qty, "customs", 1, unit="t")
    add("export.hacid.value", qty * P.reindex(m, method="nearest") * .14 * rng.normal(1, .02, len(m)), "customs", 1, unit="USD")
    obs = pd.concat(rows, ignore_index=True)
    obs["confidence"] = 1.0
    # information time: daily data public next business day, customs ~20 days after month-end
    obs["pub_date"] = obs["obs_date"] + pd.offsets.BDay(1)
    cm = obs["source"] == "customs"
    obs.loc[cm, "pub_date"] = obs.loc[cm, "obs_date"] + pd.Timedelta(days=20)
    obs["source_family"] = None
    obs.loc[obs["source"] == "chemanalyst", "source_family"] = "baiinfo"   # republishes Baiinfo
    events = pd.DataFrame([
        ("2025-04-10", "accident", "YaDong", 20000, -1, 3), ("2025-06-22", "environmental", "YaDong", 20000, -1, 3),
        ("2025-08-15", "restart", "YaDong", 20000, 1, 2), ("2024-05-01", "maintenance", "ProducerB", 8000, -1, 2)],
        columns=["event_date", "event_type", "company", "capacity_t", "direction", "severity"])
    events["announce_date"] = pd.to_datetime(events["event_date"]) + pd.to_timedelta([3, 2, 1, 1], unit="D")
    cap = pd.DataFrame([
        ("YaDong", "2023-10-01", 20000, .8, 1, "operating"), ("YaDong", "2025-04-10", 20000, .8, 0, "shutdown"),
        ("YaDong", "2025-08-15", 20000, .7, 1, "operating"),
        ("ProdB", "2023-10-01", 12000, .8, 1, "operating"), ("ProdC", "2023-10-01", 10000, .75, 1, "operating"),
        ("ProdD", "2023-10-01", 9000, .7, 1, "operating"), ("ProdE", "2023-10-01", 9000, .7, 1, "operating")],
        columns=["producer", "eff_date", "nominal_t", "utilization", "availability", "status"])
    later = cap["eff_date"] > "2023-10-01"
    cap["published_at"] = pd.to_datetime(cap["eff_date"])            # baseline: known when stated
    cap.loc[later, "published_at"] += pd.Timedelta(days=3)         # changes become public 3 days later
    return obs, events, cap


def run_demo(path="data/demo.db", out="out/demo"):
    Path(path).unlink(missing_ok=True)
    obs, ev, cap = synth()
    db.upsert_observations(obs, path)
    db.upsert_events(ev, path)
    db.upsert_capacity(cap, path)
    r = pipeline.run_forensics(path, out)
    pd.set_option("display.width", 200, "display.max_columns", 20)
    from . import quality
    print(quality.render(r["quality"]))
    print("\n== INFLECTIONS ==")
    print(r["inflections"][["id", "direction", "start", "trigger", "end", "magnitude", "shape", "detection_lag_days"]].to_string(index=False))
    print("\n== CAUSAL LABELS ==")
    print(r["classification"][["inflection", "type", "amplifiers", "historical_outcome", "evidence"]].to_string(index=False))
    print("\n== BEST LEADING INDICATORS (weekly corr) ==")
    print(r["best_leads"].round(2).to_string())
    print("\n== TOP HIT-RATE LIFT ==")
    print(r["hit_rates"].head(8).round(2).to_string(index=False))
    print("\n== START-DATE SENSITIVITY (band 0.10/0.25/0.40) ==")
    print(r["start_sensitivity"].to_string())
    print("\n== VINTAGE WEIGHTS (latest) ==")
    print(r["vintage_weights"].iloc[-1].round(3).to_string())
    print("\n== AS-OF DETECTION BACKTEST ==")
    print(r["backtest"].to_string(index=False))
    print(r["backtest_summary"])
    print("\n== LIVE DAILY RUN ==")
    pipeline.run_daily(path, out, collectors=[], alert_threshold=0)


if __name__ == "__main__":
    run_demo()
