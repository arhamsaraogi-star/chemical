"""Data acquisition: collectors, curated datasets, safe runner."""
from .baiinfo import BaiinfoCollector, BaiinfoWaybackCollector
from .comtrade import ComtradeCollector
from .nbs import NBSCollector


def live_collectors():
    """Run by the scheduled workflow (twice per weekday)."""
    return [BaiinfoCollector(), NBSCollector(), ComtradeCollector()]


def backfill_collectors():
    """Run on demand (workflow_dispatch backfill=true): full history where the source allows it."""
    return [NBSCollector(), ComtradeCollector(), BaiinfoWaybackCollector()]


REGISTRY = live_collectors
