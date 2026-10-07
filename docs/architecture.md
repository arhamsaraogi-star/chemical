# Architecture

```
chem_monitor/
  config.py          every threshold, weight and band (single source of truth)
  db.py              SQLite schema with two clocks; loaders add known_date
  store.py           CSV store (data/) -> SQLite rebuild
  ingestion/         base (http_get, Collector), baiinfo, nbs, comtrade, runner (validate/merge/status)
  series.py          master series (family-deduplicated weighted median), panel, supply, event pressure
  features.py        momentum, feedstock index, margins, export unit value
  inflections.py     detection, live trigger, start sensitivity
  score.py           components, vintage weights, block-based score
  signals.py         state logic, blocks, interpretation, event context, analogues, onsets
  classify.py        driver labels (hindsight-free) + hindsight outcome
  leadlag.py         lead/lag correlation, Granger (optional), hit rates
  event_study.py     T-90..T+90 windows
  backtest.py        point-in-time detection backtest
  quality.py         data-quality report
  report.py          site/data/*.json export
  pipeline.py        dataset builders, forensics (CSV), daily run
  cli.py             python -m chem_monitor.cli <command>
site/                index.html, assets/{style.css, chart.js, app.js}, data/ (generated)
tests/               pytest suite (+ fixtures with short public-note snippets)
```

**Why CSV and not a committed database?** CSV diffs are reviewable in pull requests, merges are
safe, and the database can always be rebuilt deterministically.

**Why a static site?** GitHub Pages hosts it for free, there is no server to maintain, and the
data the site shows is exactly the JSON committed by the last successful workflow run.

**Multi-chemical readiness:** every record carries `chemical_id`; `data/metadata/chemicals.json`
describes chemicals; `site/data/meta.json` lists them; series ids are namespaced. Adding a
chemical adds rows and files, not schema changes.
