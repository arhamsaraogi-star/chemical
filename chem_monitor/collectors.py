"""Backward-compatible import path. Collectors now live in chem_monitor.ingestion."""
from .ingestion.base import Collector, CSVCollector, HttpCollector, http_get  # noqa: F401
from .ingestion import REGISTRY  # noqa: F401
