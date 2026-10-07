/* Chemical Cycle Monitor - static front end. Reads site/data/*.json produced by chem_monitor.report.
   No framework, no tracking. All data-derived text is inserted with textContent. */
(function () {
  "use strict";
  const CHEM = "hacid";
  const cache = {};
  const load = (p) => cache[p] || (cache[p] = fetch(p, { cache: "no-cache" }).then((r) => { if (!r.ok) throw new Error(p + " " + r.status); return r.json(); }));
  const D = (name) => load(`data/${CHEM}/${name}.json`);
  const COLORS = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)", "var(--s7)", "var(--s8)"];
  const STATE_COLOR = { "NORMAL": "var(--good)", "WATCH": "var(--warning)", "DEVELOPING INFLECTION": "var(--serious)",
    "STRONG INFLECTION": "var(--critical)", "MAJOR INFLECTION": "var(--critical)", "NO DATA": "var(--muted)" };

  // ---------------------------------------------------------------- tiny DOM helper
  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const k in attrs || {}) {
      const v = attrs[k];
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") e.className = v;
      else if (k === "style" && typeof v === "object") { for (const sk in v) { if (sk.startsWith("--")) e.style.setProperty(sk, v[sk]); else e.style[sk] = v[sk]; } }
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else if (k === "html") { /* never used with data */ }
      else e.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat(Infinity)) {
      if (c === null || c === undefined || c === false) continue;
      e.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return e;
  }
  const fmtN = (v, d = 0) => v === null || v === undefined || isNaN(v) ? "—" : Number(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
  const fmtCNY = (v) => v === null || v === undefined ? "—" : "¥" + fmtN(v);
  const pct = (v, d = 1) => v === null || v === undefined || isNaN(v) ? "—" : (v > 0 ? "+" : "") + (v * 100).toFixed(d) + "%";
  const fmtD = (s) => !s ? "—" : new Date(s + "T00:00:00Z").toLocaleDateString("en-GB", { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" });
  const kind = (k) => h("span", { class: "kind " + (k || "observed") }, (k || "observed").replace("_", "-"));
  const dirCls = (v) => v > 0 ? "up" : v < 0 ? "down" : "";
  const link = (href, txt) => h("a", { href }, txt);
  const ext = (href, txt) => href ? h("a", { href, target: "_blank", rel: "noopener noreferrer" }, txt || "source ↗") : "—";
  const statusDot = (label, c) => h("span", { class: "status", style: { "--c": c } }, label);
  const sampleNote = (n, label) => h("span", { class: "tag" }, `N = ${n} — ${label}`);

  // ---------------------------------------------------------------- shell
  const NAV = [["#/", "Dashboard"], ["#/h-acid", "H-Acid"], ["#/history", "History"], ["#/events", "Events"],
    ["#/supply", "Supply"], ["#/quality", "Data quality"], ["#/sources", "Sources"], ["#/methodology", "Methodology"], ["#/about", "About"]];
  function shell() {
    const nav = h("nav", { class: "main", "aria-label": "Sections" }, NAV.map(([href, t]) => h("a", { href }, t)));
    const theme = h("button", { class: "icon", title: "Toggle light/dark", "aria-label": "Toggle colour theme", onclick: toggleTheme }, "◐");
    const upd = h("span", { class: "updated", id: "updated" }, "");
    document.body.prepend(h("header", { class: "top" }, h("div", { class: "top-inner" },
      h("a", { class: "brand", href: "#/" }, "CHEMICAL CYCLE MONITOR"), nav, upd, theme)));
    load("data/meta.json").then((m) => { upd.textContent = "Updated " + m.generated_at; }).catch(() => {});
  }
  function toggleTheme() {
    const r = document.documentElement;
    const dark = r.dataset.theme ? r.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    r.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("ccm-theme", r.dataset.theme); } catch (e) { /* storage unavailable */ }
  }
  try { const th = localStorage.getItem("ccm-theme"); if (th) document.documentElement.dataset.theme = th; } catch (e) { /* ignore */ }

  // ---------------------------------------------------------------- shared widgets
  function priceChart(root, S, opts) {
    opts = opts || {};
    const sp = S.series["hacid.spot"];
    const series = [];
    if (sp) series.push({ id: "hacid.spot", label: "Market price", color: COLORS[0], points: sp.points, maxGapDays: 75, extendTo: opts.today });
    const q = S.series["hacid.quote"];
    if (q && opts.quotes) series.push({ id: "hacid.quote", label: "Producer / ex-works quotes", color: COLORS[1], points: q.points, maxGapDays: 75, visible: false, step: false });
    const markers = (S.inflections || []).map((i) => ({ id: i.id, start: i.start, end: i.end, direction: i.direction, onClick: () => { location.hash = "#/inflection/" + i.id; } }));
    const box = h("div", {});
    const ranges = h("div", { class: "seg", role: "group", "aria-label": "Date range" });
    const toolbar = h("div", { class: "chart-toolbar" }, ranges);
    root.appendChild(toolbar); root.appendChild(box);
    const ch = new TSChart(box, { series, markers, events: opts.events || [], range: opts.range || "MAX", height: opts.height || 320,
      yFormat: (v) => "¥" + (v >= 1000 ? fmtN(v / 1000, v >= 100000 ? 0 : 0) + "k" : fmtN(v)), ariaLabel: "H-Acid price chart", xMax: opts.today });
    for (const r of Object.keys(TSChart.RANGES)) {
      const b = h("button", { class: r === (opts.range || "MAX") ? "on" : "", onclick: () => { ch.setRange(r); [...ranges.children].forEach((x) => x.classList.toggle("on", x === b)); } }, r);
      ranges.appendChild(b);
    }
    if (series.length > 1) {
      for (const s of series) {
        const tg = h("button", { class: "toggle", "aria-pressed": String(s.visible !== false), style: { "--k": s.color } }, h("span", { class: "key" }), s.label);
        tg.addEventListener("click", () => { const v = tg.getAttribute("aria-pressed") !== "true"; tg.setAttribute("aria-pressed", String(v)); ch.setVisible(s.id, v); });
        toolbar.appendChild(tg);
      }
    }
    toolbar.appendChild(h("span", { class: "tiny muted", style: { marginLeft: "auto" } }, "Drag to zoom · double-click to reset · shaded = detected inflection"));
    return ch;
  }

  function sourceLine(meta, extra) {
    return h("div", { class: "src-line" },
      h("span", {}, kind(meta.kind), " ", meta.families && meta.families.length ? "Source families: " + meta.families.join(", ") : ""),
      meta.points && meta.points.length ? h("span", {}, `Coverage ${fmtD(meta.points[0][0])} – ${fmtD(meta.points[meta.points.length - 1][0])} · ${meta.points.length} observations`) : null,
      extra || null);
  }

  function smallChart(root, title, list, S, opts) {
    opts = opts || {};
    const avail = list.filter((id) => S.series[id]);
    const card = h("section", { class: "card" }, h("h2", {}, h("span", {}, title), opts.badge || null));
    root.appendChild(card);
    if (!avail.length) { card.appendChild(h("p", { class: "muted small" }, opts.empty || "No data collected for this block yet.")); return; }
    const indexed = opts.indexed && avail.length > 1;
    const series = avail.map((id, k) => {
      const m = S.series[id];
      let pts = m.points;
      if (indexed) { const b = pts[0][1]; pts = pts.map((p) => [p[0], 100 * p[1] / b]); }
      return { id, label: m.label, color: COLORS[(opts.colorOffset || 0) + k], points: pts, maxGapDays: opts.maxGap || 45, step: opts.step !== false };
    });
    const box = h("div", {}); card.appendChild(box);
    new TSChart(box, { series, height: opts.height || 200, range: "MAX", yFormat: indexed ? (v) => fmtN(v) : (opts.yFormat || ((v) => fmtN(v))) });
    if (series.length > 1) card.appendChild(h("div", { class: "legend" }, series.map((s) => h("span", { style: { "--k": s.color } }, s.label))));
    if (indexed) card.appendChild(h("div", { class: "tiny muted" }, "Indexed: each series = 100 at its first observation (one axis; units differ)."));
    for (const id of avail) card.appendChild(sourceLine(S.series[id], h("span", {}, S.series[id].label + " · " + S.series[id].unit)));
  }

  function blocksList(blocks, conf) {
    const order = ["SUPPLY", "INVENTORY", "COST", "DEMAND", "DOWNSTREAM", "TRADE", "EVENTS", "PRICE"];
    return h("div", { class: "blocks" }, order.filter((b) => blocks[b]).map((b) => {
      const x = blocks[b], v = x.value;
      const bar = h("div", { class: "diverge", title: v === null ? "no data" : `block value ${v.toFixed(2)} (−1 bearish … +1 bullish)` });
      if (v !== null) {
        const w = Math.min(50, Math.abs(v) * 50);
        bar.appendChild(h("i", { style: { left: v >= 0 ? "50%" : (50 - w) + "%", width: w + "%", background: v >= 0 ? "var(--s2)" : "var(--s1)" } }));
      }
      const confirms = conf && conf.confirming_blocks && conf.confirming_blocks.includes(b);
      return h("div", { class: "block-row" }, h("span", { class: "name" }, b),
        bar, h("span", { class: "small " + (v === null ? "muted" : ""), style: { textAlign: "right" } },
          x.strength, x.direction ? (x.direction === "up" ? " ↑" : " ↓") : "", confirms ? " ✓" : ""));
    }));
  }

  // ---------------------------------------------------------------- pages
  async function pageDashboard(main) {
    const [S, X, ser, meta] = await Promise.all([D("summary"), D("stats"), D("series"), load("data/meta.json")]);
    const L = S.live || {};
    const today = S.generated_at ? S.generated_at.slice(0, 10) : null;
    main.appendChild(h("div", { class: "section-title", style: { marginTop: 0 } },
      h("div", {}, h("div", { class: "kicker" }, "H-Acid · China"), h("h1", {}, "Is a genuine chemical-cycle inflection developing?")),
      h("div", { class: "chem-strip", "aria-label": "Chemicals monitored" }, (meta.chemicals || []).map((c) =>
        h("a", { class: "chem-chip" + (c.id === CHEM ? " on" : ""), href: "#/" }, h("span", { class: "dot", style: { background: STATE_COLOR[c.state] || "var(--muted)" } }),
          c.name, h("b", {}, c.score === null || c.score === undefined ? "—" : String(Math.round(c.score))))))));

    // signal card
    const P = S.price || {};
    const stColor = STATE_COLOR[L.state] || "var(--muted)";
    const sc = L.score === null || L.score === undefined ? null : L.score;
    const c = L.confirmation || {};
    const chg = S.changes || {};
    const card = h("section", { class: "card signal", "aria-label": "Current signal" },
      h("div", { class: "kicker" }, "H-ACID · CHINA MARKET PRICE ", kind("observed")),
      h("div", { class: "price" }, fmtCNY(P.value), h("span", { class: "unit" }, " / t")),
      h("div", { class: "small muted" }, `as of ${fmtD(P.date)} · ${P.source_family || ""}${P.age_days > 3 ? ` · ${P.age_days} days old` : ""}`),
      h("div", { class: "chg-row" }, ["1D", "5D", "20D", "60D", "1Y"].map((k) => h("span", { title: chg[k] ? `vs ${fmtD(chg[k].from_date)} (${fmtCNY(chg[k].from_value)})` : "no observation near the comparison date" },
        h("span", { class: "muted" }, k + " "), h("b", { class: chg[k] ? dirCls(chg[k].pct) : "muted" }, chg[k] ? pct(chg[k].pct) : "n/a")))),
      h("div", { class: "state" }, h("span", { class: "dot", style: { background: stColor } }), h("span", { class: "label" }, L.state || "NO DATA"), kind("derived")),
      h("div", { class: "score" }, sc === null ? "—" : Math.round(sc), h("small", {}, " / 100")),
      h("div", { class: "meter", role: "meter", "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": sc || 0 }, h("i", { style: { width: (sc || 0) + "%", background: stColor } })),
      h("div", { class: "meter-ticks" }, ["0", "25", "50", "70", "85", "100"].map((x) => h("span", {}, x))),
      h("p", { class: "small", style: { margin: "10px 0 0" } }, L.sentence || ""),
      h("dl", { class: "kv" },
        h("dt", {}, "Current pressure"), h("dd", {}, L.driver || "—", " ", kind("inferred")),
        h("dt", {}, "Confirmation"), h("dd", {}, c.available !== undefined ? `${c.confirming} / ${c.available} independent information families with data` : "—"),
        h("dt", {}, "Evidence"), h("dd", {}, `${L.evidence_confidence || "—"} confidence · coverage ${L.coverage !== undefined ? Math.round(L.coverage * 100) + "%" : "—"}`),
        h("dt", {}, "Detected"), h("dd", {}, L.detected_since ? `since ${fmtD(L.detected_since)}` : "No active alert"),
        h("dt", {}, "Data quality"), h("dd", {}, Math.round((S.quality.overall || 0) * 100) + "%", " ", link("#/quality", "details")),
        h("dt", {}, "Score as of"), h("dd", {}, fmtD(L.as_of), " ", h("span", { class: "muted tiny" }, "(point-in-time)"))));
    const chartCard = h("section", { class: "card" }, h("h2", {}, h("span", {}, "Price — China market average (CNY/t)"), link("#/h-acid", "All series →")));
    const hero = h("div", { class: "grid g-hero" }, card, chartCard);
    main.appendChild(hero);
    const evs = await D("events");
    priceChart(chartCard, ser, { today, events: evs.map((e) => ({ date: e.event_date, label: `${e.type}: ${e.company || "industry"}` })) });
    chartCard.appendChild(sourceLine(ser.series["hacid.spot"] || {}, h("span", {}, "Step line = last observed value; dashed = unobserved gap > 75 days")));

    // why is it moving
    const why = h("section", { class: "card" }, h("h2", {}, h("span", {}, "Why is it moving?"), h("span", { class: "tiny muted" }, "signal blocks · −1 bearish … +1 bullish · ✓ confirms")),
      blocksList(L.blocks || {}, c),
      h("p", { class: "tiny muted", style: { marginBottom: 0 } }, "Correlated indicators are averaged inside a block, so the H-Acid price and producer quotes count once. ", link("#/methodology", "How blocks work")));
    // context
    const an = L.analogue || {};
    const ev = (L.events || {});
    const lastInf = (X.inflections || []).slice(-1)[0];
    const ctx = h("section", { class: "card" }, h("h2", {}, "Historical context"),
      h("dl", { class: "kv", style: { marginTop: 0 } },
        h("dt", {}, "Closest analogue"), h("dd", {}, an.id ? h("span", {}, link("#/inflection/" + an.id, `${an.id} (${fmtD(an.start)})`), ` · similarity ${an.similarity}% · ${an.label}`) : (an.label || "No strong historical analogue")),
        h("dt", {}, "Inflections found"), h("dd", {}, `${X.n_inflections} since ${ser.series["hacid.spot"] ? fmtD(ser.series["hacid.spot"].points[0][0]) : "—"} `, sampleNote(X.n_inflections, X.sample_label)),
        h("dt", {}, "Most recent"), h("dd", {}, lastInf ? h("span", {}, link("#/inflection/" + lastInf.id, lastInf.id), ` ${lastInf.direction === "up" ? "▲" : "▼"} ${pct(lastInf.magnitude)} from ${fmtD(String(lastInf.start).slice(0, 10))}`) : "—"),
        h("dt", {}, "Last known event"), h("dd", {}, ev.last_event ? `${fmtD(ev.last_event.event_date)} — ${ev.last_event.event_type} ${ev.last_event.company}` : "—"),
        h("dt", {}, "Residual event pressure"), h("dd", {}, `${fmtN(ev.residual_pressure, 2)} · ${ev.text || ""}`)),
      h("p", { style: { marginBottom: 0 } }, link("#/history", "View forensic analysis →")));
    main.appendChild(h("div", { class: "grid g2", style: { marginTop: "16px" } }, why, ctx));

    // quality + freshness
    const Q = S.quality;
    const qcard = h("section", { class: "card" }, h("h2", {}, h("span", {}, "Data quality ", h("b", {}, Math.round(Q.overall * 100) + "%")), link("#/quality", "Details →")),
      h("div", { class: "table-wrap" }, h("table", {}, h("tbody", {}, Q.groups.map((g) => h("tr", {}, h("td", {}, g.group), h("td", { class: "num" }, Math.round(g.coverage * 100) + "%"),
        h("td", {}, statusDot(g.coverage >= 0.9 ? "good" : g.coverage >= 0.6 ? "partial" : g.coverage > 0 ? "sparse" : "none", g.coverage >= 0.9 ? "var(--good)" : g.coverage >= 0.6 ? "var(--warning)" : "var(--critical)"))))))),
      h("p", { class: "tiny muted", style: { marginBottom: 0 } }, `Point-in-time: ${Math.round(Q.overall_pit_coverage * 100)}% of records (confirmed ${Math.round(Q.confirmed_share * 100)}%, estimated ${Math.round(Q.estimated_share * 100)}%, unknown ${Math.round(Q.unknown_share * 100)}%) · ${Q.independent_families} independent source families · coverage over trailing ${Q.window_days} days`));
    const fcard = h("section", { class: "card" }, h("h2", {}, h("span", {}, "Source freshness"), link("#/sources", "All sources →")),
      h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Source"), h("th", {}, "Last observation"), h("th", {}, "Status"))),
        h("tbody", {}, (S.freshness || []).filter((f) => f.last_observation_date || f.collector_status === "failed").map((f) => h("tr", {}, h("td", {}, f.name.split(" - ")[0].split(" (")[0]),
          h("td", { class: "num" }, f.last_observation_date ? `${fmtD(f.last_observation_date)}` : "—", f.age_days !== null && f.age_days !== undefined ? h("span", { class: "muted" }, ` · ${f.age_days}d`) : null),
          h("td", {}, statusDot(f.collector_status, { ok: "var(--good)", partial: "var(--warning)", curated: "var(--s1)", stale: "var(--warning)", failed: "var(--critical)" }[f.collector_status] || "var(--muted)"))))))),
      h("p", { class: "tiny muted", style: { marginBottom: 0 } }, "Monthly trade data is never 'live': it arrives ~2 months after the month it describes."));
    main.appendChild(h("div", { class: "grid g2", style: { marginTop: "16px" } }, qcard, fcard));
  }

  async function pageDetail(main) {
    const [S, ser, sum] = await Promise.all([D("series"), D("series"), D("summary")]);
    main.appendChild(h("div", { class: "section-title", style: { marginTop: 0 } }, h("div", {}, h("div", { class: "kicker" }, "H-Acid · China"), h("h1", {}, "All series"))));
    main.appendChild(h("p", { class: "lede" }, "Each chart has one axis. Series in different units are shown as separate charts or indexed to 100. Points are real observations; lines carry the last observation forward until the next one."));
    const pc = h("section", { class: "card" }, h("h2", {}, "H-Acid price & producer quotes (CNY/t)"));
    main.appendChild(pc);
    priceChart(pc, ser, { quotes: true, today: sum.generated_at.slice(0, 10) });
    pc.appendChild(sourceLine(ser.series["hacid.spot"] || {}));
    if (ser.series["hacid.quote"]) pc.appendChild(sourceLine(ser.series["hacid.quote"], h("span", {}, "Producer quotes: ex-works quotations / ex-works reference-range midpoints")));
    const g = h("div", { class: "grid g2", style: { marginTop: "16px" } }); main.appendChild(g);
    smallChart(g, "Feedstocks (indexed)", ["feed.naphthalene_refined", "feed.naphthalene_industrial", "feed.sulfuric_acid", "feed.nitric_acid", "feed.caustic_soda"], ser, { indexed: true, badge: kind("observed") });
    smallChart(g, "Feedstock price index", ["derived.cost_idx"], ser, { badge: kind("derived"), colorOffset: 6 });
    smallChart(g, "Reactive dyes (CNY/t)", ["dye.reactive", "dye.reactive_black_sci99"], ser, { badge: kind("observed"), maxGap: 400, colorOffset: 2 });
    smallChart(g, "Exports — imports from China reported by destinations (t / month)", ["mirror.ind.hacid.qty", "mirror.kor.hacid.qty", "mirror.idn.hacid.qty", "export.hacid.qty"], ser, { badge: kind("observed"), step: false, maxGap: 70 });
    smallChart(g, "Export / import unit value (USD/t, HS 292221)", ["derived.export_uv", "derived.export_uv_china"], ser, { badge: kind("derived"), step: false, maxGap: 70 });
    smallChart(g, "Supply — available share of known capacity", ["derived.supply_index"], ser, { badge: kind("estimated"), yFormat: (v) => Math.round(v * 100) + "%", maxGap: 2000 });
    smallChart(g, "Inventory", [], ser, { empty: "No reliable public inventory series exists for H-Acid. Marked unavailable - no synthetic inventory is used." });
    const scard = h("section", { class: "card" }, h("h2", {}, h("span", {}, "Point-in-time inflection score"), kind("derived")));
    g.appendChild(scard);
    const ok = (S.score || []).filter((r) => r.status === "ok").map((r) => [r.d, r.score]);
    const weak = (S.score || []).filter((r) => r.status !== "ok").map((r) => [r.d, r.score]);
    const ss = [];
    if (ok.length) ss.push({ id: "ok", label: "Score (alert-grade)", color: COLORS[6], points: ok, step: false, dots: false, maxGapDays: 4 });
    if (weak.length) ss.push({ id: "weak", label: "Raw score, insufficient evidence (capped at WATCH)", color: "var(--axis)", points: weak, step: false, dots: false, maxGapDays: 4 });
    if (ss.length) { const b = h("div", {}); scard.appendChild(b); new TSChart(b, { series: ss, height: 200, yFormat: (v) => fmtN(v) }); scard.appendChild(h("div", { class: "legend" }, ss.map((x) => h("span", { style: { "--k": x.color } }, x.label)))); }
    else scard.appendChild(h("p", { class: "muted small" }, "Not enough point-in-time history to score yet."));
    scard.appendChild(h("div", { class: "src-line" }, "Bands: 25 WATCH · 50 DEVELOPING · 70 STRONG · 85 MAJOR. Rows with coverage below the minimum are capped at WATCH."));

    // provenance table
    main.appendChild(h("div", { class: "section-title" }, h("h2", {}, "Every H-Acid price observation"), h("span", { class: "small muted" }, "provenance, vintage and the original sentence")));
    const rows = [];
    for (const [fam, list] of Object.entries(S.by_family || {})) for (const r of list) rows.push(Object.assign({ fam }, r));
    rows.sort((a, b) => b.d.localeCompare(a.d));
    main.appendChild(h("div", { class: "card table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Obs. date", "Value", "Kind", "Family", "Published", "Vintage", "Via", "Evidence"].map((x) => h("th", { class: x === "Value" ? "num" : "" }, x)))),
      h("tbody", {}, rows.map((r) => h("tr", {}, h("td", { class: "num" }, fmtD(r.d), r.precision && r.precision !== "day" ? h("div", { class: "tiny muted" }, r.precision) : null), h("td", { class: "num" }, fmtCNY(r.v)), h("td", {}, kind(r.kind)), h("td", {}, r.fam),
        h("td", { class: "num" }, fmtD(r.pub)), h("td", {}, r.vintage), h("td", { class: "small" }, r.via || r.src, " ", ext(r.url, "↗")), h("td", { class: "small ink2", style: { maxWidth: "420px" } }, r.text || "")))))));
  }

  async function pageHistory(main) {
    const [X, I] = await Promise.all([D("stats"), D("inflections")]);
    main.appendChild(h("div", { class: "section-title", style: { marginTop: 0 } }, h("div", {}, h("div", { class: "kicker" }, "H-Acid"), h("h1", {}, "History & inflections")), sampleNote(X.n_inflections, X.sample_label)));
    main.appendChild(h("p", { class: "lede" }, "Inflections are detected on the economic timeline (when prices actually moved). System detection is tested on the information timeline - using only data that was public at the time."));
    main.appendChild(h("div", { class: "card table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["ID", "Onset (best)", "Window", "Direction", "Magnitude", "Driver", "Detection lead", "Confidence"].map((x) => h("th", {}, x)))),
      h("tbody", {}, I.slice().reverse().map((f) => h("tr", { class: "click", onclick: () => { location.hash = "#/inflection/" + f.id; } },
        h("td", {}, link("#/inflection/" + f.id, f.id)), h("td", { class: "num" }, fmtD(f.price_onset.best)), h("td", { class: "num small" }, `${fmtD(f.price_onset.earliest)} – ${fmtD(f.price_onset.latest)}`),
        h("td", { class: f.direction === "up" ? "up" : "down" }, f.direction === "up" ? "▲ up" : "▼ down"), h("td", { class: "num" }, pct(f.magnitude)),
        h("td", {}, f.driver.type), h("td", { class: "num" }, f.detection_lead_days === null ? h("span", { class: "muted small" }, f.system_detection.evaluable ? "not detected" : "not evaluable") : `${f.detection_lead_days} d`),
        h("td", {}, f.confidence)))))));
    if (!I.length) main.appendChild(h("p", { class: "muted" }, "No inflection has been detected in the observed history."));

    // backtest + hit rates
    const bs = X.backtest_summary || {};
    main.appendChild(h("div", { class: "section-title" }, h("h2", {}, "As-of detection backtest"), h("span", { class: "small muted" }, "information axis · threshold ", bs.threshold)));
    main.appendChild(h("div", { class: "grid g4" }, [["Evaluable inflections", bs.inflections_evaluable], ["Detected", bs.detected], ["Median days earlier than price rule", bs.median_days_earlier_than_price_rule === null || bs.median_days_earlier_than_price_rule === undefined || isNaN(bs.median_days_earlier_than_price_rule) ? "—" : bs.median_days_earlier_than_price_rule], ["False-alarm episodes", bs.false_alarm_episodes]].map(([k, v]) =>
      h("div", { class: "card" }, h("div", { class: "kicker" }, k), h("div", { class: "score" }, v === undefined ? "—" : String(v))))));
    main.appendChild(h("p", { class: "small muted" }, "With very few evaluable inflections these numbers describe what happened; they are not evidence of skill."));
    const hr = X.hit_rates || [];
    main.appendChild(h("div", { class: "section-title" }, h("h2", {}, "Leading indicators — hit rates"), h("span", { class: "small muted" }, "share of inflections preceded by a ≥1σ move, vs base rate")));
    if (!hr.length) main.appendChild(h("p", { class: "muted small" }, "Not computable yet: leading-indicator series need ≥120 observations and at least one inflection inside their coverage."));
    else main.appendChild(h("div", { class: "card table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Variable", "Lead (days)", "N", "Hits", "Hit rate", "Base rate", "Lift", "Sample"].map((x) => h("th", {}, x)))),
      h("tbody", {}, hr.map((r) => h("tr", {}, h("td", {}, r.variable), h("td", { class: "num" }, r.lead_days), h("td", { class: "num" }, r.n_inflections), h("td", { class: "num" }, r.hits), h("td", { class: "num" }, pct(r.hit_rate, 0)), h("td", { class: "num" }, pct(r.base_rate, 0)), h("td", { class: "num" }, fmtN(r.lift, 2)), h("td", {}, h("span", { class: "tag" }, r.sample_label))))))));
  }

  async function pageInflection(main, id) {
    const [I, ser, evs, sum] = await Promise.all([D("inflections"), D("series"), D("events"), D("summary")]);
    const f = I.find((x) => x.id === id);
    if (!f) { main.appendChild(h("p", {}, "Unknown inflection ", id, ". ", link("#/history", "Back to history"))); return; }
    const up = f.direction === "up";
    main.appendChild(h("div", { class: "section-title", style: { marginTop: 0 } }, h("div", {}, h("div", { class: "kicker" }, link("#/history", "History"), " / " + f.id),
      h("h1", {}, `${f.id} — ${f.driver.type.toUpperCase()} ${up ? "UPWARD" : "DOWNWARD"} INFLECTION`)), h("span", { class: "tag" }, "Confidence: " + f.confidence)));
    const po = f.price_onset, fo = f.fundamental_onset;
    const kv = (k, v, kd) => [h("dt", {}, k), h("dd", {}, v, kd ? [" ", kind(kd)] : null)];
    const facts = h("section", { class: "card" }, h("dl", { class: "kv", style: { marginTop: 0 } },
      kv("Fundamental onset", fo.date ? `${fmtD(fo.date)}${fo.earliest && fo.earliest !== fo.latest ? ` (window ${fmtD(fo.earliest)} – ${fmtD(fo.latest)})` : ""} · ${fo.evidence}` : fo.evidence, "inferred"),
      kv("Publicly observable", fo.public_date ? fmtD(fo.public_date) : "—", fo.public_date ? "observed" : null),
      kv("Price regime onset", `${fmtD(po.best)}${po.exact ? "" : ` · plausible ${fmtD(po.earliest)} – ${fmtD(po.latest)}`}`, "estimated"),
      kv("Onset confidence", `${po.confidence} (spread ${po.spread_days} days)`),
      kv("Price trigger", `${fmtD(f.price_trigger)} (${f.rule})`, "derived"),
      kv("System detection", f.system_detection.text, "derived"),
      kv("Detection lead", f.detection_lead_days === null ? "—" : `${f.detection_lead_days} days before the price rule`),
      kv("Magnitude", `${pct(f.magnitude)} (${fmtCNY(f.start_price)} → ${fmtCNY(f.end_price)})`, "observed"),
      kv("Shape", f.shape.replace("_", " ")),
      kv("Primary driver", f.driver.type, "inferred"),
      kv("Amplifiers", f.driver.amplifiers.length ? f.driver.amplifiers.join(", ") : "none"),
      kv("Historical analogue", f.analogue && f.analogue.id ? `${f.analogue.id} · similarity ${f.analogue.similarity}%` : (f.analogue ? f.analogue.label : "—")),
      kv("Outcome (hindsight)", f.historical_outcome || "—")));
    const evid = h("section", { class: "card" }, h("h2", {}, "Evidence"),
      f.driver.evidence.length ? h("ul", { class: "small", style: { paddingLeft: "18px", margin: 0 } }, f.driver.evidence.map((e) => h("li", {}, e))) : h("p", { class: "muted small" }, "No fundamental evidence available at the move's start - the label is price-led / unclassified."),
      h("h3", { style: { marginTop: "16px" } }, "Timeline"),
      h("ul", { class: "timeline" }, f.timeline.map((x) => h("li", {}, h("span", { class: "when" }, fmtD(x.date)), h("span", { class: "dot", style: { "--c": x.kind === "event" ? (x.direction < 0 ? "var(--s2)" : "var(--s3)") : x.type === "system_detection" ? "var(--s7)" : "var(--s1)" } }),
        h("span", {}, x.kind === "event" ? h("span", {}, `${x.type}: ${x.company || "industry"}`, x.precision && x.precision !== "day" ? h("span", { class: "muted tiny" }, ` (date precision: ${x.precision})`) : null, x.public_date ? h("span", { class: "muted tiny" }, ` · public ${fmtD(x.public_date)}`) : null, " ", ext(x.url, "↗")) : h("span", {}, x.label, " ", kind(x.kind)))))));
    main.appendChild(h("div", { class: "grid g2" }, facts, evid));
    const pc = h("section", { class: "card", style: { marginTop: "16px" } }, h("h2", {}, "Price around the move"));
    main.appendChild(pc);
    const ch = priceChart(pc, ser, { quotes: true, today: sum.generated_at.slice(0, 10), events: evs.map((e) => ({ date: e.event_date, label: `${e.type}: ${e.company || "industry"}` })) });
    const a = Date.parse(po.earliest + "T00:00:00Z") - 120 * 86400000, b = Date.parse(f.end + "T00:00:00Z") + 60 * 86400000;
    ch.zoom = [a, b]; ch.render();
  }

  async function pageEvents(main) {
    const E = await D("events");
    main.appendChild(h("div", { class: "section-title", style: { marginTop: 0 } }, h("div", {}, h("div", { class: "kicker" }, "H-Acid"), h("h1", {}, "Events"))));
    main.appendChild(h("p", { class: "lede" }, "Shutdowns, accidents, environmental actions, policy and capacity changes. Each event keeps two dates: when it happened (economic) and when it became public (information). Direction is the effect on SUPPLY."));
    const types = [...new Set(E.map((e) => e.type))].sort(), cos = [...new Set(E.map((e) => e.company).filter(Boolean))].sort();
    const fType = h("select", { "aria-label": "Event type" }, h("option", { value: "" }, "All types"), types.map((t) => h("option", { value: t }, t)));
    const fCo = h("select", { "aria-label": "Company" }, h("option", { value: "" }, "All companies"), cos.map((t) => h("option", { value: t }, t)));
    const fSev = h("select", { "aria-label": "Severity" }, h("option", { value: "" }, "Any severity"), [1, 2, 3].map((s) => h("option", { value: s }, "≥ " + s)));
    const q = h("input", { type: "search", placeholder: "Search…", "aria-label": "Search events" });
    main.appendChild(h("div", { class: "filters" }, fType, fCo, fSev, q));
    const body = h("tbody", {});
    main.appendChild(h("div", { class: "card table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Event date", "Public", "Type", "Company / plant", "Capacity", "Supply", "Sev.", "Evidence", "Source"].map((x) => h("th", {}, x)))), body)));
    const draw = () => {
      body.textContent = "";
      const s = q.value.toLowerCase();
      E.slice().reverse().filter((e) => (!fType.value || e.type === fType.value) && (!fCo.value || e.company === fCo.value) && (!fSev.value || e.severity >= +fSev.value) &&
        (!s || JSON.stringify(e).toLowerCase().includes(s))).forEach((e) => body.appendChild(h("tr", {},
          h("td", { class: "num" }, fmtD(e.event_date), e.precision !== "day" ? h("div", { class: "tiny muted" }, "precision: " + e.precision) : null),
          h("td", { class: "num" }, fmtD(e.announce_date), h("div", { class: "tiny muted" }, e.vintage)), h("td", {}, e.type),
          h("td", {}, e.company || "industry-wide", e.location ? h("div", { class: "tiny muted" }, e.location) : null),
          h("td", { class: "num" }, e.capacity_t ? fmtN(e.capacity_t) + " t/yr" : "—"), h("td", { class: e.direction < 0 ? "down" : "up" }, e.direction < 0 ? "▼ cut" : "▲ add"),
          h("td", { class: "num" }, e.severity), h("td", { class: "small ink2", style: { maxWidth: "380px" } }, e.raw_text || "", e.note ? h("div", { class: "tiny muted" }, e.note) : null),
          h("td", {}, kind(e.kind), " ", ext(e.url, "↗")))));
    };
    [fType, fCo, fSev].forEach((x) => x.addEventListener("change", draw)); q.addEventListener("input", draw); draw();
  }

  async function pageSupply(main) {
    const [S, ser] = await Promise.all([D("supply"), D("series")]);
    main.appendChild(h("div", { class: "section-title", style: { marginTop: 0 } }, h("div", {}, h("div", { class: "kicker" }, "H-Acid"), h("h1", {}, "Supply"))));
    main.appendChild(h("p", { class: "warn" }, S.note));
    main.appendChild(h("div", { class: "card table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Producer", "Location", "Nominal capacity", "Basis", "Status", "As of", "Note", "Source"].map((x) => h("th", {}, x)))),
      h("tbody", {}, S.producers.map((p) => h("tr", {}, h("td", {}, p.company, p.plant ? h("div", { class: "tiny muted" }, p.plant) : null), h("td", {}, p.location),
        h("td", { class: "num" }, p.nominal_capacity_t ? fmtN(p.nominal_capacity_t) + " t/yr" : h("span", { class: "muted" }, "not verified")), h("td", { class: "small" }, p.capacity_basis),
        h("td", {}, statusDot(p.status, { operating: "var(--good)", trial: "var(--warning)", reduced: "var(--warning)", disrupted: "var(--serious)", shutdown: "var(--critical)" }[p.status])),
        h("td", { class: "num" }, fmtD(p.status_as_of)), h("td", { class: "small ink2", style: { maxWidth: "360px" } }, p.note), h("td", {}, ext(p.url, "↗"))))))));
    main.appendChild(h("p", { class: "small muted" }, `Known nominal capacity in registry: ${fmtN(S.known_nominal_t)} t/yr (capacity figures are company / broker statements, not audited).`));
    const g = h("div", { class: "grid g2" }); main.appendChild(g);
    smallChart(g, "Available share of known capacity", ["derived.supply_index"], ser, { badge: kind("estimated"), yFormat: (v) => Math.round(v * 100) + "%", maxGap: 2000 });
    smallChart(g, "Available known capacity (t/yr)", ["derived.eff_supply"], ser, { badge: kind("estimated"), maxGap: 2000 });
    main.appendChild(h("div", { class: "section-title" }, h("h2", {}, "Capacity status timeline")));
    main.appendChild(h("div", { class: "card table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Producer", "Effective", "Known publicly", "Nominal", "Availability", "Status", "Kind", "Note"].map((x) => h("th", {}, x)))),
      h("tbody", {}, S.capacity_timeline.map((c) => h("tr", {}, h("td", {}, c.producer), h("td", { class: "num" }, fmtD(c.eff_date)), h("td", { class: "num" }, fmtD(c.published_at)), h("td", { class: "num" }, fmtN(c.nominal_t)),
        h("td", { class: "num" }, c.availability === null ? "—" : Math.round(c.availability * 100) + "%"), h("td", {}, c.status), h("td", {}, kind(c.value_kind)), h("td", { class: "small ink2" }, c.note, " ", ext(c.url, "↗"))))))));
  }

  async function pageQuality(main) {
    const [S, src] = await Promise.all([D("summary"), load("data/sources.json")]);
    const Q = S.quality;
    main.appendChild(h("div", { class: "section-title", style: { marginTop: 0 } }, h("div", {}, h("div", { class: "kicker" }, "H-Acid"), h("h1", {}, "Data quality")), h("div", { class: "score" }, Math.round(Q.overall * 100) + "%")));
    main.appendChild(h("p", { class: "lede" }, `Coverage = share of business days in the trailing ${Q.window_days} days (to ${fmtD(Q.window_end)}) on which a usable value exists. A low-quality dataset lowers evidence confidence and can cap the state at WATCH.`));
    main.appendChild(h("div", { class: "card table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Group", "Coverage", "Point-in-time", "Confirmed vintage", "Families / producers", "Records", "Weight"].map((x) => h("th", {}, x)))),
      h("tbody", {}, Q.groups.map((g) => h("tr", {}, h("td", {}, g.group), h("td", { class: "num" }, Math.round(g.coverage * 100) + "%"),
        h("td", { class: "num" }, g.pit_coverage === null ? "n/a" : Math.round(g.pit_coverage * 100) + "%"), h("td", { class: "num" }, g.pit_confirmed === null ? "n/a" : Math.round(g.pit_confirmed * 100) + "%"),
        h("td", { class: "num" }, g.independent_families), h("td", { class: "num" }, g.n_records), h("td", { class: "num" }, Math.round(g.weight * 100) + "%")))))));
    main.appendChild(h("div", { class: "grid g4", style: { marginTop: "16px" } }, [["Point-in-time", Q.overall_pit_coverage], ["Confirmed vintage", Q.confirmed_share], ["Estimated vintage", Q.estimated_share], ["Unknown vintage", Q.unknown_share]].map(([k, v]) =>
      h("div", { class: "card" }, h("div", { class: "kicker" }, k), h("div", { class: "score" }, Math.round(v * 100) + "%")))));
    main.appendChild(h("p", { class: "small muted" }, `${Q.independent_families} independent source families overall; ${Q.price_families} for the H-Acid price itself. Websites that republish the same original count as one family.`));
    main.appendChild(h("div", { class: "section-title" }, h("h2", {}, "Collector status")));
    main.appendChild(h("div", { class: "card table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Source", "Status", "Last success", "Last attempt", "Last observation", "Rows", "Vintage mix", "Failure reason"].map((x) => h("th", {}, x)))),
      h("tbody", {}, src.map((s) => h("tr", {}, h("td", {}, s.name), h("td", {}, statusDot(s.collector_status, { ok: "var(--good)", partial: "var(--warning)", stale: "var(--warning)", failed: "var(--critical)", curated: "var(--s1)" }[s.collector_status] || "var(--muted)")),
        h("td", { class: "small" }, s.last_success || "—"), h("td", { class: "small" }, s.last_attempt || "—"), h("td", { class: "num" }, fmtD(s.last_observation_date)), h("td", { class: "num" }, s.rows),
        h("td", { class: "small" }, Object.entries(s.vintage || {}).map(([k, v]) => `${k} ${v}`).join(" · ") || "—"), h("td", { class: "small down" }, s.failure_reason || "")))))));
  }

  async function pageSources(main) {
    const src = await load("data/sources.json");
    main.appendChild(h("div", { class: "section-title", style: { marginTop: 0 } }, h("div", {}, h("div", { class: "kicker" }, "Registry"), h("h1", {}, "Sources"))));
    main.appendChild(h("p", { class: "lede" }, "Every source considered, including the ones we cannot or will not use, and why. Tier 1 = official/primary, 5 = discovery only (zero weight). No paywall, login or anti-bot control is ever circumvented."));
    main.appendChild(h("div", { class: "card table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Source", "Family", "Tier", "Data", "Frequency", "Coverage", "Reliability", "Access", "Status", "Last update"].map((x) => h("th", {}, x)))),
      h("tbody", {}, src.map((s) => h("tr", {}, h("td", {}, s.url && s.url.startsWith("http") ? ext(s.url, s.name) : s.name, h("div", { class: "tiny muted", style: { maxWidth: "340px" } }, s.notes)), h("td", {}, s.family), h("td", { class: "num" }, s.tier),
        h("td", { class: "small" }, s.series), h("td", { class: "small" }, s.frequency), h("td", { class: "small" }, s.coverage), h("td", { class: "small" }, s.reliability), h("td", { class: "small" }, s.access),
        h("td", {}, statusDot(s.registry_status, s.registry_status && s.registry_status.startsWith("active") ? "var(--good)" : "var(--muted)")), h("td", { class: "num small" }, fmtD(s.last_observation_date))))))));
  }

  function pageMethodology(main) {
    const tpl = document.getElementById("tpl-methodology");
    main.appendChild(tpl.content.cloneNode(true));
  }
  function pageAbout(main) {
    const tpl = document.getElementById("tpl-about");
    main.appendChild(tpl.content.cloneNode(true));
  }

  // ---------------------------------------------------------------- router
  const routes = [[/^#?\/?$/, pageDashboard], [/^#\/h-acid$/, pageDetail], [/^#\/history$/, pageHistory], [/^#\/inflection\/(\w+)$/, pageInflection],
    [/^#\/events$/, pageEvents], [/^#\/supply$/, pageSupply], [/^#\/quality$/, pageQuality], [/^#\/sources$/, pageSources],
    [/^#\/methodology$/, pageMethodology], [/^#\/about$/, pageAbout]];
  async function route() {
    const hash = location.hash || "#/";
    const main = document.getElementById("main");
    main.textContent = "";
    document.querySelectorAll("nav.main a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === hash || (hash.startsWith("#/inflection") && a.getAttribute("href") === "#/history")));
    for (const [re, fn] of routes) {
      const m = hash.match(re);
      if (m) {
        main.appendChild(h("div", { class: "skeleton" }, "Loading…"));
        try { const tmp = h("div", {}); main.textContent = ""; main.appendChild(tmp); await fn(tmp, m[1]); }
        catch (e) { main.textContent = ""; main.appendChild(h("div", { class: "warn" }, "Could not load data: " + e.message)); console.error(e); }
        window.scrollTo(0, 0);
        return;
      }
    }
    main.appendChild(h("p", {}, "Page not found. ", link("#/", "Dashboard")));
  }
  shell();
  window.addEventListener("hashchange", route);
  route();
})();
