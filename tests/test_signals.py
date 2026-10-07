"""Score/state consistency, blocks, event staleness, analogue suppression, small samples, lead/lag."""
import numpy as np
import pandas as pd
import pytest
from chem_monitor import signals, score, leadlag, series, quality, report
from chem_monitor.config import BANDS, BLOCKS
from chem_monitor.inflections import Inflection


def row(score_, pressure=None, status="ok", coverage=0.9):
    return pd.Series({"score": score_, "pressure": pressure if pressure is not None else score_ / 100,
                      "status": status, "coverage": coverage})


def blocks(**kw):
    b = pd.Series({k: np.nan for k in BLOCKS})
    for k, v in kw.items():
        b[k] = v
    return b


@pytest.mark.parametrize("s,expected", [(0, "NORMAL"), (13, "NORMAL"), (24.9, "NORMAL"), (25, "WATCH"), (49.9, "WATCH"),
                                        (50, "DEVELOPING INFLECTION"), (69, "DEVELOPING INFLECTION"), (70, "STRONG INFLECTION"),
                                        (84.9, "STRONG INFLECTION"), (85, "MAJOR INFLECTION"), (100, "MAJOR INFLECTION")])
def test_state_bands(s, expected):
    assert signals.state_for(s)[0] == expected


def test_normal_state_never_claims_an_inflection():
    """Regression: 'score 13 NORMAL' must not be described as a high-confidence supply-driven move."""
    it = signals.interpret(row(13), blocks(PRICE=0.1, SUPPLY=0.9, INVENTORY=0.8, COST=0.7), quality_score=0.95)
    assert it["state"] == "NORMAL"
    assert "No statistically significant price inflection detected" in it["sentence"]
    assert "inflection is" not in it["sentence"].lower()
    assert it["driver"] == "Supply tightening"         # attribution still reported - separately


def test_state_text_consistent_for_all_scores():
    for s in np.linspace(0, 100, 101):
        it = signals.interpret(row(s), blocks(PRICE=0.5, SUPPLY=0.5))
        assert it["state"] == signals.state_for(s)[0]
        assert it["sentence"].startswith(signals.STATE_SENTENCE[it["state"]].split(".")[0])


def test_insufficient_evidence_caps_state():
    it = signals.interpret(row(90, status="insufficient_evidence", coverage=0.3), blocks(PRICE=0.9))
    assert it["state"] == "WATCH" and it["state_capped"]


def test_correlated_price_indicators_count_once():
    """Price momentum + acceleration + quotes all maxed must not outweigh a single block."""
    idx = pd.bdate_range("2025-01-01", periods=3)
    comps = pd.DataFrame({"price_momentum": 1.0, "price_acceleration": 1.0, "producer_quotes": 1.0,
                          "feedstock_cost": -1.0}, index=idx)
    b = signals.block_frame(comps)
    assert b.loc[idx[0], "PRICE"] == 1.0 and b.loc[idx[0], "COST"] == -1.0
    p, cov = signals.block_pressure(b)
    assert p.iloc[0] == pytest.approx((0.30 - 0.15) / 0.45)
    c = signals.confirmation(b.iloc[0], +1)
    assert c["confirming"] == 0 and c["contradicting_blocks"] == ["COST"]


def test_stale_event_not_active():
    idx = pd.bdate_range("2025-01-01", "2025-12-31")
    ev = pd.DataFrame({"event_date": [pd.Timestamp("2025-01-10")], "announce_date": [pd.Timestamp("2025-01-11")],
                       "event_type": ["accident"], "company": ["X"], "direction": [-1], "severity": [3], "capacity_t": [np.nan]})
    ev["known_date"] = ev["announce_date"]
    pr = series.event_pressure(ev, idx, time_axis="information")
    ctx = signals.event_context(ev, pr, "2025-12-31")
    assert ctx["last_event"]["company"] == "X" and not ctx["active"]
    assert signals.event_context(ev, pr, "2025-01-20")["active"]


def _inf(i, start, end, mag=0.3):
    return Inflection(i, "up", pd.Timestamp(start), pd.Timestamp(start), pd.Timestamp(end), 100, 100 * (1 + mag), mag, "r", "trend_move", 3)


def test_weak_analogue_suppressed_and_future_excluded():
    idx = pd.bdate_range("2024-01-01", "2026-01-01")
    b = pd.DataFrame(0.0, index=idx, columns=list(BLOCKS))
    b.loc["2024-02-01":"2024-03-01", "SUPPLY"] = 1.0          # past episode fingerprint: supply
    infls = [_inf("I01", "2024-03-01", "2024-04-01"), _inf("I02", "2025-12-01", "2025-12-30")]
    now = blocks(**{k: 0.0 for k in BLOCKS}); now["COST"] = 1.0
    an = signals.analogue(now.fillna(0), b, infls, "2025-12-31")
    assert an["id"] is None and an["label"] == "No strong historical analogue"
    now2 = now.copy(); now2["COST"] = 0.0; now2["SUPPLY"] = 1.0
    an2 = signals.analogue(now2, b, infls, "2025-12-31")
    assert an2["id"] == "I01" and an2["similarity"] >= 80        # I02 ended too recently to be eligible


@pytest.mark.parametrize("n,label", [(0, "exploratory only"), (4, "exploratory only"), (12, "indicative"), (40, "statistically meaningful")])
def test_sample_labels(n, label):
    assert signals.sample_label(n) == label


def test_onset_window_brackets_sparse_observations():
    inf = _inf("I01", "2025-06-23", "2025-07-04")
    inf.trigger = pd.Timestamp("2025-06-24")
    obs = pd.DatetimeIndex(["2025-06-09", "2025-06-24", "2025-07-04"])
    w = signals.onset_window(inf, pd.Series([pd.Timestamp("2025-06-23")]), obs)
    assert w["earliest"] == "2025-06-09" and w["latest"] == "2025-06-23" and w["spread_days"] == 14 and w["confidence"] == "Medium" and not w["exact"]


def test_leadlag_alignment():
    """X leads Y by two weeks -> the best positive lead found is 14 days."""
    rng = np.random.default_rng(0)
    idx = pd.date_range("2022-01-07", periods=200, freq="W-FRI")
    x = pd.Series(np.cumsum(rng.normal(0, 1, 200)) + 100, idx)
    y = x.shift(2).bfill() + rng.normal(0, 0.05, 200)
    panel = pd.DataFrame({"hacid.spot": y, "feed.x": x}).resample("B").ffill()
    tbl = leadlag.lead_lag_table(panel)
    best = leadlag.best_leads(tbl)
    assert best.loc["feed.x", "best_lead_days"] == 14


def test_changes_require_real_observations():
    m = pd.DataFrame({"value": [100.0, 150.0]}, index=pd.to_datetime(["2025-01-01", "2025-09-01"]))
    ch = report.changes(m, pd.Timestamp("2025-09-02"))
    assert ch["1D"] is None and ch["20D"] is None and ch["1Y"] is None    # no observation near those dates


def test_quality_low_coverage_reported():
    idx = pd.bdate_range("2025-01-01", "2025-12-31")
    panel = pd.DataFrame({"hacid.spot": np.where(np.arange(len(idx)) < 50, 1.0, np.nan)}, index=idx)
    obs = pd.DataFrame({"series": ["hacid.spot"], "source": ["a"], "source_family": ["a"], "vintage_status": ["unknown"]})
    q = quality.data_quality(obs, panel, pd.DataFrame(), pd.DataFrame(), end="2025-12-31")
    assert q.loc["H-Acid price", "coverage"] < 0.25
    assert q.loc["Inventory", "coverage"] == 0 and q.attrs["unknown_share"] == 1.0
    assert q.attrs["overall_score"] < 0.2


def test_freshness_flags_stale_source():
    reg = pd.DataFrame([{"source_id": "s", "source_name": "S", "source_family": "f", "tier": 2, "series": "x", "frequency": "daily",
                         "url": "", "historical_coverage": "", "reliability": "", "status": "active", "access_method": "", "notes": "",
                         "collector": "s"}])
    st = {"s": {"status": "ok", "last_observation_date": "2026-09-01"}}
    obs = pd.DataFrame({"source": [], "obs_date": [], "vintage_status": []})
    f = report.freshness(st, reg, obs, pd.Timestamp("2026-10-07"))
    assert f[0]["collector_status"] == "stale" and f[0]["age_days"] == 36
