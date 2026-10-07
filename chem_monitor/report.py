"""Build the static website's JSON artifacts (site/data/**). Pure function of the CSV store.

Every number written here carries its epistemic kind (observed / derived / estimated / inferred /
ai_extracted) and, where it comes from a source, the source family and URL.
"""
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
from . import db, store, quality, inflections, classify, leadlag, score, backtest, signals, series as series_mod
from .config import (DATA_DIR, DB_PATH, SITE_DATA_DIR, TARGET, ALERT_THRESHOLD, FRESHNESS_DAYS, CHEMICAL_ID,
                     BLOCKS, BLOCK_WEIGHTS, BANDS, MOVE_RULES)
from .ingestion import runner
from .pipeline import build_dataset

SERIES_META = {   # id -> label, unit, kind, block, default-visible
    "hacid.spot": ("H-Acid market price (China)", "CNY/t", "observed", "PRICE", True),
    "hacid.quote": ("H-Acid producer / ex-works quotes", "CNY/t", "observed", "PRICE", False),
    "dye.reactive": ("Reactive dye (Baiinfo)", "CNY/t", "observed", "DOWNSTREAM", False),
    "dye.reactive_black_sci99": ("Reactive black (SCI99)", "CNY/t", "observed", "DOWNSTREAM", False),
    "feed.naphthalene_refined": ("Refined naphthalene", "CNY/t", "observed", "COST", False),
    "feed.naphthalene_industrial": ("Industrial naphthalene", "CNY/t", "observed", "COST", False),
    "feed.sulfuric_acid": ("Sulfuric acid 98%", "CNY/t", "observed", "COST", False),
    "feed.nitric_acid": ("Nitric acid 98%", "CNY/t", "observed", "COST", False),
    "feed.caustic_soda": ("Caustic soda 32%", "CNY/t", "observed", "COST", False),
    "feed.coke": ("Metallurgical coke (context)", "CNY/t", "observed", "COST", False),
    "export.hacid.qty": ("China exports HS 292221 - quantity", "t", "observed", "TRADE", False),
    "export.hacid.value": ("China exports HS 292221 - value", "USD", "observed", "TRADE", False),
    "mirror.ind.hacid.qty": ("India imports from China HS 292221 - quantity", "t", "observed", "TRADE", False),
    "mirror.kor.hacid.qty": ("Korea imports from China HS 292221 - quantity", "t", "observed", "TRADE", False),
    "mirror.idn.hacid.qty": ("Indonesia imports from China HS 292221 - quantity", "t", "observed", "TRADE", False),
    "derived.cost_idx": ("Feedstock price index (equal-weight, chain-linked)", "index", "derived", "COST", False),
    "derived.export_uv": ("Import unit value, mirror (HS 292221)", "USD/t", "derived", "TRADE", False),
    "derived.export_uv_china": ("Export unit value, China-reported (HS 292221)", "USD/t", "derived", "TRADE", False),
    "derived.supply_index": ("Available share of known capacity", "ratio", "estimated", "SUPPLY", False),
    "derived.eff_supply": ("Available known capacity", "t/yr", "estimated", "SUPPLY", False),
    "derived.event_pressure": ("Residual event pressure", "index", "derived", "EVENTS", False),
}


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (o is None or math.isnan(o) or math.isinf(o)) else round(float(o), 6)
    if isinstance(o, (pd.Timestamp,)):
        return None if pd.isna(o) else str(o.date())
    if o is pd.NaT:
        return None
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def _write(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_clean(obj), ensure_ascii=False, separators=(",", ":")) + "\n")


def _d(x):
    return None if x is None or pd.isna(x) else str(pd.Timestamp(x).date())


# ---------------------------------------------------------------- pieces
def observed_master(obs, s):
    """Observation-date master (no carry-forward) for charts: real points only."""
    m = series_mod.build_master(obs, s, "economic")
    return m


def changes(m: pd.DataFrame, asof: pd.Timestamp):
    """Price changes over 1D/5D/20D/60D/1Y using REAL observations only. A change is reported only if
    an observation exists within a tolerance of the comparison date - otherwise null (no gap-filling)."""
    v = m["value"].dropna()
    if v.empty:
        return {}
    last_d = v.index[-1]
    out = {}
    for lab, days, tol in (("1D", 1, 4), ("5D", 7, 4), ("20D", 28, 7), ("60D", 84, 14), ("1Y", 365, 31)):
        target = last_d - pd.Timedelta(days=days)
        prev = v[(v.index <= target) & (v.index >= target - pd.Timedelta(days=tol))]
        out[lab] = None if prev.empty else {"pct": float(v.iloc[-1] / prev.iloc[-1] - 1),
                                           "from_date": str(prev.index[-1].date()), "from_value": float(prev.iloc[-1])}
    return out


def freshness(status: dict, registry: pd.DataFrame, obs: pd.DataFrame, now: pd.Timestamp):
    rows = []
    for _, r in registry.iterrows():
        sid = r["source_id"]
        st = status.get(sid, {})
        o = obs[obs["source"] == sid]
        last_obs = st.get("last_observation_date") or (_d(o["obs_date"].max()) if len(o) else None)
        freq = str(r.get("frequency") or "")
        key = "daily" if "daily" in freq else "10-day" if "10-day" in freq else "monthly" if "monthly" in freq else "irregular"
        age = None if not last_obs else int((now - pd.Timestamp(last_obs)).days)
        stale = age is not None and age > FRESHNESS_DAYS[key]
        state = st.get("status") or ("curated" if r.get("collector") == "curated" else
                                    "unavailable" if r.get("status") in ("unavailable", "excluded", "not implemented") else "never run")
        if state in ("ok", "partial") and stale:
            state = "stale"
        rows.append({"source_id": sid, "name": r["source_name"], "family": r["source_family"], "tier": int(r["tier"]),
                     "series": r["series"], "frequency": freq, "url": r["url"], "coverage": r["historical_coverage"],
                     "reliability": r["reliability"], "registry_status": r["status"], "access": r["access_method"],
                     "notes": r["notes"], "collector_status": state, "last_attempt": st.get("last_attempt"),
                     "last_success": st.get("last_success"), "failure_reason": st.get("failure_reason"),
                     "last_observation_date": last_obs, "age_days": age, "rows": int(len(o)),
                     "vintage": o["vintage_status"].value_counts().to_dict() if len(o) else {}})
    return rows


def forensic(inf, sens, obs_dates, events_econ, blocks_econ, bt_row, cls_row, infls_before, blocks_pit):
    sens_row = sens.loc[inf.trigger] if inf.trigger in sens.index else None
    if sens_row is not None and isinstance(sens_row, pd.DataFrame):
        sens_row = sens_row.iloc[0]
    if sens_row is not None:
        sens_row = sens_row.drop(labels=["spread_days"], errors="ignore")
    ow = signals.onset_window(inf, sens_row, obs_dates)
    fo = signals.fundamental_onset(inf, events_econ, blocks_econ)
    det = None if bt_row is None or pd.isna(bt_row.get("score_alert")) else pd.Timestamp(bt_row["score_alert"])
    evaluable = bool(bt_row is not None and bt_row.get("scored_history_available"))
    lead = None if det is None else int((inf.trigger - det).days)
    an = signals.analogue(blocks_pit.loc[:inf.start].iloc[-1] if len(blocks_pit.loc[:inf.start]) else
                          pd.Series(dtype=float), blocks_pit, infls_before, inf.start) if len(blocks_pit) else \
        {"label": "No strong historical analogue", "id": None, "similarity": None, "candidates": 0}
    lo, hi = inf.start - pd.Timedelta(days=120), inf.end + pd.Timedelta(days=30)
    tl = events_econ[(events_econ["event_date"] >= lo) & (events_econ["event_date"] <= hi)] if len(events_econ) else events_econ
    timeline = [{"date": _d(e["event_date"]), "precision": e.get("event_date_precision") or "day",
                 "public_date": _d(e.get("announce_date")), "type": e["event_type"], "company": e.get("company") or "",
                 "direction": int(e["direction"]), "url": e.get("url"), "kind": "event"} for _, e in tl.iterrows()]
    timeline += [{"date": ow["best"], "type": "price_onset", "kind": "estimated",
                  "label": f"Price regime onset (window {ow['earliest']} → {ow['latest']})"},
                 {"date": _d(inf.trigger), "type": "price_trigger", "kind": "derived",
                  "label": f"Price rule fired ({inf.rule})"},
                 {"date": _d(inf.end), "type": "move_end", "kind": "derived", "label": "Move peak/trough"}]
    if det is not None:
        timeline.append({"date": _d(det), "type": "system_detection", "kind": "derived",
                         "label": "System alert (point-in-time score ≥ threshold)"})
    timeline.sort(key=lambda x: x["date"] or "")
    conf_pts = (ow["confidence"] != "Low") + bool(cls_row is not None and cls_row.get("evidence")) + \
        (fo.get("basis") == "event")
    return {"id": inf.id, "direction": inf.direction, "magnitude": inf.magnitude, "shape": inf.shape, "rule": inf.rule,
            "z": inf.z, "start_price": inf.start_price, "end_price": inf.end_price,
            "price_onset": ow, "price_trigger": _d(inf.trigger), "end": _d(inf.end),
            "fundamental_onset": fo,
            "system_detection": {"date": _d(det), "evaluable": evaluable,
                                 "text": (_d(det) if det is not None else
                                          "Not detected" if evaluable else
                                          "Not evaluable - insufficient point-in-time history")},
            "detection_lead_days": lead,
            "driver": {"label": cls_row.get("label") if cls_row is not None else "?",
                       "type": cls_row.get("type") if cls_row is not None else "Unclassified",
                       "amplifiers": [classify.LABELS[a] for a in (cls_row.get("amplifiers") or "")] if cls_row is not None else [],
                       "evidence": [x for x in (cls_row.get("evidence") or "").split(" | ") if x] if cls_row is not None else [],
                       "kind": "inferred"},
            "historical_outcome": cls_row.get("historical_outcome") if cls_row is not None else None,
            "analogue": an, "confidence": "High" if conf_pts == 3 else "Medium" if conf_pts == 2 else "Low",
            "timeline": timeline}


# ---------------------------------------------------------------- main
def build_site_data(db_path=DB_PATH, data_dir=DATA_DIR, out_dir=SITE_DATA_DIR, now=None, rebuild=True) -> dict:
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None)
    if rebuild:
        store.rebuild(db_path, data_dir)
    obs, ev, cap = db.load_observations(db_path), db.load_events(db_path), db.load_capacity(db_path)
    econ = build_dataset(db_path, "economic")
    pit = build_dataset(db_path, "information", index_end=now.normalize())
    P = econ.panel
    infls = econ.infls

    # ---- scoring on the information axis (point-in-time)
    comps = score.components(pit.panel)
    W = score.vintage_weights(pit.panel, comps)
    scored = score.compute_score(pit.panel, W, comps)
    blocks_pit = scored[[c for c in scored if c.startswith("block.")]].rename(columns=lambda c: c[6:])
    comps_e = score.components(P)
    blocks_econ = signals.block_frame(comps_e)

    # ---- quality
    q = quality.data_quality(obs, P, cap, ev, end=now.normalize())
    # ---- live state
    valid = scored["score"].dropna()
    ts = valid.index[-1] if len(valid) else None
    master = observed_master(obs, TARGET)
    last_price = master["value"].dropna()
    status = runner.read_status(data_dir)
    registry = pd.read_csv(data_dir / "metadata" / "sources.csv")
    fresh = freshness(status, registry, obs, now)
    tgt_obs = obs[obs["series"] == TARGET].sort_values(["obs_date", "tier"])
    last_row = tgt_obs[tgt_obs["obs_date"] == tgt_obs["obs_date"].max()].iloc[0] if len(tgt_obs) else None
    if ts is not None:
        it = signals.interpret(scored.loc[ts], blocks_pit.loc[ts], q.attrs["overall_score"])
        evc = signals.event_context(ev[ev["known_date"].notna()], pit.panel.get("derived.event_pressure", pd.Series(dtype=float)), ts)
        an = signals.analogue(blocks_pit.loc[ts], blocks_pit, infls, ts)
        row = scored.loc[ts]
        # detection age: how long the state has been >= DEVELOPING continuously
        hot = scored.loc[:ts, "score"].fillna(0) >= ALERT_THRESHOLD
        since = None
        if hot.iloc[-1]:
            off = hot[::-1].idxmin() if (~hot).any() else hot.index[0]
            since = _d(off)
        live = {"as_of": _d(ts), "score": float(row["score"]), "pressure": float(row["pressure"]),
                "coverage": float(row["coverage"]), "status": row["status"], **it,
                "events": evc, "analogue": an, "detected_since": since}
    else:
        live = {"as_of": None, "score": None, "state": "NO DATA", "icon": "⚪",
                "sentence": "Not enough point-in-time history to score yet.", "blocks": {}, "confirmation": {},
                "events": signals.event_context(ev, pd.Series(dtype=float), now), "analogue": None}

    infl_frame = inflections.to_frame(infls)
    sens = inflections.start_sensitivity(P[TARGET]) if len(infls) else pd.DataFrame()
    cls = classify.classify_all(infls, P, econ.events) if len(infls) else pd.DataFrame()
    bt, bt_sum, fa = backtest.detection_backtest(infls, pit.panel, scored, ALERT_THRESHOLD) if len(infls) else \
        (pd.DataFrame(), {}, pd.DataFrame())
    obs_dates = pd.DatetimeIndex(sorted(tgt_obs["obs_date"].unique()))
    forensics = []
    for k, i in enumerate(infls):
        bt_row = bt.set_index("inflection").loc[i.id].to_dict() if len(bt) else None
        cls_row = cls.set_index("inflection").loc[i.id].to_dict() if len(cls) else None
        forensics.append(forensic(i, sens, obs_dates, econ.events, blocks_econ, bt_row, cls_row,
                                  infls[:k], blocks_pit))

    hits = leadlag.inflection_hit_rates(P, infls) if len(infls) else pd.DataFrame()
    if len(hits):
        hits["sample_label"] = hits["n_inflections"].map(signals.sample_label)
    ll = leadlag.lead_lag_table(P)

    summary = {
        "chemical": {"id": CHEMICAL_ID, "name": "H-Acid", "market": "China"},
        "generated_at": now.strftime("%Y-%m-%d %H:%M") + " CST",
        "price": None if last_row is None else {
            "value": float(last_price.iloc[-1]), "date": _d(last_price.index[-1]), "unit": "CNY/t",
            "kind": "observed", "source_family": last_row["source_family"], "url": last_row["url"],
            "n_families": int(master["n_families"].iloc[-1]), "lo": float(master["lo"].iloc[-1]), "hi": float(master["hi"].iloc[-1]),
            "age_days": int((now - last_price.index[-1]).days)},
        "changes": changes(master, now),
        "live": live,
        "quality": {"overall": q.attrs["overall_score"], "groups": q.reset_index().to_dict("records"),
                    **{k: v for k, v in q.attrs.items() if k != "overall_score"}},
        "freshness": [{k: f[k] for k in ("source_id", "name", "collector_status", "last_observation_date", "age_days", "frequency")}
                      for f in fresh if f["rows"] or f["collector_status"] not in ("unavailable",)],
        "n_inflections": len(infls), "sample_label": signals.sample_label(len(infls)),
        "config": {"bands": [{"upper": b[0], "state": b[1]} for b in BANDS], "blocks": BLOCKS,
                   "block_weights": BLOCK_WEIGHTS, "alert_threshold": ALERT_THRESHOLD,
                   "move_rules": [f"{w}d ≥ {t:.0%}" for w, t in MOVE_RULES]},
    }

    # ---- series for charts: real observation points (no carry-forward) + derived series
    chart = {}
    for sid, (label, unit, kind, block, vis) in SERIES_META.items():
        if sid.startswith("derived."):
            if sid not in P:
                continue
            s = P[sid].dropna()
            if sid != "derived.event_pressure":
                s = s[s.ne(s.shift())]                      # change points only (step series)
            pts = [[_d(d), float(v)] for d, v in s.items()]
            fams = []
        else:
            if not (obs["series"] == sid).any():
                continue
            m = observed_master(obs, sid)
            pts = [[_d(d), float(v)] for d, v in m["value"].items()]
            fams = sorted(obs.loc[obs["series"] == sid, "source_family"].dropna().unique().tolist())
        if pts:
            chart[sid] = {"label": label, "unit": unit, "kind": kind, "block": block, "default": vis,
                          "families": fams, "points": pts}
    # per-source points of the target (to show independent families)
    by_src = {}
    for fam, g in tgt_obs.groupby("source_family"):
        by_src[fam] = [{"d": _d(r.obs_date), "v": float(r.value), "pub": _d(r.pub_date), "vintage": r.vintage_status,
                        "kind": r.value_kind, "url": r.url, "src": r.source, "via": r.republisher if isinstance(r.republisher, str) else None,
                        "text": r.raw_text if isinstance(r.raw_text, str) else None, "precision": r.date_precision}
                       for r in g.itertuples()]
    score_hist = [{"d": _d(d), "score": float(r.score), "state": r.state, "status": r.status, "coverage": float(r.coverage)}
                  for d, r in scored.dropna(subset=["score"]).iterrows()]

    events_out = [{"event_date": _d(e["event_date"]), "precision": e.get("event_date_precision"),
                   "announce_date": _d(e.get("announce_date")), "vintage": e.get("vintage_status"),
                   "type": e["event_type"], "company": e.get("company") or "", "plant": e.get("plant") or "",
                   "location": e.get("location") or "", "capacity_t": None if pd.isna(e.get("capacity_t")) else float(e["capacity_t"]),
                   "direction": int(e["direction"]), "severity": int(e.get("severity") or 1),
                   "source": e.get("source"), "family": e.get("source_family"), "url": e.get("url"),
                   "kind": e.get("value_kind") or "observed", "confidence": e.get("confidence"),
                   "note": e.get("note"), "raw_text": e.get("raw_text")} for _, e in ev.sort_values("event_date").iterrows()]

    producers = pd.read_csv(data_dir / "metadata" / "producers.csv")
    supply = {"producers": producers.where(producers.notna(), None).to_dict("records"),
              "capacity_timeline": [{**{k: (None if (isinstance(v, float) and math.isnan(v)) else v) for k, v in r.items()},
                                     "eff_date": _d(r["eff_date"]), "published_at": _d(r["published_at"]),
                                     "known_date": _d(r["known_date"])} for r in cap.sort_values(["producer", "eff_date"]).to_dict("records")],
              "known_nominal_t": float(producers["nominal_capacity_t"].fillna(0).sum()),
              "note": ("Utilisation is not published for any producer. 'Available capacity' = nominal × availability, "
                       "where availability for trial/reduced/disrupted status is a documented assumption (0.5) - ESTIMATED, not observed.")}

    stats = {"inflections": infl_frame.to_dict("records") if len(infl_frame) else [],
             "n_inflections": len(infls), "sample_label": signals.sample_label(len(infls)),
             "hit_rates": hits.to_dict("records") if len(hits) else [],
             "lead_lag": ({"variables": ll.index.tolist(), "lags": [int(c) for c in ll.columns],
                           "corr": ll.round(3).where(ll.notna(), None).values.tolist()} if len(ll) else None),
             "backtest_summary": bt_sum, "backtest": bt.to_dict("records") if len(bt) else [],
             "false_alarms": fa.to_dict("records") if len(fa) else []}

    dest_p = data_dir / "observations" / "comtrade_destinations.csv"
    dests = pd.read_csv(dest_p, dtype={"period": str}).to_dict("records") if dest_p.exists() else []

    base = out_dir / CHEMICAL_ID
    _write(base / "summary.json", summary)
    _write(base / "series.json", {"series": chart, "by_family": by_src, "score": score_hist,
                                  "inflections": [{"id": f["id"], "direction": f["direction"], "start": f["price_onset"]["best"],
                                                   "trigger": f["price_trigger"], "end": f["end"], "magnitude": f["magnitude"]}
                                                  for f in forensics]})
    _write(base / "inflections.json", forensics)
    _write(base / "events.json", events_out)
    _write(base / "supply.json", supply)
    _write(base / "stats.json", stats)
    _write(base / "trade_destinations.json", dests)
    _write(out_dir / "sources.json", fresh)
    _write(out_dir / "meta.json", {"generated_at": summary["generated_at"],
                                   "chemicals": [{"id": CHEMICAL_ID, "name": "H-Acid", "market": "China", "active": True,
                                                  "score": live.get("score"), "state": live.get("state")}]})
    return {"summary": summary, "n_inflections": len(infls), "scored_rows": int(scored["score"].notna().sum())}
