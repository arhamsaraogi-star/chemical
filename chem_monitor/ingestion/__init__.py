"""Data acquisition: collectors, curated datasets, safe runner."""
from .baiinfo import BaiinfoCollector, BaiinfoWaybackCollector
from .comtrade import ComtradeCollector
from .nbs import NBSCollector
from .ecb import ECBFXCollector


def live_collectors():
    """Run by the scheduled workflow (twice per weekday)."""
    return [BaiinfoCollector(), NBSCollector(), ComtradeCollector(), ECBFXCollector()]


def backfill_collectors():
    """Run on demand (workflow_dispatch backfill=true): full history where the source allows it."""
    return [NBSCollector(), ComtradeCollector(), ECBFXCollector()] + wayback_collectors()


def wayback_collectors(every_days=3):
    """One archive collector per Baiinfo page so they can run in parallel (GitHub Actions matrix)."""
    from .baiinfo import PAGES
    return [BaiinfoWaybackCollector(pages=[p], every_days=every_days, name="baiinfo_wayback_" + p.series.replace(".", "_"))
            for p in PAGES]


REGISTRY = live_collectors
