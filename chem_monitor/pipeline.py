"""Orchestration. Two datasets, two purposes:
  economic axis    -> historical forensics (true dates of prices/events/capacity)
  information axis -> anything that pretends to be live (scoring, alerts, detection backtest)"""
from dataclasses import dataclass
from pathlib import Path
import pandas as pd
from . import quality, db, series, features, inflections, event_study, leadlag, classify, score, alerts, backtest
from .config import DB_PATH, OUT_DIR, TARGET, COST_WEIGHTS, ALERT_THRESHOLD, VINTAGE_POLICY


@dataclass
class Dataset:
    panel: pd.DataFrame
    dispersion: dict
    events: pd.DataFrame
    capacity: pd.DataFrame
    infls: list
    time_axis: str
    vintage_excluded: dict = None


def build_dataset(path=DB_PATH, time_axis="economic", as_of=None, vintage_policy=VINTAGE_POLICY,
                  index_end=None) -> Dataset:
    obs, ev, cap = db.load_observations(path), db.load_events(path), db.load_capacity(path)
    unk = {}
    if time_axis == "information":              # unknown publication dates: exclude (default) or opt in
        obs, unk["observations"] = db.apply_vintage_policy(obs, "obs_date", vintage_policy)
        ev, unk["events"] = db.apply_vintage_policy(ev, "event_date", vintage_policy)
        cap, unk["capacity"] = db.apply_vintage_policy(cap, "eff_date", vintage_policy)
    if as_of is not None:                       # hard as-of cut for events and capacity too
        as_of = pd.Timestamp(as_of)
        ev, cap = ev[ev["known_date"] <= as_of], cap[cap["known_date"] <= as_of]
    panel, disp = series.build_panel(obs, time_axis, as_of, index_end=as_of if as_of is not None else index_end)
    idx = panel.index
    total_nom = None
    if len(cap):
        sup = series.effective_supply(cap, idx, time_axis)
        panel["derived.eff_supply"] = sup["eff_supply_t"]
        panel["derived.supply_index"] = sup["supply_index"]
        total_nom = sup["nominal_t"]
    panel["derived.event_pressure"] = series.event_pressure(ev, idx, total_nom, time_axis=time_axis)
    ci = features.cost_index(panel, COST_WEIGHTS)
    if ci is not None:
        panel["derived.cost_idx"] = ci
        for c, s in features.margins(panel[TARGET], cost_idx=ci).items():
            panel[f"derived.{c}"] = s
    ca = features.cost_from_recipe(panel)
    if ca is not None:
        panel["derived.cost_abs"] = ca
        for c, s in features.margins(panel[TARGET], cost_abs=ca).items():
            panel[f"derived.{c}"] = s
    uv = features.export_unit_value(panel)
    if uv is not None:
        for c in uv:
            panel[c] = uv[c]
    # like-for-like mirror aggregates from raw monthly records (replace the naive panel sums)
    dcol = "obs_date" if time_axis == "economic" else "known_date"
    for tag, (uvc, qc) in {"hacid": ("derived.export_uv", "derived.export_qty_mirror"),
                           "rdye": ("derived.rdye_uv", "derived.rdye_qty")}.items():
        mc = features.mirror_chain(obs, tag, dcol)
        if mc is not None:
            mc = mc[mc.index <= idx[-1]]
            pos = idx.searchsorted(mc.index).clip(max=len(idx) - 1)
            for src, dst in (("uv", uvc), ("qty_index", qc)):
                s_ = pd.Series(mc[src].to_numpy(), index=idx[pos]).groupby(level=0).last()
                panel[dst] = s_.reindex(idx).ffill(limit=30)
    if "derived.export_uv" in panel and "fx.usdcny" in panel:
        panel["derived.export_uv_cny"] = panel["derived.export_uv"] * panel["fx.usdcny"].ffill()
    observed = disp[TARGET].index if TARGET in disp else None
    return Dataset(panel, disp, ev, cap, inflections.detect(panel[TARGET], observed=observed), time_axis, unk)


def run_forensics(path=DB_PATH, out=OUT_DIR, plots=True, threshold=ALERT_THRESHOLD) -> dict:
    """Phases 1-3 on the economic axis + a point-in-time detection backtest on the information axis."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ds = build_dataset(path, "economic")
    r = {"dataset": ds}
    ds.panel.to_csv(out / "panel.csv")
    if TARGET in ds.dispersion:
        ds.dispersion[TARGET].to_csv(out / "hacid_source_dispersion.csv")
    r["quality"] = quality.data_quality(db.load_observations(path), ds.panel, db.load_capacity(path), db.load_events(path))
    r["quality"].to_csv(out / "data_quality.csv")
    r["inflections"] = inflections.to_frame(ds.infls)
    r["inflections"].to_csv(out / "inflections.csv", index=False)
    r["start_sensitivity"] = inflections.start_sensitivity(ds.panel[TARGET])
    r["start_sensitivity"].to_csv(out / "start_sensitivity.csv")
    r["windows"] = event_study.event_windows(ds.panel, ds.infls)
    r["windows"].to_csv(out / "event_windows.csv", index=False)
    r["pre_move"] = event_study.pre_move_table(r["windows"])
    r["pre_move"].to_csv(out / "pre_move_changes.csv")
    r["classification"] = classify.classify_all(ds.infls, ds.panel, ds.events)
    r["classification"].to_csv(out / "classification.csv", index=False)
    r["leadlag"] = leadlag.lead_lag_table(ds.panel)
    r["leadlag"].to_csv(out / "leadlag_corr.csv")
    r["best_leads"] = leadlag.best_leads(r["leadlag"])
    r["hit_rates"] = leadlag.inflection_hit_rates(ds.panel, ds.infls)
    r["hit_rates"].to_csv(out / "hit_rates.csv", index=False)
    g = leadlag.granger(ds.panel)
    if g is not None:
        g.to_csv(out / "predictive_lead_granger.csv", index=False)
    # diagnostic only - uses the full sample, so it must never reach live scoring
    r["weights_fullsample_DIAGNOSTIC"] = score.fit_weights(ds.panel)
    r["weights_fullsample_DIAGNOSTIC"].to_csv(out / "diagnostic_fullsample_weights.csv")

    # ---- point-in-time part
    pit = build_dataset(path, "information")
    comps = score.components(pit.panel)
    r["vintage_weights"] = score.vintage_weights(pit.panel, comps)
    r["vintage_weights"].to_csv(out / "vintage_weights.csv")
    r["scored"] = score.compute_score(pit.panel, r["vintage_weights"], comps)
    r["scored"].to_csv(out / "score_history_pit.csv")
    r["backtest"], r["backtest_summary"], r["false_alarms"] = backtest.detection_backtest(
        ds.infls, pit.panel, r["scored"], threshold)
    r["backtest"].to_csv(out / "detection_backtest.csv", index=False)
    r["false_alarms"].to_csv(out / "false_alarms.csv", index=False)
    r["pit"] = pit
    if plots:
        try:
            r["plot"] = alerts.plot_forensics(ds.panel, ds.infls, r["scored"], str(out / "forensics.png"))
        except ImportError:
            pass
    return r


def run_daily(path=DB_PATH, out=OUT_DIR, collectors=None, webhook=None, alert_threshold=ALERT_THRESHOLD,
              data_dir=None):
    """Ingest (safe runner) -> rebuild DB from the CSV store -> score on the information axis with
    weights refit from matured history only. collectors=[] skips ingestion (offline / demo)."""
    from . import store
    from .config import DATA_DIR
    from .ingestion import live_collectors, runner
    cs = live_collectors() if collectors is None else collectors
    if cs:
        runner.run_all(cs, "live", data_dir or DATA_DIR)
        store.rebuild(path, data_dir or DATA_DIR)
    ds = build_dataset(path, "information")
    comps = score.components(ds.panel)
    W = score.vintage_weights(ds.panel, comps)      # recomputed every run; nothing read from disk
    scored = score.compute_score(ds.panel, W, comps)
    ts = scored["score"].dropna().index[-1]
    w_now = W.loc[ts]
    text = alerts.render_dashboard(ts, scored, comps, ds.panel, ds.events, ds.infls, w_now)
    print(text)
    if scored.loc[ts, "score"] >= alert_threshold and scored.loc[ts, "status"] != "ok":
        print(f"[gate] raw score {scored.loc[ts, 'score']:.0f} suppressed: coverage "
              f"{scored.loc[ts, 'coverage']:.0%} below minimum")
    if scored.loc[ts, "score"] >= alert_threshold and scored.loc[ts, "status"] == "ok":
        alerts.send(alerts.build_alert(ts, scored, comps, ds.panel, ds.events, ds.infls, w_now), webhook)
    return scored.loc[ts]
