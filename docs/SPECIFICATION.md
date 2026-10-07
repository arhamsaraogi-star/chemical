# Chemical Cycle Monitor — Specification

Version 0.2 · H-Acid reference implementation · status: implemented unless marked **[planned]**

This document is the contract for the system: what it must do, the data model, the rules every
number obeys, the interfaces between components, and how each requirement is verified. Section
numbers in brackets (e.g. *[R-PIT-3]*) are referenced by tests and code comments.

---

## 1. Purpose and scope

The product answers, for one chemical at a time:

> *What is happening to the price in China, why is it happening, and is a genuine chemical-cycle
> inflection developing?*

It separates four things that are usually blurred: **price move**, **fundamental regime change**,
**system detection** and **market confirmation**, and for each historical inflection reports when
the fundamental change began, when it became public, when price moved, when the system detected it,
what caused it, what confirmed it, and whether it resembles an earlier episode.

In scope (v0.2): H-Acid (CAS 90-20-0), China market. Out of scope: other chemicals (the schema is
ready; no data is populated), user accounts, trading signals, opaque ML prediction.

## 2. Principles (non-negotiable)

| ID | Principle |
|---|---|
| P1 | **Point-in-time.** No historical signal may use information that was not public at that date. |
| P2 | **No fabrication.** No invented prices, publication dates, inventories or capacity. Unknown stays unknown. |
| P3 | **Five kinds of number** — `observed`, `derived`, `estimated`, `inferred`, `ai_extracted` — are stored and displayed distinctly. |
| P4 | **Deterministic core.** Prices, scores, statistics and backtests use no AI/ML. AI may only assist text extraction, always with source, URL, date and raw evidence retained. |
| P5 | **Provenance.** Every observation and event carries source, source family, URL and the original text where legally permissible. |
| P6 | **Independence is by family, not by website.** Republications of one original count once. |
| P7 | **Honest uncertainty.** Windows instead of false precision; sample sizes on every statistic; weak analogues suppressed. |
| P8 | **Lawful collection.** robots.txt respected, identifying User-Agent, polite rate, no login/paywall/anti-bot circumvention. |
| P9 | **Failure never destroys data.** A failed source keeps its previous data and is shown as failed/stale. |

## 3. Architecture

```
GitHub repository
├── chem_monitor/          Python package (collection, analytics, export)
├── data/                  CSV store = source of truth (git-versioned)
│   ├── observations/      one CSV per collector (append/update only)
│   ├── curated/           cited price points, events, capacity timeline
│   ├── metadata/          sources.csv (registry), producers.csv, chemicals.json
│   └── status/            source_status.json (last attempt/success/failure per source)
├── site/                  static website (HTML/CSS/JS) + site/data/*.json (generated)
└── .github/workflows/     tests.yml · update-data.yml (scheduled) · deploy.yml (Pages)
```

Flow (update-data.yml, 10:37 and 18:37 China time on weekdays):
`collect → validate → merge into CSV store → tests → rebuild SQLite from CSVs → analytics →
site JSON → commit if changed → deploy GitHub Pages`. No server; the site is static.

## 4. Data model

### 4.1 Observation (`db.OBS_COLS`)
| field | meaning |
|---|---|
| `obs_date` | economic date the value refers to |
| `pub_date` | information date (when publicly available); may be null |
| `vintage_status` | `confirmed` (source-dated) · `estimated` (explicit labelled lag) · `unknown` |
| `source`, `source_family`, `tier` | collector/source id; independence group; 1 (official) … 5 (discovery, zero weight) |
| `series` | namespaced id: `hacid.spot`, `hacid.quote`, `feed.*`, `dye.*`, `export.*`, `mirror.<iso>.*`, `ind.*` |
| `value`, `currency`, `unit` | number in CNY/t for prices (kg quotes converted) |
| `price_type`, `market`, `quote_kind`, `grade`, `location` | what kind of price this is; never merged across kinds |
| `value_kind` | observed / derived / estimated / inferred / ai_extracted |
| `date_precision` | day / 10-day / month / early-month / mid-month |
| `url`, `republisher`, `raw_text`, `confidence` | provenance |
| `chemical_id` | `hacid` |

Primary key: (`obs_date`, `source`, `series`, `location`).
`known_date = max(obs_date, pub_date)`; NaT when `pub_date` is unknown.

### 4.2 Event
`event_date`, `event_date_precision`, `announce_date`, `vintage_status`, `event_type`
(accident, shutdown, maintenance, environmental, policy, restart, new_capacity, closure), `company`,
`plant`, `location`, `capacity_t`, `direction` (effect on **supply**: −1 cut, +1 add), `severity` 1–3,
`source`, `source_family`, `url`, `value_kind`, `confidence`, `note`, `raw_text`.

### 4.3 Capacity timeline / producer registry
Capacity rows: `producer, eff_date, published_at, location, nominal_t, utilization, availability,
status, value_kind, url, note`. Producer registry (`data/metadata/producers.csv`): company, plant,
location, nominal capacity and its basis, status, status date, source, confidence.
Effective supply = nominal × utilisation × availability **only where those inputs are published**;
otherwise "available capacity" = nominal × availability, with availability for
trial/reduced/disrupted = 0.5 as a documented **estimate** (`config.STATUS_AVAILABILITY`).

### 4.4 Source registry (`data/metadata/sources.csv`)
source_id, name, family, tier, URL, country, language, series, frequency, data_type, product, grade,
location, currency, unit, price_type, historical_coverage, publication_timing, access_method,
collector, robots_checked, reliability, status, notes. Sources that cannot be used lawfully are kept
with status `unavailable` and the reason.

### 4.5 Chemical registry (`data/metadata/chemicals.json`)
id, name, aliases, CAS, HS code, market, country, target series, feedstocks, downstream, active flag.
Adding a chemical = a registry entry + collectors writing the same series namespace under its id.

## 5. Point-in-time rules  *[R-PIT]*

1. *[R-PIT-1]* Economic time and information time are separate fields for every record.
2. *[R-PIT-2]* A publication date is never fabricated and never assumed equal to the observation date.
3. *[R-PIT-3]* `unknown` vintages are usable for economic-axis research but excluded from all
   information-axis work (score, alerts, backtest) by default.
4. *[R-PIT-4]* `estimated` vintages are allowed only with an explicit, documented lag and are shown as estimated.
5. *[R-PIT-5]* Scoring, alerts and the detection backtest use the information axis; a value exists
   from its `known_date`; an event from its announcement date.
6. *[R-PIT-6]* Rebuilding with data cut at T reproduces the full-history score at T exactly
   (`tests/test_point_in_time.py::test_asof_equivalence`).
7. *[R-PIT-7]* Score weights are refit every 60 business days using only matured forward-return labels.

## 6. Analytics

### 6.1 Master series
Weighted median per date over sources (weight = tier weight × confidence, split equally within a
family). Panel: business-day index; observations on non-business days roll to the next business
day; carry-forward limited per series family (`config.FFILL_LIMITS`; H-Acid 45 bdays). Beyond the
limit the value is NaN — no detection inside unobserved gaps.

### 6.2 Inflection detection
Trigger rules: |Δ| ≥ 5% in 5 bdays, ≥10% in 20, ≥20% in 60. Triggers within 20 bdays merge into
an episode. Shape: acceleration (pre-trend same sign ≥2%), regime_change (z ≥ 3), trend_move.

### 6.3 Onsets  *[R-ONSET]*
* **Price onset**: best estimate = last date within 25% of the move from the pre-move extreme.
  Plausible window = union of onsets under bands 10/25/40% and the real observations bracketing the
  best estimate. Spread ≤5 d High, ≤20 d Medium, else Low. Never "exact" unless spread = 0.
* **Fundamental onset**: earliest supporting supply/policy event (economic date, widened by its
  precision) or fundamental block turn (|block| ≥ 0.3) in the 120 days before the price onset;
  reported with its public (announcement) date.
* **System detection**: first information-axis date in [onset − 60 d, end] with score ≥ 50,
  matching direction, alert-grade coverage. **Detection lead** = price trigger − system detection.

### 6.4 Signal blocks and score  *[R-SCORE]*
Components (expanding percentile → [−1, +1], no look-ahead) are grouped into blocks:

| block | components | weight |
|---|---|---|
| PRICE | momentum (10d), acceleration (5d), producer quotes (5d) | 30% |
| SUPPLY | available-capacity share (20d Δ, sign −), utilisation | 20% |
| COST | feedstock index (20d) | 15% |
| INVENTORY | inventory (20d, sign −) | 10% |
| DOWNSTREAM | reactive dye price (20d) | 10% |
| DEMAND | — (no reliable series yet) | 5% |
| TRADE | mirror import unit value (21d) | 5% |
| EVENTS | decayed event pressure | 5% |

Block value = weighted mean of its components (within-block weights from §5.7).
Pressure = Σ block weight × block value / Σ weight of blocks with data. Score = |pressure| × 100.
Coverage = share of configured block weight with data; < 70% ⇒ `insufficient_evidence`.

### 6.5 State and text  *[R-STATE]*
State is a pure function of score: 0–24 NORMAL · 25–49 WATCH · 50–69 DEVELOPING INFLECTION ·
70–84 STRONG INFLECTION · 85–100 MAJOR INFLECTION. Insufficient evidence caps the state at WATCH.
All live text is generated by `signals.interpret()`:
* the headline sentence comes from the state only; a NORMAL state always says
  "No statistically significant price inflection detected";
* the **driver** (strongest confirming non-price block) is reported separately as "current pressure";
* **confirmation** = non-price blocks agreeing with the direction by ≥ 0.2, shown as k / n;
* **evidence confidence** (High/Medium/Low) combines confirmation, coverage and data quality and
  never changes the state.

### 6.6 Events  *[R-EVENT]*
Decayed pressure (half-life 30 d) × severity × (0.5 + capacity share). The UI shows "last known
event" separately from "current residual pressure"; |pressure| < 0.10 ⇒ not active.

### 6.7 Analogues  *[R-ANALOGUE]*
Cosine similarity × 100 of block fingerprints vs the 14 days before each earlier inflection that
ended ≥ 30 days before the evaluation date. ≥80 strong, 65–80 moderate, 50–65 weak, <50 none.
Below 65 the UI shows "No strong historical analogue".

### 6.8 Statistics and sample size  *[R-SAMPLE]*
Lead/lag correlation on a shared weekly grid; hit rate, base rate, lift per indicator and lead.
Every statistic shows N: N < 10 "exploratory only", 10–29 "indicative", ≥ 30 "statistically
meaningful". Granger output is labelled a predictive lead, not causation.

### 6.9 Driver classification
Rule-based labels A Supply, B Demand, C Cost-push, D Policy, E Inventory using only information
at the move's start; amplifiers listed. `historical_outcome` (sustained / false_breakout: >50%
retrace within 30 d) is hindsight-only and never feeds the live score.

### 6.10 Feedstock index
Chain-linked, equal-weighted index of refined naphthalene, sulfuric acid, nitric acid, caustic
soda. Equal weights because no sourced production coefficients exist; documented as a price index,
not a cost model. Physical recipe support (`COST_RECIPE`) exists for when coefficients are sourced.

## 7. Data acquisition

| source | family | series | method | vintage |
|---|---|---|---|---|
| Baiinfo public product pages | baiinfo | hacid.spot, feed.naphthalene_*, feed.nitric_acid, feed.caustic_soda, dye.reactive | public daily note, parsed | confirmed (source-dated note) |
| Baiinfo via Internet Archive | baiinfo | same | Wayback CDX snapshots (GitHub Actions) | confirmed; note dated after capture is rejected |
| Baiinfo / SCI99 cited in news & broker notes | baiinfo, sci99 | hacid.spot, hacid.quote, dye.* | manual curation with URL + sentence | confirmed (article date) |
| NBS 10-day prices | nbs | feed.sulfuric_acid, feed.caustic_soda, feed.coke | public release pages | confirmed (release timestamp) |
| UN Comtrade (HS 292221) | un_comtrade | export.hacid.*, mirror.{ind,kor,idn}.hacid.* | public preview API | estimated (month end + 45/60 d) |
| News (Xinhua, CLS, …) | news | events | manual curation | confirmed (article date) |
| SunSirs/100ppi, ChemicalBook | — | — | **not collected**: anti-bot challenge / 403 | — |

Validation before merge *[R-VALID]*: parseable dates; finite positive values; no future obs/pub
dates; publication not before observation; known series namespace; jump > 3× previous stored
value rejected. Merge is union on the primary key (revisions replace, nothing is deleted).
Status per source: `ok | partial | failed | stale | curated | unavailable`, last attempt, last
success, failure reason, last observation date, row counts, rejected-row reasons.

**[planned]** Chinese-language event extraction (AI-assisted, human-confirmed) feeding
`events.csv` with `value_kind = ai_extracted`; licensed Baiinfo/SunSirs history via manual archival import.

## 8. Data quality  *[R-QUALITY]*
Groups: H-Acid price, producer quotes, feedstocks, capacity, inventory, downstream dyes, exports,
events. Coverage = share of business days in the trailing 365 days with a usable value (events:
share of quarters with ≥1 event). Overall quality = weighted coverage (30/10/15/10/10/10/10/5).
Also: point-in-time share, confirmed/estimated/unknown shares, independent families (overall and
for the price). Quality ≥ 0.7 is one of the three evidence-confidence points.

## 9. Website

Static, hash-routed, no framework, no tracking. Pages: Dashboard, H-Acid detail, History,
Inflection (forensic), Events, Supply, Data quality, Sources, Methodology, About.
* Dashboard: price (observed, with date and age), 1D/5D/20D/60D/1Y changes computed only from real
  observations near the comparison date (else "n/a"), state + score + meter, sentence, current
  pressure, confirmation k/n, evidence confidence, detected-since, data quality; price chart with
  ranges 1M/3M/6M/1Y/3Y/MAX, drag-zoom, inflection bands (click → forensic page), event markers;
  "Why is it moving?" blocks; historical context; quality; source freshness.
* Charts: one y-axis per chart; different units → separate charts or indexed to 100; step lines with
  dashed unobserved gaps; crosshair tooltip listing every visible series with its observation date.
* Every epistemic kind is shown with a pill (observed/derived/estimated/inferred/ai-extracted).
* Dark/light mode; mobile-responsive; text inserted with `textContent` only.
* Multi-chemical ready: `site/data/meta.json` lists chemicals; only H-Acid is active.

## 10. Operations
* Schedules: weekdays 02:37 and 10:37 UTC. Manual `workflow_dispatch` with `backfill=true` runs NBS,
  Comtrade and Internet-Archive history.
* Deploy: GitHub Pages via Actions (Settings → Pages → Source: GitHub Actions). Tests must pass first.
* Secrets: none required. Never commit credentials; `.gitignore` excludes `.env`, DBs, outputs.
* Freshness thresholds (calendar days): daily 7, 10-day 25, monthly 100, irregular 120.

## 11. Acceptance criteria → verification

| # | criterion | how verified |
|---|---|---|
| 1 | H-Acid history Oct 2023 → present where obtainable | `data/curated/hacid_price_points.csv` (2024-06 →) + live + archive; gaps shown as gaps |
| 2 | multiple independent families | quality page `price_families`; baiinfo + sci99 for price; nbs, un_comtrade, news |
| 3 | provenance on every observation | schema; detail-page provenance table |
| 4 | unknown vintages identified | `vintage_status`; quality page shares |
| 5 | no future leakage | `test_asof_equivalence`, `test_no_future_leakage_in_master`, `test_event_unknown_before_announcement` |
| 6–7 | inflections + forensic timelines | `inflections.json`, inflection page |
| 8–9 | leading indicators with sample labels | `stats.json` hit rates + `sample_label`; `test_sample_labels` |
| 10 | live scoring | `summary.json.live`; scheduled workflow |
| 11 | data quality visible | quality page |
| 12 | failed collectors keep data | `test_failed_collector_keeps_existing_data`, `test_all_invalid_is_a_failure_not_an_overwrite` |
| 13–14 | Actions update + Pages display | workflows |
| 16 | tests pass | `tests.yml` on every push |
| 18 | no credentials | no secrets used; `.gitignore` |
| 19 | no fake data presented as real | demo data only in `demo.py`/tests; site reads the real store only |
| 20 | no AI in core | code review: no model calls anywhere in `chem_monitor/` |
| — | score/state consistency | `test_state_bands`, `test_normal_state_never_claims_an_inflection`, `test_state_text_consistent_for_all_scores` |
| — | stale events, analogue suppression, lead/lag alignment | `test_stale_event_not_active`, `test_weak_analogue_suppressed_and_future_excluded`, `test_leadlag_alignment` |

## 12. Known limitations (v0.2)
* Pre-2026 H-Acid prices are sparse (cited figures), so early inflections have wide onset windows
  and the score history is short. Live collection densifies the series from Oct 2026.
* No reliable public inventory or utilisation series → INVENTORY block empty; capacity availability partly estimated.
* China's own monthly HS 292221 exports end Dec 2024 on Comtrade; mirror data substitutes.
* HS 292221 is not pure H-Acid.
* Inflection count is small → all statistics exploratory.
