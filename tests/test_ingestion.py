"""Collectors and the safe runner: parsing, validation, failure handling, no data destruction."""
import json
from pathlib import Path
import pandas as pd
import pytest
from chem_monitor.ingestion import runner
from chem_monitor.ingestion.baiinfo import PAGES, parse_note
from chem_monitor.ingestion.nbs import parse_release, period_end
from chem_monitor.ingestion.base import Collector

FX = Path(__file__).parent / "fixtures"
PAGE = {p.series: p for p in PAGES}


def fx(name):
    return (FX / name).read_text(encoding="utf-8")


def test_baiinfo_parses_market_average():
    r = parse_note(fx("baiinfo_hacid.html"), PAGE["hacid.spot"], pd.Timestamp("2026-10-07"))
    assert r["obs_date"] == pd.Timestamp("2026-09-30") and r["value"] == 150000 and r["price_type"] == "market_average"


def test_baiinfo_reference_price_lower_confidence():
    r = parse_note(fx("baiinfo_gongyenai.html"), PAGE["feed.naphthalene_industrial"], pd.Timestamp("2026-10-07"))
    assert r["value"] == 6000 and r["price_type"] == "ex_works_reference" and r["confidence"] < 1


def test_baiinfo_kg_converted_to_tonne():
    r = parse_note(fx("baiinfo_dye.html"), PAGE["dye.reactive"], pd.Timestamp("2026-10-07"))
    assert r["value"] == 47000


def test_baiinfo_year_rollover():
    """A 31 Dec note seen on 3 Jan belongs to the previous year - never to a future date."""
    r = parse_note(fx("baiinfo_dec.html"), PAGE["hacid.spot"], pd.Timestamp("2027-01-03"))
    assert r["obs_date"] == pd.Timestamp("2026-12-31")


def test_baiinfo_implausible_value_rejected():
    assert parse_note(fx("baiinfo_bad.html"), PAGE["hacid.spot"], pd.Timestamp("2026-10-07")) is None


def test_baiinfo_wrong_product_not_parsed():
    assert parse_note(fx("baiinfo_dye.html"), PAGE["hacid.spot"], pd.Timestamp("2026-10-07")) is None


def test_nbs_release_parsing_and_dedup():
    rows = parse_release(fx("nbs_release.html"), period_end(2026, 9, "中"), "https://www.stats.gov.cn/x/t20260923_1.html")
    got = {r["series"]: r for r in rows}
    assert len(rows) == 3
    assert got["feed.sulfuric_acid"]["value"] == 1777.3 and got["feed.caustic_soda"]["value"] == 682.6
    assert got["feed.sulfuric_acid"]["pub_date"] == pd.Timestamp("2026-09-24")
    assert got["feed.sulfuric_acid"]["vintage_status"] == "confirmed"
    assert period_end(2026, 2, "下") == pd.Timestamp("2026-02-28")


class Fake(Collector):
    name, tier = "fake", 2

    def __init__(self, df=None, exc=None):
        self.df, self.exc = df, exc

    def fetch(self, mode="live"):
        if self.exc:
            raise self.exc
        return self.df.copy()


def _rows(dates, vals, **kw):
    d = pd.DataFrame({"obs_date": pd.to_datetime(dates), "value": vals, "series": "hacid.spot", "location": "China"})
    d["pub_date"] = d["obs_date"]
    for k, v in kw.items():
        d[k] = v
    return d


def test_failed_collector_keeps_existing_data(tmp_path):
    st = runner.run_collector(Fake(_rows(["2026-09-01", "2026-09-02"], [100.0, 101.0])), data_dir=tmp_path, now="2026-10-01")
    assert st["status"] == "ok"
    before = (tmp_path / "observations" / "fake.csv").read_text()
    st = runner.run_collector(Fake(exc=ConnectionError("site down")), data_dir=tmp_path)
    assert st["status"] == "failed" and "site down" in st["failure_reason"]
    assert (tmp_path / "observations" / "fake.csv").read_text() == before
    status = json.loads((tmp_path / "status" / "source_status.json").read_text())["fake"]
    assert status["last_success"] and status["last_observation_date"] == "2026-09-02"


def test_merge_never_deletes_and_counts_revisions(tmp_path):
    runner.run_collector(Fake(_rows(["2026-09-01", "2026-09-02"], [100.0, 101.0])), data_dir=tmp_path, now="2026-10-01")
    st = runner.run_collector(Fake(_rows(["2026-09-02", "2026-09-03"], [102.0, 103.0])), data_dir=tmp_path, now="2026-10-01")
    df = runner.read_store("fake", tmp_path)
    assert list(df["value"]) == [100.0, 102.0, 103.0] and st["rows_revised"] == 1 and st["rows_new"] == 1


def test_validation_rejects_bad_rows(tmp_path):
    existing = _rows(["2026-09-01"], [100.0], source="fake")
    bad = pd.concat([
        _rows(["2026-09-02"], [-5.0]),                                 # non-positive
        _rows(["2030-01-01"], [100.0]),                                # future
        _rows(["2026-09-03"], [1000.0]),                               # >3x jump
        _rows(["2026-09-04"], [101.0]).assign(pub_date=pd.Timestamp("2026-08-01")),   # published before obs
        _rows(["2026-09-05"], [101.0]).assign(series="weird.series"),
        _rows(["2026-09-06"], [102.0]),                                # good
    ])
    good, reasons = runner.validate(bad, existing, now="2026-10-01")
    assert list(good["value"]) == [102.0]
    assert len(reasons) == 5


def test_all_invalid_is_a_failure_not_an_overwrite(tmp_path):
    runner.run_collector(Fake(_rows(["2026-09-01"], [100.0])), data_dir=tmp_path, now="2026-10-01")
    st = runner.run_collector(Fake(_rows(["2026-09-02"], [-1.0])), data_dir=tmp_path, now="2026-10-01")
    assert st["status"] == "failed"
    assert len(runner.read_store("fake", tmp_path)) == 1
