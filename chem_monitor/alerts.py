"""Alert text, historical analogue search, text dashboard, optional charts."""
import numpy as np
import pandas as pd
from .config import TARGET


def build_alert(ts, scored, comps, panel, events, infls, weights=None) -> str:
    """Plain-text alert. Every sentence comes from signals.interpret(), whose state is a pure function
    of the score - so the text can never contradict the number."""
    from .signals import interpret, event_context, analogue
    row = scored.loc[ts]
    blocks = scored[[c for c in scored if c.startswith("block.")]].rename(columns=lambda c: c[6:])
    it = interpret(row, blocks.loc[ts])
    p = panel[TARGET]
    ev = event_context(events, panel.get("derived.event_pressure", pd.Series(dtype=float)), ts)
    an = analogue(blocks.loc[ts], blocks, infls, ts)
    c = it["confirmation"]
    lines = [f"{it['icon']} H-ACID  {it['state']}  |  score {row['score']:.0f}/100  ({it['direction']})  "
             f"coverage {row['coverage']:.0%}",
             f"price {p.asof(ts):,.0f}  |  5d {p.pct_change(5, fill_method=None).asof(ts):+.1%}  "
             f"20d {p.pct_change(20, fill_method=None).asof(ts):+.1%}",
             it["sentence"],
             f"current pressure: {it['driver']}  |  confirming families: {c['confirming']}/{c['available']} "
             f"with data  |  evidence confidence: {it['evidence_confidence']}"]
    if ev["last_event"]:
        e = ev["last_event"]
        lines.append(f"last known event: {e['event_date']} - {e['event_type']} {e['company']}".rstrip())
    lines.append(f"current residual event pressure: {ev['residual_pressure']:+.2f} ({ev['text']})")
    lines.append(f"historical analogue: {an['label']}" + (f" - {an['id']} ({an['start']}) similarity "
                                                           f"{an['similarity']:.0f}%" if an["id"] else ""))
    return "\n".join(lines)


def render_dashboard(ts, scored, comps, panel, events, infls, weights=None) -> str:
    from .signals import strength
    row = scored.loc[ts]
    sc = 0 if pd.isna(row["score"]) else row["score"]
    bar = "█" * int(sc // 10) + "░" * (10 - int(sc // 10))
    blocks = {c[6:]: row[c] for c in scored if c.startswith("block.")}
    lead = [f"  {b:<11}{strength(v):<9}{'' if pd.isna(v) else f'{v:+.2f}'}" for b, v in blocks.items()]
    return "\n".join([f"H-ACID  {panel[TARGET].asof(ts):,.0f}/t",
                      f"INFLECTION SCORE  {bar} {sc:.0f}/100  {row['state']}",
                      "SIGNAL BLOCKS", *lead,
                      "", build_alert(ts, scored, comps, panel, events, infls, weights)])


def send(text: str, webhook=None):
    """POST to a Slack-style webhook if one is configured (the dashboard is already printed)."""
    if webhook:
        import requests
        requests.post(webhook, json={"text": text}, timeout=15)


def plot_forensics(panel, infls, scored=None, path="out/forensics.png"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rows = 2 if scored is not None else 1
    fig, ax = plt.subplots(rows, 1, figsize=(13, 4 * rows), sharex=True, squeeze=False)
    a = ax[0, 0]
    a.plot(panel.index, panel[TARGET], lw=1.4, color="k")
    for i in infls:
        a.axvspan(i.start, i.end, color="tab:green" if i.direction == "up" else "tab:red", alpha=.2)
        a.annotate(i.id, (i.start, i.start_price), fontsize=8)
    a.set_title("H-Acid master series with detected inflections")
    if scored is not None:
        b = ax[1, 0]
        b.plot(scored.index, scored["score"], color="tab:purple")
        for lim in (25, 50, 70):
            b.axhline(lim, ls=":", color="grey")
        b.set_title("Inflection score")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path
