"""Daily change digest: compares yesterday's published summary with today's and writes a short,
plain-English message only when something a reader cares about changed. Used by update-data.yml,
which posts it as a comment on the 'Daily H-Acid updates' issue (GitHub then e-mails the owner).

python -m chem_monitor.notify OLD_SUMMARY NEW_SUMMARY NEW_INFLECTIONS SOURCES OUT_MD
Writes OUT_MD only if there is something to report."""
import json
import sys
from pathlib import Path


def _load(p):
    try:
        return json.loads(Path(p).read_text())
    except Exception:                                  # noqa: BLE001 - first run: no previous file
        return {}


def digest(old: dict, new: dict, infl: list, sources: list, site_url: str) -> str:
    lines = []
    op, np_ = old.get("price") or {}, new.get("price") or {}
    if np_ and np_.get("date") != op.get("date"):
        chg = ""
        if op.get("value"):
            pct = np_["value"] / op["value"] - 1
            chg = f" ({pct:+.1%} vs ¥{op['value']:,.0f} on {op.get('date')})"
        lines.append(f"- **New H-Acid price:** ¥{np_['value']:,.0f}/t on {np_['date']}{chg}.")
    ol, nl = old.get("live") or {}, new.get("live") or {}
    if nl.get("state") and nl.get("state") != ol.get("state"):
        lines.append(f"- **Cycle state changed:** {ol.get('state', '—')} → **{nl['state']}** (score {nl.get('score', 0):.0f}/100).")
    if new.get("n_inflections", 0) > old.get("n_inflections", 0) and infl:
        f = infl[-1]
        lines.append(f"- **New price surge detected ({f['id']}):** {f['magnitude']:+.0%} since {f['price_onset']['best']}. "
                     f"{(f.get('story') or {}).get('diagnosis', '')}")
    od = {t["block"]: t["word"] for t in old.get("tiles", [])}
    moved = [f"{t['label']}: {od.get(t['block'], '—')} → {t['word']}" for t in new.get("tiles", [])
             if od and od.get(t["block"]) != t["word"]]
    if moved:
        lines.append("- **Drivers changed:** " + "; ".join(moved) + ".")
    bad = [s["name"].split(" - ")[0].split(" (")[0] for s in sources if s.get("collector_status") in ("failed", "stale")]
    if bad:
        lines.append(f"- **Data warning:** {', '.join(sorted(set(bad)))} failed or is stale (previous data kept).")
    if not lines:
        return ""
    head = new.get("headline") or ""
    return "\n".join([f"**H-Acid update — {new.get('generated_at', '')}**", "", head, ""] + lines +
                     ["", f"[Open the monitor]({site_url})"])


def main(argv=None):
    a = argv or sys.argv[1:]
    old, new, infl, src, out = _load(a[0]), _load(a[1]), _load(a[2]) or [], _load(a[3]) or [], a[4]
    site = a[5] if len(a) > 5 else "https://arhamsaraogi-star.github.io/chemical/"
    text = digest(old, new, infl, src, site)
    if text:
        Path(out).write_text(text + "\n")
        print(text)
    else:
        print("nothing to report")


if __name__ == "__main__":
    main()
