"""Generic Internet Archive collector for H-Acid prices published on any website.

For each target (a URL, or a URL prefix covering many article pages) every archived capture is fetched
from the Internet Archive's public copy and scanned for sentences / table rows that mention H-Acid
with a price and a date. Rules:
  * a price is kept only with an explicit date in the same sentence/row, or the page's own date line
  * pub_date = page publication date if printed, else the archive capture date (a verified "public by"
    date); a price dated after its capture is rejected
  * the source FAMILY is the original publisher named in the sentence (百川盈孚 -> baiinfo, 卓创 -> sci99,
    生意社 -> 100ppi, 隆众 -> oilchem); otherwise the website itself. Republications never count twice.
  * ranges -> midpoint (labelled); 万元/吨 and 元/公斤 converted to CNY/t; plausibility 5k-500k CNY/t
"""
import re
from dataclasses import dataclass
import pandas as pd
from bs4 import BeautifulSoup
from .base import Collector, http_get

CDX = "https://web.archive.org/cdx/search/cdx"


@dataclass(frozen=True)
class Target:
    name: str            # collector / file name suffix
    url: str             # URL or prefix (without scheme)
    family: str          # default family if no publisher is named
    match: str = "exact"  # exact | prefix
    limit: int = 400


# Discovered by probing the archive (scripts in docs/data-sources.md). Prefix targets cover article pages.
TARGETS = [
    Target("baiinfo_hacid_news", "www.baiinfo.com/news/17971/", "baiinfo", "prefix", 300),
    Target("baiinfo_hacid_quotes", "www.baiinfo.com/news/20822/", "baiinfo", "prefix", 300),
    Target("baiinfo_dye_intermediates", "www.baiinfo.com/ranliao/ranliaozhongjianti", "baiinfo"),
    Target("baiinfo_cn_dye_intermediates", "www.baiinfo.com.cn/meihuagong/ranliaozhongjianti", "baiinfo"),
    Target("sunsirs_hacid", "www.sunsirs.com/uk/prodetail-1389.html", "100ppi"),
    Target("chemicalbook_hacid", "www.chemicalbook.com/ProductPriceInfo_CB4396468.htm", "chemicalbook"),
]

PUBLISHERS = [("百川盈孚", "baiinfo"), ("百川", "baiinfo"), ("卓创", "sci99"), ("生意社", "100ppi"),
              ("隆众", "oilchem"), ("金联创", "jlc"), ("SunSirs", "100ppi"), ("Baiinfo", "baiinfo")]
NUM = r"(\d+(?:,\d{3})*(?:\.\d+)?)"
PRICE_RE = re.compile(NUM + r"(?:\s*[-–—~至]\s*" + NUM + r")?\s*(万元/吨|元/吨|元/公斤|元/千克|yuan/ton|yuan/mt|RMB/ton)", re.I)
DATE_FULL = re.compile(r"(20\d\d)[年\-/.](\d{1,2})[月\-/.](\d{1,2})日?")
DATE_MD = re.compile(r"(?<!\d)(\d{1,2})月(\d{1,2})日")
KEYWORDS = ("H酸", "H-acid", "H Acid", "H-Acid", "H acid")
OTHER_PRODUCT = re.compile(r"染料|活性黑|萘|硫酸|硝酸|液碱|烧碱|对位酯|还原物|分散|J酸|γ酸|K酸|2-萘酚")


def _to_t(v, unit):
    u = unit.lower()
    if "万元" in unit:
        return v * 10000
    if "公斤" in unit or "千克" in unit:
        return v * 1000
    return v


def page_date(text):
    m = DATE_FULL.search(text[:3000])
    return pd.Timestamp(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def extract(html: str, capture: pd.Timestamp, url: str, default_family: str, max_age_days=400):
    """-> list of observation dicts found in one archived page."""
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style"]):
        t.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    pdate = page_date(text)
    if pdate is not None and pdate > capture.normalize() + pd.Timedelta(days=1):
        pdate = None
    units = [re.sub(r"\s+", " ", tr.get_text(" ", strip=True)) for tr in soup.find_all("tr")]
    units += re.split(r"(?<=[。；!?！？])|(?<=\. )", text)
    out, seen = [], set()
    for s in units:
        if not any(k in s for k in KEYWORDS) or len(s) > 600:
            continue
        # the price must belong to H-Acid: it follows a keyword within 40 chars, with no other product between
        pm = None
        for km in re.finditer("|".join(re.escape(k) for k in KEYWORDS), s):
            window = s[km.end(): km.end() + 40]
            cand = PRICE_RE.search(window)
            if cand and not OTHER_PRODUCT.search(window[:cand.start()]):
                pm = cand
                break
        if not pm:
            continue
        a = float(pm.group(1).replace(",", ""))
        b = float(pm.group(2).replace(",", "")) if pm.group(2) else None
        v = _to_t((a + b) / 2 if b else a, pm.group(3))
        if not 5_000 <= v <= 500_000:
            continue
        # the date that governs the price = the last date written before the price in the same sentence
        head = s[: s.find(pm.group(0)) if pm.group(0) in s else len(s)]
        fulls = [(m.start(), pd.Timestamp(int(m.group(1)), int(m.group(2)), int(m.group(3)))) for m in DATE_FULL.finditer(head)]
        mds = []
        for m in DATE_MD.finditer(head):
            d = pd.Timestamp(capture.year, int(m.group(1)), int(m.group(2)))
            if d > capture + pd.Timedelta(days=2):
                d = d.replace(year=capture.year - 1)
            mds.append((m.start(), d))
        dates = sorted(fulls + mds)
        if dates:
            obs = dates[-1][1]
        elif pdate is not None and any(w in s for w in ("今日", "当前", "目前", "截至")):
            obs = pdate
        else:
            continue                                  # no date we can defend -> skip
        pub = pdate if pdate is not None and pdate >= obs else capture.normalize()
        if obs > capture.normalize() or (capture - obs).days > max_age_days:
            continue
        fam = next((f for k, f in PUBLISHERS if k in s), default_family)
        # "出厂参考" = a market reference (spot series); a company's "出厂价/出厂报价" = producer quote
        series = "hacid.quote" if re.search(r"出厂价|出厂报价", s) and "出厂参考" not in s else "hacid.spot"
        key = (obs, series, round(v))
        if key in seen:
            continue
        seen.add(key)
        out.append({"obs_date": obs, "pub_date": pub, "vintage_status": "confirmed", "value": v, "series": series,
                    "source_family": fam, "location": "China", "currency": "CNY", "unit": "t",
                    "price_type": "range_midpoint" if b else ("ex_works" if series == "hacid.quote" else "market"),
                    "market": "domestic", "quote_kind": "archived_text", "value_kind": "observed",
                    "confidence": 0.7 if b else 0.8, "date_precision": "day", "republisher": "Internet Archive",
                    "url": url, "raw_text": f"[capture {capture:%Y-%m-%d}] " + s[max(0, s.find(pm.group(0)) - 80): s.find(pm.group(0)) + 60].strip()})
    return out


class ArchiveCollector(Collector):
    tier = 3

    def __init__(self, target: Target, delay=1.0):
        self.t, self.delay = target, delay
        self.name = "archive_" + target.name

    def captures(self):
        q = (f"{CDX}?url={self.t.url}&matchType={self.t.match}&output=json&from=2023&fl=timestamp,original"
             f"&filter=statuscode:200&filter=mimetype:text/html&collapse={'urlkey' if self.t.match == 'prefix' else 'digest'}"
             f"&limit={self.t.limit * 3}")
        js = http_get(q, timeout=120, delay=self.delay).json()
        rows = [tuple(r[:2]) for r in js[1:]]
        print(f"[archive] {self.t.url} ({self.t.match}): {len(rows)} captures", flush=True)
        return rows[-self.t.limit:]

    def fetch(self, mode="backfill"):
        rows, errors, pages_hit = [], [], 0
        for ts, orig in self.captures():
            cap = pd.Timestamp(ts[:8])
            try:
                html = http_get(f"https://web.archive.org/web/{ts}id_/{orig}", timeout=60, delay=self.delay).text
            except Exception as e:                     # noqa: BLE001
                errors.append(f"{ts}: {e}")
                continue
            found = extract(html, cap, f"https://web.archive.org/web/{ts}/{orig}", self.t.family)
            pages_hit += bool(found)
            rows += found
        print(f"[archive] {self.t.name}: {len(rows)} prices from {pages_hit} pages", flush=True)
        df = pd.DataFrame(rows)
        df.attrs["errors"] = errors[:20]
        if df.empty:
            raise RuntimeError("no dated H-Acid prices found in archived captures" + (f" ({errors[0]})" if errors else ""))
        df["source"], df["tier"] = "archive_web", self.tier
        return df.drop_duplicates(["obs_date", "series", "value"])


def archive_collectors():
    return [ArchiveCollector(t) for t in TARGETS]
