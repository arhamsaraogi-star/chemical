"""Point-in-time integrity: the information-axis pipeline has no look-ahead. Rebuilding from scratch
with only data public by date T must reproduce the full-history result at T exactly."""
import warnings
import numpy as np
import pandas as pd
import pytest
from chem_monitor import db, pipeline, score, classify, series
from chem_monitor.demo import synth
from chem_monitor.ingestion.base import CSVCollector


@pytest.fixture(scope="module")
def demo_db(tmp_path_factory):
    p = tmp_path_factory.mktemp("pit") / "demo.db"
    obs, ev, cap = synth()
    db.upsert_observations(obs, p); db.upsert_events(ev, p); db.upsert_capacity(cap, p)
    return p


def test_asof_equivalence(demo_db):
    full = pipeline.build_dataset(demo_db, "information")
    comps_f = score.components(full.panel)
    sc_f = score.compute_score(full.panel, score.vintage_weights(full.panel, comps_f), comps_f)
    for T in ["2025-03-14", "2025-06-27", "2026-02-13"]:
        part = pipeline.build_dataset(demo_db, "information", as_of=T)
        comps_p = score.components(part.panel)
        sc_p = score.compute_score(part.panel, score.vintage_weights(part.panel, comps_p), comps_p)
        a, b = sc_f["pressure"].loc[T], sc_p["pressure"].loc[T]
        assert np.isclose(a, b, atol=1e-9), f"look-ahead at {T}: full={a:.6f} as_of={b:.6f}"


def test_event_unknown_before_announcement(demo_db):
    _, ev, _ = synth()
    e = ev.iloc[0]
    d_event, d_known = pd.Timestamp(e["event_date"]), pd.Timestamp(e["announce_date"])
    before = pipeline.build_dataset(demo_db, "information", as_of=d_known - pd.Timedelta(days=1))
    assert before.events[before.events["event_date"] == d_event].empty, "event visible before announcement"


def test_unknown_vintage_excluded_by_default(tmp_path):
    obs, ev, cap = synth()
    m = obs["series"] == "dye.reactive"
    obs.loc[m, "pub_date"] = None
    obs.loc[m, "vintage_status"] = None
    p2 = tmp_path / "v.db"
    db.upsert_observations(obs, p2); db.upsert_events(ev, p2); db.upsert_capacity(cap, p2)
    assert "dye.reactive" in pipeline.build_dataset(p2, "economic").panel          # research can use it
    info = pipeline.build_dataset(p2, "information")
    assert "dye.reactive" not in info.panel and info.vintage_excluded["observations"] > 0
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        opt = pipeline.build_dataset(p2, "information", vintage_policy="assume_economic")
    assert "dye.reactive" in opt.panel and any("unknown vintage" in str(x.message) for x in w)


def test_collector_never_stamps_today(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("date,price\n2024-01-01,20000\n2024-01-02,20200\n")
    df = CSVCollector(f, "x", 2, {"date": "obs_date", "price": "value"}, {"series": "hacid.spot"}).fetch()
    assert (df["vintage_status"] == "unknown").all() and df["pub_date"].isna().all()
    df = CSVCollector(f, "x", 2, {"date": "obs_date", "price": "value"}, {"series": "hacid.spot"}, pub_lag_days=3).fetch()
    assert (df["vintage_status"] == "estimated").all() and (df["pub_date"] - df["obs_date"]).dt.days.eq(3).all()


def test_estimated_vintage_used_from_its_assumed_date(tmp_path):
    """An estimated vintage is usable point-in-time, but only from the assumed publication date."""
    rows = pd.DataFrame({"obs_date": pd.bdate_range("2025-01-01", periods=30), "value": range(100, 130),
                         "series": "hacid.spot", "source": "s", "tier": 2})
    rows["pub_date"] = rows["obs_date"] + pd.Timedelta(days=10)
    rows["vintage_status"] = "estimated"
    p = tmp_path / "e.db"
    db.upsert_observations(rows, p)
    o = db.load_observations(p)
    assert set(o["vintage_status"]) == {"estimated"}
    m = series.build_master(o, "hacid.spot", "information", as_of="2025-01-20")
    assert m.index.max() <= pd.Timestamp("2025-01-20")
    assert m["value"].max() == 107               # obs <= 10 Jan (8 business days) published by 20 Jan


def test_low_coverage_blocks_alert_grade_score(demo_db):
    panel = pipeline.build_dataset(demo_db, "information").panel[["hacid.spot", "hacid.quote"]]
    sc = score.compute_score(panel)
    assert (sc["status"].dropna() == "insufficient_evidence").all()
    assert not sc["state"].dropna().isin(["MAJOR INFLECTION", "STRONG INFLECTION", "DEVELOPING INFLECTION"]).any()


def test_hindsight_not_in_driver_label(demo_db):
    ds = pipeline.build_dataset(demo_db, "economic")
    c = classify.classify_all(ds.infls, ds.panel, ds.events)
    assert "F" not in set(c["label"]) and "historical_outcome" in c


def test_no_future_leakage_in_master():
    """A value published after the as-of date must not appear, even if its obs_date is earlier."""
    o = pd.DataFrame({"obs_date": pd.to_datetime(["2025-01-02", "2025-01-03"]), "pub_date": pd.to_datetime(["2025-01-02", "2025-02-01"]),
                      "series": "hacid.spot", "source": "a", "source_family": "a", "tier": 2, "value": [1.0, 2.0], "confidence": 1.0})
    o["known_date"] = o[["obs_date", "pub_date"]].max(axis=1)
    m = series.build_master(o, "hacid.spot", "information", as_of="2025-01-15")
    assert list(m["value"]) == [1.0]
