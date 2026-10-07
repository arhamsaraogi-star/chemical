"""Central configuration. Everything tunable lives here.

Series naming convention (column names in the daily panel):
  hacid.spot / hacid.quote / hacid.fob      H-Acid price series (kept separate on purpose)
  feed.<name>                               feedstock / input prices
  dye.<name>                                downstream dye prices
  ind.utilization / ind.inventory           industry stats
  export.hacid.value / export.hacid.qty     customs data
  derived.*                                 computed by the pipeline
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "chem_monitor.db"          # rebuilt from the CSV store; never committed
OUT_DIR = ROOT / "out"
SITE_DATA_DIR = ROOT / "site" / "data"
CHEMICAL_ID = "hacid"                           # reference implementation; see data/metadata/chemicals.json

TARGET = "hacid.spot"          # the series whose inflections we study

# ---- data hierarchy (Tier 5 = discovery only, zero weight in the master series)
TIER_WEIGHT = {1: 1.0, 2: 0.8, 3: 0.6, 4: 0.3, 5: 0.0}
MAX_FFILL_DAYS = 10            # default: how long a stale observation may be carried forward (bdays)
# per-prefix staleness limits (bdays). Sparse / low-frequency series may be carried further, but never
# across an unobserved gap longer than this: beyond it the panel is NaN and nothing is detected there.
FFILL_LIMITS = {"hacid.": 45, "dye.": 45, "feed.": 15, "export.": 30, "mirror.": 30, "ind.": 15, "fx.": 5}

# ---- inflection detection
MOVE_RULES = [(5, 0.05), (20, 0.10), (60, 0.20)]   # (window in business days, |return| threshold)
EPISODE_GAP = 20               # triggers closer than this (bdays) belong to one episode
LOOKBACK = 60                  # how far back we search for the true start of a move
START_BAND = 0.25              # "near the extreme" band for the true-start heuristic (see start_sensitivity)

# ---- event study / lead-lag
EVENT_OFFSETS = [-90, -60, -30, -14, -7, 0, 7, 30, 90]   # calendar days
LEAD_DAYS = [7, 14, 30, 60]

# ---- feedstock index. H-Acid route: naphthalene -> sulfonation (sulfuric/oleum) -> nitration (nitric)
# -> reduction -> alkali fusion (caustic soda). No sourced production coefficients are available, so the
# index is EQUAL-weighted and documented as a feedstock price index, not a cost of production.
COST_WEIGHTS = {"feed.naphthalene_refined": 0.25, "feed.sulfuric_acid": 0.25,
                "feed.nitric_acid": 0.25, "feed.caustic_soda": 0.25}
# Optional physical recipe (t of input per t of H-Acid) + other cost/t -> cost in currency/t
COST_RECIPE: dict = {}         # e.g. {"feed.naphthalene": 0.9, ...}
OTHER_COST_PER_T = 0.0

# ---- event typing
SUPPLY_EVENT_TYPES = {"accident", "shutdown", "maintenance"}
POLICY_EVENT_TYPES = {"policy", "environmental"}
EVENT_HALFLIFE_DAYS = 30

# ---- inflection score
# name: (panel column, transform, window, sign)  sign = effect on *upward* price pressure
COMPONENTS = {
    "price_momentum":       ("hacid.spot",           "pct",   10, +1),
    "price_acceleration":   ("hacid.spot",           "accel",  5, +1),
    "producer_quotes":      ("hacid.quote",          "pct",    5, +1),
    "supply_disruption":    ("derived.supply_index", "diff",  20, -1),
    "capacity_utilization": ("ind.utilization",      "diff",  20, -1),
    "inventory":            ("ind.inventory",        "pct",   20, -1),
    "feedstock_cost":       ("derived.cost_idx",     "pct",   20, +1),
    "downstream_dyes":      ("dye.reactive",         "pct",   20, +1),
    "dye_trade":            ("derived.rdye_qty",     "pct",   21, +1),
    "export_data":          ("derived.export_uv",    "pct",   21, +1),
    "events":               ("derived.event_pressure", "level", 0, +1),
}
# Starting weights (from the project brief). fit_weights() re-estimates them from history.
PRIOR_WEIGHTS = {
    "price_momentum": .15, "price_acceleration": .15, "producer_quotes": .10,
    "supply_disruption": .15, "capacity_utilization": .10, "inventory": .10,
    "feedstock_cost": .10, "downstream_dyes": .05, "dye_trade": .05, "export_data": .05, "events": .05,
}
# Series built FROM the target price (circular as "leading indicators") - excluded from lead/lag & hit rates
ENDOGENOUS = {"hacid.spot", "derived.spread_idx", "derived.ratio_idx", "derived.margin_abs", "derived.margin_ratio"}
# Columns where a *rise* is NOT bullish for price (used by lead-lag hit-rates)
PRESSURE_SIGN = {"ind.inventory": -1, "ind.utilization": -1, "derived.eff_supply": -1, "derived.supply_index": -1}

# state bands (score -> state). The text shown with a score is ALWAYS derived from this table.
BANDS = [(25, "NORMAL", "🟢"), (50, "WATCH", "🟡"), (70, "DEVELOPING INFLECTION", "🟠"),
         (85, "STRONG INFLECTION", "🔴"), (101, "MAJOR INFLECTION", "🔴")]

# ---- signal blocks: correlated indicators are averaged WITHIN a block before blocks are combined,
# so price / producer quotes (same move) cannot count as independent confirmations.
BLOCKS = {
    "PRICE":      ["price_momentum", "price_acceleration", "producer_quotes"],
    "SUPPLY":     ["supply_disruption", "capacity_utilization"],
    "DEMAND":     [],                       # textile demand indicators: none reliable yet
    "COST":       ["feedstock_cost"],
    "INVENTORY":  ["inventory"],
    "DOWNSTREAM": ["downstream_dyes", "dye_trade"],
    "TRADE":      ["export_data"],
    "EVENTS":     ["events"],
}
BLOCK_WEIGHTS = {"PRICE": .30, "SUPPLY": .20, "DEMAND": .05, "COST": .15, "INVENTORY": .10,
                 "DOWNSTREAM": .10, "TRADE": .05, "EVENTS": .05}
BLOCK_STRENGTH = [(0.6, "Strong"), (0.3, "Moderate"), (0.1, "Weak"), (0.0, "Neutral")]
CONFIRM_MIN = 0.2              # a non-price block "confirms" when its value agrees with direction by >= this

# ---- residual event pressure: below this an old event no longer counts as "active"
EVENT_ACTIVE_MIN = 0.10

# ---- analogue similarity (cosine x 100)
ANALOGUE_BANDS = [(80, "Strong analogue"), (65, "Moderate analogue"), (50, "Weak analogue")]
ANALOGUE_MIN_SHOW = 65         # weaker analogues are reported as "No strong historical analogue"

# ---- small-sample labelling
SAMPLE_LABELS = [(30, "statistically meaningful"), (10, "indicative"), (0, "exploratory only")]

# ---- capacity status -> availability when no published utilisation exists (ESTIMATED, documented)
STATUS_AVAILABILITY = {"operating": 1.0, "trial": 0.5, "reduced": 0.5, "disrupted": 0.5,
                       "shutdown": 0.0, "retired": 0.0}

# ---- point-in-time scoring / backtest
WEIGHT_REFIT_EVERY = 60        # bdays between weight refits (live and backtest)
WEIGHT_MIN_TRAIN = 250         # bdays of history needed before weights are learned (else prior)
SCORE_HORIZON = 20             # forward-return horizon (bdays) used to learn weights
ALERT_THRESHOLD = 50
BACKTEST_PRE_DAYS = 60         # how far before a true start an alert still counts as "early"

# ---- evidence gating
MIN_COVERAGE = 0.70            # share of score weight that must have data, else no alert-grade score
VINTAGE_POLICY = "exclude"     # records with unknown publication date on the information axis

# ---- data freshness: a source is "stale" when its last observation is older than this (calendar days)
FRESHNESS_DAYS = {"daily": 7, "10-day": 25, "monthly": 100, "irregular": 120}
