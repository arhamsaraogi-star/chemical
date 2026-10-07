# Data sources

The machine-readable registry is `data/metadata/sources.csv` (one row per source, including
rejected ones). Collector run status is in `data/status/source_status.json`.

| source | family | tier | collected how | status |
|---|---|---|---|---|
| Baiinfo (百川盈孚) public product pages | baiinfo | 2 | `ingestion/baiinfo.py`: parses only the public dated note ("百川盈孚提示") on six pages: H-Acid, refined and industrial naphthalene, nitric acid, caustic soda, reactive dye | active, daily |
| Baiinfo via Internet Archive | baiinfo | 2 | `BaiinfoWaybackCollector`: Wayback CDX snapshots since Sep 2023 | backfill (GitHub Actions) |
| Baiinfo / SCI99 cited in news & broker notes | baiinfo, sci99 | 2 | `data/curated/hacid_price_points.csv`: each row has the URL and the verbatim sentence | curated |
| National Bureau of Statistics 10-day prices | nbs | 1 | `ingestion/nbs.py`: sulfuric acid 98%, liquid caustic 32%, metallurgical coke | active |
| UN Comtrade public API, HS 292221 | un_comtrade | 1 | `ingestion/comtrade.py`: China exports (data ends Dec 2024) and imports from China reported by India, Korea and Indonesia | active, monthly |
| News (Xinhua/Jiemian, CLS, 21st Century, Sina, Tencent, ifeng, BHI) | news | 3 | `data/curated/events.csv`, `capacity.csv`, `metadata/producers.csv` | curated |

## Rejected or unavailable

* **SunSirs / 生意社 (100ppi.com):** serves a JavaScript anti-bot challenge (`HW_CHECK` cookie).
  Solving it programmatically would circumvent an access control, so it is not collected.
* **ChemicalBook:** returns HTTP 403 to automated clients. Its listings are supplier asking prices anyway.
* **Baiinfo members area** (article bodies, price database, producer notes): login required, not collected.
* **Modelled price reports** (IMARC, ChemAnalyst, etc.): unsourced quarterly numbers; tier 5, zero weight.
* **China Customs online query:** protected by a captcha; not automated. Mirror data is used instead.

## Rules for every collector

* Honest User-Agent (`chem-cycle-monitor/0.2 (+repo URL)`), robots.txt checked, polite delays
  of 1.5–2 s, retries with back-off.
* Publication dates come only from the source, or from an explicit, labelled lag (`estimated`).
* A failure never overwrites stored data (`ingestion/runner.py`).
