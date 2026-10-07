"""Collector base classes.

Collectors return DataFrames in the observation schema (see db.OBS_COLS) and never write anything
themselves - ingestion.runner validates and merges. Rules every collector follows:
  * honest User-Agent, robots.txt respected, polite delays, no login / paywall / anti-bot circumvention
  * a publication date is only ever taken from the source (or an explicit, labelled lag assumption)
"""
from abc import ABC, abstractmethod
import time
import warnings
from typing import Callable
import pandas as pd

USER_AGENT = "chem-cycle-monitor/0.2 (+https://github.com/arhamsaraogi-star/chemical; research)"


def http_get(url, timeout=40, retries=4, delay=1.0, session=None, **kw):
    """GET with an identifying User-Agent and exponential back-off on connection errors / 5xx / 429."""
    import requests
    s = session or requests
    last = None
    for k in range(retries):
        try:
            r = s.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            if r.encoding in (None, "ISO-8859-1"):
                r.encoding = r.apparent_encoding
            time.sleep(delay)
            return r
        except Exception as e:                     # noqa: BLE001 - retried, then re-raised
            last = e
            time.sleep(delay * 2 ** k)
    raise last


class Collector(ABC):
    name: str = "base"          # == source_id in data/metadata/sources.csv and the CSV file name
    tier: int = 2
    kind: str = "observations"

    @abstractmethod
    def fetch(self, mode: str = "live") -> pd.DataFrame:
        """Return observations with at least: obs_date, series, value (+ any provenance fields).
        mode: 'live' (latest data only) or 'backfill' (history, where the source allows it)."""

    def _finish(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["source"] = df.get("source", self.name)
        df["tier"] = df.get("tier", self.tier)
        return df


class CSVCollector(Collector):
    """Load an exported CSV/Excel file. `columns` maps file headers -> schema names; `defaults` fills
    constant fields (series, unit, currency, price_type, market ...).

    VINTAGE (when could an analyst have known each row?):
      * file has a publication-date column (map it to 'pub_date')  -> 'confirmed'
      * else pub_lag_days=N given                                  -> 'estimated' (obs_date + N days)
      * else assume_known_on_obs_date=True (warns, optimistic)     -> 'estimated'
      * else                                                       -> 'unknown' (excluded from as-of work)
    """

    def __init__(self, path, name, tier, columns=None, defaults=None, date_format=None,
                 pub_lag_days=None, assume_known_on_obs_date=False):
        self.path, self.name, self.tier = path, name, tier
        self.columns, self.defaults, self.date_format = columns or {}, defaults or {}, date_format
        self.pub_lag_days, self.assume_obs = pub_lag_days, assume_known_on_obs_date

    def fetch(self, mode="live"):
        df = pd.read_excel(self.path) if str(self.path).endswith((".xls", ".xlsx")) else pd.read_csv(self.path)
        df = df.rename(columns=self.columns)
        df["obs_date"] = pd.to_datetime(df["obs_date"], format=self.date_format)
        for k, v in self.defaults.items():
            if k not in df:
                df[k] = v
        df["pub_date"] = pd.to_datetime(df["pub_date"]) if "pub_date" in df else pd.NaT
        df["vintage_status"] = df["pub_date"].notna().map({True: "confirmed", False: "unknown"})
        miss = df["pub_date"].isna()
        if miss.any() and self.pub_lag_days is not None:
            df.loc[miss, "pub_date"] = df.loc[miss, "obs_date"] + pd.Timedelta(days=self.pub_lag_days)
            df.loc[miss, "vintage_status"] = "estimated"
        elif miss.any() and self.assume_obs:
            warnings.warn(f"{self.name}: assuming {int(miss.sum())} rows were public on their observation "
                          "date; as-of results will be optimistic", stacklevel=2)
            df.loc[miss, "pub_date"] = df.loc[miss, "obs_date"]
            df.loc[miss, "vintage_status"] = "estimated"
        raw = df.drop(columns=["raw_text", "pub_date", "vintage_status"], errors="ignore")
        df["raw_text"] = raw.astype(object).where(raw.notna(), "").astype(str).agg("|".join, axis=1)
        return self._finish(df)


class HttpCollector(Collector):
    """Generic web collector; you supply `parse(text) -> DataFrame` (one parse function per site).

    mode='live'    : rows dated within `live_window_days` of today are first-seen NOW -> pub_date=today,
                     'confirmed'. Older rows on the same page (an archive table) are kept for research
                     but get NO publication date ('unknown'): we cannot claim we knew them then.
    mode='archive' : pub_date comes from parse() if the site provides one ('confirmed'); otherwise
                     'unknown'. Nothing is ever stamped with today's date.
    """

    def __init__(self, url, name, tier, parse: Callable[[str], pd.DataFrame], mode="live",
                 live_window_days=5, headers=None, timeout=30):
        assert mode in ("live", "archive")
        self.url, self.name, self.tier, self.parse, self.mode = url, name, tier, parse, mode
        self.live_window_days = live_window_days
        self.timeout = timeout

    def fetch(self, mode="live"):
        r = http_get(self.url, timeout=self.timeout)
        df = self.parse(r.text)
        df["obs_date"] = pd.to_datetime(df["obs_date"])
        df["url"] = self.url
        df["pub_date"] = pd.to_datetime(df["pub_date"]) if "pub_date" in df else pd.NaT
        if self.mode == "live":
            today = pd.Timestamp.today().normalize()
            fresh = df["obs_date"] >= today - pd.Timedelta(days=self.live_window_days)
            df.loc[fresh & df["pub_date"].isna(), "pub_date"] = today
        df["vintage_status"] = df["pub_date"].notna().map({True: "confirmed", False: "unknown"})
        return self._finish(df)

