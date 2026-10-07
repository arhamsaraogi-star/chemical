"""python -m chem_monitor.cli <command>"""
import argparse
import pandas as pd
from . import db, pipeline
from .ingestion.base import CSVCollector
from .config import DB_PATH, OUT_DIR, DATA_DIR, SITE_DATA_DIR


def main(argv=None):
    ap = argparse.ArgumentParser(prog="chem_monitor")
    ap.add_argument("--db", default=str(DB_PATH))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    o = sub.add_parser("import-obs", help="load a price/indicator CSV into observations")
    o.add_argument("csv"); o.add_argument("--source", required=True); o.add_argument("--tier", type=int, required=True)
    o.add_argument("--series", help="constant series name if the file has no 'series' column")
    o.add_argument("--date-col", default="obs_date"); o.add_argument("--value-col", default="value")
    o.add_argument("--pub-col", help="file column holding the publication date (-> confirmed vintage)")
    o.add_argument("--pub-lag-days", type=int, default=None, help="assumed publication lag (-> estimated vintage)")
    o.add_argument("--assume-known-on-obs-date", action="store_true", help="optimistic; warns")
    o.add_argument("--currency", default="CNY"); o.add_argument("--unit", default="t")
    e = sub.add_parser("import-events"); e.add_argument("csv")
    c = sub.add_parser("import-capacity"); c.add_argument("csv")
    sub.add_parser("forensics", help="phases 1-3: inflections, causes, leading indicators")
    d = sub.add_parser("daily", help="phases 4-6: ingest, score, alert")
    d.add_argument("--webhook"); d.add_argument("--threshold", type=float, default=50)
    sub.add_parser("quality", help="data-quality report (coverage, point-in-time, source families)")
    sub.add_parser("demo", help="run everything on synthetic data")
    co = sub.add_parser("collect", help="run collectors safely into data/observations (+ status file)")
    co.add_argument("--backfill", action="store_true", help="full history where the source allows it")
    co.add_argument("--source", action="append", help="only these source ids (repeatable)")
    b = sub.add_parser("build", help="rebuild the DB from the CSV store and write site/data/*.json")
    b.add_argument("--out", default=str(SITE_DATA_DIR))
    sub.add_parser("rebuild-db", help="rebuild the SQLite DB from the CSV store")
    a = ap.parse_args(argv)

    if a.cmd == "init":
        db.init_db(a.db)
    elif a.cmd == "import-obs":
        cols = {a.date_col: "obs_date", a.value_col: "value"}
        if a.pub_col:
            cols[a.pub_col] = "pub_date"
        defaults = {"currency": a.currency, "unit": a.unit}
        if a.series:
            defaults["series"] = a.series
        n = db.upsert_observations(CSVCollector(a.csv, a.source, a.tier, cols, defaults, pub_lag_days=a.pub_lag_days,
                                          assume_known_on_obs_date=a.assume_known_on_obs_date).fetch(), a.db)
        print(f"{n} rows imported")
        obs = db.load_observations(a.db)
        print(obs[obs.source == a.source]["vintage_status"].value_counts().to_string())
        if (obs[obs.source == a.source]["vintage_status"] == "unknown").any():
            print("NOTE: 'unknown' vintage rows are used for research but EXCLUDED from as-of scoring/backtests.")
    elif a.cmd == "import-events":
        print(db.upsert_events(pd.read_csv(a.csv), a.db), "events imported")
    elif a.cmd == "import-capacity":
        print(db.upsert_capacity(pd.read_csv(a.csv), a.db), "capacity rows imported")
    elif a.cmd == "forensics":
        r = pipeline.run_forensics(a.db)
        print(r["inflections"].to_string(index=False))
        print(r["classification"].to_string(index=False))
        print(f"\nresults written to {OUT_DIR}/")
        if (OUT_DIR / "forensics.png").exists():
            pass
    elif a.cmd == "daily":
        pipeline.run_daily(a.db, webhook=a.webhook, alert_threshold=a.threshold)
    elif a.cmd == "quality":
        from . import quality
        ds = pipeline.build_dataset(a.db)
        print(quality.render(quality.data_quality(db.load_observations(a.db), ds.panel,
                                                  db.load_capacity(a.db), db.load_events(a.db))))
    elif a.cmd == "demo":
        from .demo import run_demo
        run_demo()
    elif a.cmd == "collect":
        from .ingestion import runner, live_collectors, backfill_collectors
        cs = backfill_collectors() if a.backfill else live_collectors()
        if a.source:
            cs = [c for c in cs if c.name in a.source]
        st = runner.run_all(cs, "backfill" if a.backfill else "live", DATA_DIR)
        if cs and all(v["status"] == "failed" for v in st.values()):
            print("[collect] every collector failed - previous data kept")
    elif a.cmd == "rebuild-db":
        from . import store
        print(store.rebuild(a.db, DATA_DIR))
    elif a.cmd == "build":
        from . import report
        r = report.build_site_data(a.db, DATA_DIR, a.out)
        live = r["summary"]["live"]
        print(f"[build] price {r['summary']['price']} | state {live.get('state')} score {live.get('score')} | "
              f"{r['n_inflections']} inflections | {r['scored_rows']} scored days")


if __name__ == "__main__":
    main()
