"""UN Comtrade public preview API, HS 292221 (aminohydroxynaphthalenesulphonic acids and salts).

H-Acid dominates the code but it also contains J-acid, gamma-acid etc., so unit values are labelled
'unit value (HS 292221)' and never substituted for an H-Acid spot price.

Two kinds of series:
  export.hacid.qty / .value            China-reported exports to the World (FOB). China's monthly
                                        Comtrade reporting currently ends Dec 2024.
  mirror.<iso>.hacid.qty / .value      Imports FROM China reported by the destination (CIF). India
                                        (~half of China's exports), Korea and Indonesia keep reporting,
                                        so these mirror series carry the trade signal for 2025->.
Vintage: the API gives no release date. We use an EXPLICIT assumption pub_date = month end + 45 days
(China) / + 60 days (mirror) -> vintage_status 'estimated', never 'confirmed'.
"""
import pandas as pd
from .base import Collector, http_get

API = "https://comtradeapi.un.org/public/v1/preview/C/M/HS"
CHINA = 156
MIRRORS = {699: ("ind", "India"), 410: ("kor", "Korea"), 360: ("idn", "Indonesia")}
PUB_LAG = {"export": 45, "mirror": 60}


def months(start, end):
    return [p.strftime("%Y%m") for p in pd.period_range(start, end, freq="M")]


class ComtradeCollector(Collector):
    name, tier = "comtrade", 1

    def __init__(self, since="2023-01", delay=1.5):
        self.since, self.delay = since, delay
        self.destinations = pd.DataFrame()

    def _get(self, reporter, period, partner, flow):
        q = f"{API}?reporterCode={reporter}&period={period}&cmdCode=292221&flowCode={flow}"
        if partner is not None:
            q += f"&partnerCode={partner}"
        js = http_get(q, timeout=60, delay=self.delay).json()
        if js.get("error"):
            raise RuntimeError(js["error"])
        return js.get("data") or [], q

    def _rows(self, data, url, per, prefix, location, kind, value_field):
        if not data:
            return []
        r = data[0]
        obs = pd.Period(per, "M").to_timestamp(how="end").normalize()
        kg, usd = r.get("netWgt") or r.get("qty"), r.get(value_field) or r.get("primaryValue")
        common = {"obs_date": obs, "pub_date": obs + pd.Timedelta(days=PUB_LAG[kind]),
                  "vintage_status": "estimated", "location": location, "market": "export",
                  "price_type": "FOB" if kind == "export" else "CIF (importer-reported)",
                  "quote_kind": "customs", "grade": "HS 292221", "date_precision": "month",
                  "value_kind": "observed", "url": url, "confidence": 1.0}
        out = []
        if kg:
            out.append({**common, "series": f"{prefix}.qty", "value": kg / 1000.0, "unit": "t",
                        "raw_text": f"netWgt={kg} kg; isQtyEstimated={r.get('isQtyEstimated')}"})
        if usd:
            out.append({**common, "series": f"{prefix}.value", "value": float(usd), "unit": "USD",
                        "currency": "USD", "raw_text": f"{value_field}={usd} USD"})
        return out

    def fetch(self, mode="live"):
        today = pd.Timestamp.today()
        start = self.since if mode == "backfill" else (today - pd.DateOffset(months=6)).strftime("%Y-%m")
        rows, dest, errors = [], [], []
        for per in months(start, (today - pd.DateOffset(months=1)).strftime("%Y-%m")):
            try:
                data, url = self._get(CHINA, per, 0, "X")
                rows += self._rows(data, url, per, "export.hacid", "World", "export", "fobvalue")
                if data and mode == "backfill":
                    pdata, _ = self._get(CHINA, per, None, "X")
                    dest += [{"period": per, "partner_code": d["partnerCode"], "qty_t": d["netWgt"] / 1000.0,
                              "fob_usd": d.get("fobvalue") or d.get("primaryValue")}
                             for d in pdata if d.get("partnerCode") and d.get("netWgt")]
            except Exception as e:                 # noqa: BLE001
                errors.append(f"{per} China: {e}")
            for rep, (iso, label) in MIRRORS.items():
                try:
                    data, url = self._get(rep, per, CHINA, "M")
                    rows += self._rows(data, url, per, f"mirror.{iso}.hacid", f"{label} (from China)",
                                       "mirror", "cifvalue")
                except Exception as e:             # noqa: BLE001
                    errors.append(f"{per} {label}: {e}")
        df = pd.DataFrame(rows)
        df.attrs["errors"] = errors
        self.destinations = pd.DataFrame(dest)
        if df.empty:
            raise RuntimeError("no Comtrade rows" + (": " + errors[0] if errors else ""))
        df["source"], df["source_family"], df["tier"] = self.name, "un_comtrade", self.tier
        return df
