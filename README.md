# Chemical Cycle Monitor

**An open, point-in-time research monitor for Chinese chemical price cycles. H-Acid first.**

🌐 **Live site:** https://arhamsaraogi-star.github.io/chemical/ (after Pages is enabled; see *Deploying*)

> *What is happening to H-Acid prices in China, why is it happening, and is a genuine
> chemical-cycle inflection developing?*

The monitor collects public price, feedstock, trade and plant-event data, reconstructs what an
analyst could have known on each date, detects price inflections, explains them, and publishes a
static website that refreshes automatically. Every number on the site links back to its source.

*Beautiful on the surface. Transparent underneath. Quantitative at the core. No black box.*

---

## Why H-Acid?

H-Acid (1-amino-8-naphthol-3,6-disulfonic acid, CAS 90-20-0) is the key coupling component of
reactive dyes, which colour most of the world's cotton. Production needs hazardous sulfonation and
nitration steps and is concentrated in a handful of Chinese plants, so accidents, environmental
inspections and safety rules move the price violently. In 2026 the Baiinfo market average rose
from about ¥40,000/t (February) to ¥150,000/t (30 September). That makes it a good laboratory for
separating price moves from fundamental regime changes.

## How it works

```
GitHub Actions (weekdays 10:37 & 18:37 China time)
  collect ─▶ validate ─▶ merge into CSV store ─▶ tests ─▶ analytics ─▶ site/data/*.json ─▶ commit ─▶ GitHub Pages
```

* **Data store:** plain CSV files in `data/`, versioned by git. The SQLite database is rebuilt from
  them on every run and is never committed.
* **Two clocks:** every record has an *economic* date (when it happened) and an *information* date
  (when it was published). Forensics use the first; the live score, alerts and backtests use only
  the second, so there is no look-ahead (tested).
* **Signal blocks:** ten indicators are grouped into eight blocks (price, supply, demand, cost,
  inventory, downstream, trade, events). Correlated indicators share one vote. The 0–100 score maps
  to NORMAL / WATCH / DEVELOPING / STRONG / MAJOR, and the text is generated from that state, so it
  can never contradict the number.
* **Forensics:** for each inflection the monitor estimates the fundamental onset, when it became
  public, the price onset (as a window), the price trigger, the system's point-in-time detection
  and lead, the driver and amplifiers, and the closest earlier analogue (if strong enough).
* **No AI in the core:** prices, scores, statistics and backtests are deterministic.

Full detail: [`docs/SPECIFICATION.md`](docs/SPECIFICATION.md) · [`docs/methodology.md`](docs/methodology.md)
· [`docs/architecture.md`](docs/architecture.md).

## Data sources

| Source | What | How | Vintage |
|---|---|---|---|
| Baiinfo (百川盈孚) public pages | H-Acid market average; naphthalene, nitric acid, caustic soda; reactive dye | daily public note (members-only content is not collected) | confirmed |
| Baiinfo / SCI99 figures cited in news & broker notes | historical H-Acid prices, producer quotes | curated with URL + original sentence | confirmed (article date) |
| Internet Archive snapshots of Baiinfo pages | historical daily notes | Wayback CDX (backfill) | confirmed |
| National Bureau of Statistics | sulfuric acid 98%, caustic soda 32% (10-day) | public releases | confirmed |
| UN Comtrade (HS 292221) | China exports (to Dec 2024); India/Korea/Indonesia imports from China (mirror) | public API | estimated (labelled lag) |
| News (Xinhua, CLS, …) | accidents, shutdowns, policy, capacity | curated | confirmed |

Not used: SunSirs/100ppi (JavaScript anti-bot challenge), ChemicalBook (blocks automated clients),
modelled "price index" reports (unsourced). See [`docs/data-sources.md`](docs/data-sources.md) and
`data/metadata/sources.csv`.

## Run locally

```bash
pip install -r requirements.txt
python -m pytest -q tests                      # 45+ tests, offline
python -m chem_monitor.cli build               # rebuild DB from data/ and write site/data/*.json
python -m http.server -d site 8000             # open http://localhost:8000
```

Other commands:

```bash
python -m chem_monitor.cli collect             # live collectors (network)
python -m chem_monitor.cli collect --backfill  # NBS + Comtrade + Internet Archive history (slow, polite)
python -m chem_monitor.cli quality             # text data-quality report
python -m chem_monitor.cli forensics           # CSV outputs in out/ (+ forensics.png with matplotlib)
python -m chem_monitor.cli daily               # collect + score + text alert
python -m chem_monitor.cli demo                # synthetic end-to-end check (fake data, never published)
```

## Automated updates

* `.github/workflows/update-data.yml` runs twice each weekday and on demand (tick **backfill** for
  history). A source that fails keeps its previous data. Its status, last success and failure
  reason appear on the site's *Data quality* page.
* `.github/workflows/tests.yml` runs the test suite on every push.
* `.github/workflows/deploy.yml` publishes `site/` to GitHub Pages after tests pass.

### Deploying (one-time)
1. Merge to `main` (scheduled workflows only run on the default branch).
2. Settings → Pages → *Build and deployment* → Source: **GitHub Actions**.
3. Actions → *update-data* → *Run workflow* (tick *backfill* the first time).

## Add a source

1. Add a row to `data/metadata/sources.csv` (family, tier, access method, robots/terms check).
2. Write a collector in `chem_monitor/ingestion/` returning rows in the observation schema, with a
   publication date only if the source provides one (or an explicit, labelled lag). Then
   `vintage_status` = `estimated`.
3. Register it in `chem_monitor/ingestion/__init__.py` and add a parser test with a small fixture.

Curated items (a price cited in an article, a plant accident) go in `data/curated/*.csv` with the
URL and the original sentence.

## Add a chemical

Add an entry to `data/metadata/chemicals.json`, collectors writing `<chemical>.spot` style series
with `chemical_id`, and a producers/events file. The site already reads `site/data/meta.json`
for the list of chemicals. No other chemical is populated until H-Acid is validated.

## Limitations

* Before live collection began (Oct 2026) the H-Acid series consists of cited data points
  (2024–2026). It is sparse, so onset windows are wide, and gaps longer than ~2 months are left blank.
* There is no public inventory or utilisation data. The inventory block is empty, and capacity
  availability is partly an estimate (labelled as such).
* HS 292221 contains other naphthalene sulfonic acids, and China's own monthly Comtrade data ends in
  Dec 2024.
* With few historical inflections, every hit rate and lead time is *exploratory*.

## Disclaimer

For research and education only; not investment advice. Third-party data belongs to its
publishers and is cited for research; verify against the original before relying on it.

## License

Code: MIT (see `LICENSE`). Data: see the licence note in `LICENSE`.
