"""Baiinfo (百川盈孚) public product pages.

Each product page shows a short, dated public note ("百川盈孚提示") with the day's market average. Only
that public note is parsed. Article bodies, the price database and producer notes are members-only
and are deliberately NOT collected. robots.txt (checked 2026-10-07) allows these query-free paths.

Two collectors share one parser:
  BaiinfoCollector         live page            -> today's note
  BaiinfoWaybackCollector  Internet Archive     -> historical notes (snapshot = proof of publication)
Both belong to source_family 'baiinfo'; they are never counted as independent of each other.
"""
import re
from dataclasses import dataclass
import pandas as pd
from bs4 import BeautifulSoup
from .base import Collector, http_get


@dataclass(frozen=True)
class Page:
    path: str
    series: str
    keyword: str            # must appear in the note
    unit: str               # unit the note quotes: 't' or 'kg' (converted to CNY/t)
    lo: float               # plausibility range in CNY/t
    hi: float
    grade: str = ""
    location: str = "China"
    old_paths: tuple = ()   # paths used by earlier site versions (for the archive)


PAGES = [
    Page("ranliao/ranliaozhongjianti", "hacid.spot", "H酸", "t", 5_000, 500_000, "industrial",
         old_paths=("meihuagong/ranliaozhongjianti",)),
    Page("meijingxihuagong/jingnai", "feed.naphthalene_refined", "精萘", "t", 2_000, 40_000, "refined"),
    Page("meijiaoyoushenjiagong/gongyenai", "feed.naphthalene_industrial", "工业萘", "t", 1_500, 30_000,
         "industrial"),
    Page("qitawuji/xiaosuan", "feed.nitric_acid", "硝酸", "t", 300, 10_000, "98%"),
    Page("lvjianchanye/yejian", "feed.caustic_soda", "液碱", "t", 150, 4_000, "32% ion-membrane"),
    Page("ranliao/huoxingranliao", "dye.reactive", "活性", "kg", 5_000, 200_000, "reactive black (WNN150%)",
         "Jiangsu-Zhejiang"),
]

DATE_RE = re.compile(r"(?:(20\d\d)年)?(\d{1,2})月(\d{1,2})日")
NUM = r"([\d,]+(?:\.\d+)?)"
AVG_RE = re.compile(r"均价(?:为|参考|约|在)?\s*" + NUM + r"\s*(元/吨|元/公斤|元/千克)")
REF_RE = re.compile(r"(?:出厂参考|参考价|参考)(?:为|至|在)?\s*" + NUM + r"\s*(元/吨|元/公斤|元/千克)")


def page_text(html: str) -> str:
    s = BeautifulSoup(html, "lxml")
    for t in s(["script", "style"]):
        t.decompose()
    return re.sub(r"\s+", " ", s.get_text(" ", strip=True))


def extract_note(text: str) -> str:
    """The public note: text after '百川盈孚提示' (current layout) or the first dated sentence block."""
    i = text.find("百川盈孚提示")
    if i >= 0:
        return text[i + 6: i + 900].lstrip("：: ")
    m = re.search(r"百川盈孚\s*\d{1,2}月\d{1,2}日讯", text)
    return text[m.start(): m.start() + 900] if m else ""


def infer_date(m, ref: pd.Timestamp) -> pd.Timestamp:
    y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
    if y:
        return pd.Timestamp(int(y), mo, d)
    cand = pd.Timestamp(ref.year, mo, d)
    return cand if cand <= ref + pd.Timedelta(days=2) else pd.Timestamp(ref.year - 1, mo, d)


def parse_note(html: str, page: Page, ref: pd.Timestamp):
    """-> dict(obs_date, value, raw_text, price_type, confidence) or None.
    `ref` = when the page was seen (collection time or archive capture time)."""
    note = extract_note(page_text(html))
    if not note or page.keyword not in note:
        return None
    first_sentence = re.split(r"(?<=[。；])", note)[0]
    md = DATE_RE.search(note[:80])
    if not md:
        return None
    obs = infer_date(md, pd.Timestamp(ref).normalize())
    m, price_type, conf = AVG_RE.search(note), "market_average", 1.0
    if not m:
        m, price_type, conf = REF_RE.search(note), "ex_works_reference", 0.7
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    if m.group(2) in ("元/公斤", "元/千克"):
        v *= 1000
    if not (page.lo <= v <= page.hi):
        return None
    sent = next((x for x in re.split(r"(?<=[。；])", note) if m.group(0) in x), first_sentence)
    return {"obs_date": obs, "value": v, "raw_text": sent.strip()[:500], "price_type": price_type,
            "confidence": conf}


def _row(page: Page, parsed: dict, url: str, source: str, republisher=""):
    return {**parsed, "pub_date": parsed["obs_date"], "vintage_status": "confirmed",
            "source": source, "source_family": "baiinfo", "tier": 2, "series": page.series,
            "location": page.location, "grade": page.grade, "currency": "CNY", "unit": "t",
            "market": "domestic", "quote_kind": "reference", "url": url, "value_kind": "observed",
            "date_precision": "day", "republisher": republisher}


class BaiinfoCollector(Collector):
    """Live public notes. The note is dated by Baiinfo itself and published the same working day,
    so pub_date = note date (confirmed). A note dated in the future relative to now is rejected."""
    name, tier = "baiinfo_public", 2
    BASE = "https://www.baiinfo.com/"

    def __init__(self, pages=PAGES, delay=2.0):
        self.pages, self.delay = pages, delay

    def fetch(self, mode="live"):
        rows, errors = [], []
        now = pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None)
        for p in self.pages:
            url = self.BASE + p.path
            try:
                parsed = parse_note(http_get(url, delay=self.delay).text, p, now)
            except Exception as e:                 # noqa: BLE001 - one page must not stop the others
                errors.append(f"{p.series}: {e}")
                continue
            if parsed is None:
                errors.append(f"{p.series}: note not found / unparseable")
                continue
            rows.append(_row(p, parsed, url, self.name))
        df = pd.DataFrame(rows)
        df.attrs["errors"] = errors
        if df.empty:
            raise RuntimeError("no Baiinfo note parsed: " + "; ".join(errors))
        return df


class BaiinfoWaybackCollector(Collector):
    """Historical public notes from Internet Archive snapshots of the same pages.
    pub_date = note date (Baiinfo dates its notes); the capture timestamp is an upper bound and a
    note dated after its capture is rejected. One snapshot per day, digests de-duplicated."""
    name, tier = "baiinfo_wayback", 2
    CDX = "https://web.archive.org/cdx/search/cdx"

    def __init__(self, pages=PAGES, start="20230901", max_per_page=600, delay=1.5):
        self.pages, self.start, self.max_per_page, self.delay = pages, start, max_per_page, delay

    def snapshots(self, path):
        out = []
        for host in ("www.baiinfo.com", "baiinfo.com", "www.baiinfo.com.cn"):
            q = (f"{self.CDX}?url={host}/{path}&output=json&from={self.start}&fl=timestamp,original,digest"
                 "&filter=statuscode:200&collapse=digest")
            try:
                js = http_get(q, timeout=90, delay=self.delay).json()
            except Exception:                      # noqa: BLE001 - archive hiccups are normal
                continue
            out += [tuple(r) for r in js[1:]]
        seen, uniq = set(), []
        for ts, orig, dig in sorted(out):
            if ts[:8] not in seen:
                seen.add(ts[:8])
                uniq.append((ts, orig))
        return uniq[-self.max_per_page:]

    def fetch(self, mode="backfill"):
        rows, errors = [], []
        for p in self.pages:
            for path in (p.path, *p.old_paths):
                for ts, orig in self.snapshots(path):
                    url = f"https://web.archive.org/web/{ts}id_/{orig}"
                    cap = pd.Timestamp(ts[:8]) + pd.Timedelta(hours=int(ts[8:10] or 0) + 8)  # UTC->CST
                    try:
                        parsed = parse_note(http_get(url, timeout=60, delay=self.delay).text, p, cap)
                    except Exception as e:         # noqa: BLE001
                        errors.append(f"{ts} {p.series}: {e}")
                        continue
                    if parsed is None or parsed["obs_date"] > cap.normalize():
                        continue
                    r = _row(p, parsed, f"https://web.archive.org/web/{ts}/{orig}", self.name,
                             "Internet Archive")
                    r["raw_text"] = f"[capture {ts}] " + r["raw_text"]
                    rows.append(r)
        df = pd.DataFrame(rows)
        df.attrs["errors"] = errors[:50]
        if df.empty:
            raise RuntimeError("no archived Baiinfo notes parsed" + (": " + errors[0] if errors else ""))
        return df.drop_duplicates(["obs_date", "series"], keep="first")
