"""ECB reference exchange rates (public SDMX API). USD/CNY = (CNY per EUR) / (USD per EUR).
Published ~16:00 CET on the reference date -> confirmed vintage (pub_date = obs_date)."""
import io
import pandas as pd
from .base import Collector, http_get

API = "https://data-api.ecb.europa.eu/service/data/EXR/D.CNY+USD.EUR.SP00.A"


class ECBFXCollector(Collector):
    name, tier = "ecb_fx", 1

    def __init__(self, since="2023-01-01"):
        self.since = since

    def fetch(self, mode="live"):
        start = self.since if mode == "backfill" else (pd.Timestamp.today() - pd.Timedelta(days=40)).strftime("%Y-%m-%d")
        url = f"{API}?startPeriod={start}&format=csvdata"
        d = pd.read_csv(io.StringIO(http_get(url, timeout=60).text))
        w = d.pivot_table(index="TIME_PERIOD", columns="CURRENCY", values="OBS_VALUE").dropna()
        fx = (w["CNY"] / w["USD"]).rename("value").reset_index()
        fx["obs_date"] = pd.to_datetime(fx["TIME_PERIOD"])
        out = fx[["obs_date", "value"]].assign(
            pub_date=lambda x: x["obs_date"], vintage_status="confirmed", series="fx.usdcny", location="",
            currency="CNY", unit="per USD", price_type="reference_rate", market="fx", quote_kind="reference",
            url=url, raw_text="ECB EXR CNY/EUR ÷ USD/EUR", confidence=1.0, value_kind="derived",
            date_precision="day", source=self.name, source_family="ecb", tier=self.tier)
        if out.empty:
            raise RuntimeError("no ECB rates returned")
        return out
