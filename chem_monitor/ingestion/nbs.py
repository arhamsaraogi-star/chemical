"""National Bureau of Statistics: 10-day prices of important means of production in circulation
(流通领域重要生产资料市场价格变动情况). Official, public, timestamped on the page -> confirmed vintage.

Used series:  feed.sulfuric_acid (硫酸 98%), feed.caustic_soda (烧碱 液碱 32%), feed.coke (焦炭, context only).
obs_date = last day of the 10-day period (上旬 10th, 中旬 20th, 下旬 month end).
"""
import re
import pandas as pd
from bs4 import BeautifulSoup
from .base import Collector, http_get

LIST = "https://www.stats.gov.cn/sj/zxfb/"
TITLE_RE = re.compile(r"(20\d\d)年(\d{1,2})月(上|中|下)旬流通领域重要生产资料市场价格变动情况")
PRODUCTS = {  # row label prefix -> (series, grade)
    "硫酸": ("feed.sulfuric_acid", "98%"),
    "烧碱": ("feed.caustic_soda", "liquid 32%"),
    "焦炭": ("feed.coke", "quasi-grade-1 metallurgical"),
}


def period_end(y, m, part):
    if part == "上":
        return pd.Timestamp(y, m, 10)
    if part == "中":
        return pd.Timestamp(y, m, 20)
    return pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)


def list_releases(max_pages=80, since="2023-09-01", delay=1.5):
    """Walk the release index (index.html, index_1.html, ...) until releases are older than `since`."""
    out, since = [], pd.Timestamp(since)
    for k in range(max_pages):
        url = LIST + ("index.html" if k == 0 else f"index_{k}.html")
        html = http_get(url, delay=delay).text
        s = BeautifulSoup(html, "lxml")
        oldest = None
        for a in s.find_all("a", href=True):
            m = TITLE_RE.search(a.get_text(strip=True))
            if not m:
                continue
            end = period_end(int(m.group(1)), int(m.group(2)), m.group(3))
            href = a["href"]
            full = href if href.startswith("http") else LIST + href.lstrip("./")
            out.append((end, full))
            oldest = end if oldest is None else min(oldest, end)
        if oldest is not None and oldest < since:
            break
    seen, uniq = set(), []
    for end, u in sorted(out):
        if end not in seen and end >= since:
            seen.add(end)
            uniq.append((end, u))
    return uniq


def parse_release(html: str, period: pd.Timestamp, url: str):
    s = BeautifulSoup(html, "lxml")
    text = s.get_text(" ", strip=True)
    m = re.search(r"(20\d\d)/(\d\d)/(\d\d) (\d\d:\d\d)", text)
    if m:
        pub, vintage = pd.Timestamp(f"{m.group(1)}-{m.group(2)}-{m.group(3)}"), "confirmed"
    else:                                   # fall back to the release folder date in the URL
        mu = re.search(r"/t(20\d{6})_", url)
        pub, vintage = (pd.Timestamp(mu.group(1)), "estimated") if mu else (pd.NaT, "unknown")
    rows = []
    for tr in s.find_all("tr"):
        cells = [re.sub(r"\s+", "", c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
        if len(cells) < 3:
            continue
        for key, (series, grade) in PRODUCTS.items():
            if cells[0].startswith(key):
                try:
                    v = float(cells[2])
                except ValueError:
                    continue
                rows.append({"obs_date": period, "pub_date": pub, "vintage_status": vintage, "series": series,
                             "value": v, "grade": grade, "unit": "t", "currency": "CNY", "location": "China",
                             "price_type": "market", "market": "domestic", "quote_kind": "survey",
                             "url": url, "raw_text": " | ".join(cells[:5]), "confidence": 1.0,
                             "value_kind": "observed", "date_precision": "10-day"})
    uniq = {}
    for r in rows:                          # the page repeats the table (print + screen layout)
        uniq.setdefault(r["series"], r)
    return list(uniq.values())


class NBSCollector(Collector):
    name, tier = "nbs_10day", 1

    def __init__(self, since="2023-09-01", delay=1.5):
        self.since, self.delay = since, delay

    def fetch(self, mode="live"):
        since = self.since if mode == "backfill" else (pd.Timestamp.today() - pd.Timedelta(days=75)).strftime("%Y-%m-%d")
        rels = list_releases(max_pages=80 if mode == "backfill" else 2, since=since, delay=self.delay)
        rows, errors = [], []
        for end, url in rels:
            try:
                rows += parse_release(http_get(url, delay=self.delay).text, end, url)
            except Exception as e:                 # noqa: BLE001
                errors.append(f"{url}: {e}")
        df = pd.DataFrame(rows)
        df.attrs["errors"] = errors
        if df.empty:
            raise RuntimeError("no NBS release parsed" + (": " + errors[0] if errors else ""))
        df["source"], df["source_family"], df["tier"] = self.name, "nbs", self.tier
        return df
