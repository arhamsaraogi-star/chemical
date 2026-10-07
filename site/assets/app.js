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
  const NAV = [["#/", "Overview"], ["#/price", "Price"], ["#/drivers", "Drivers"], ["#/events", "Events"],
    ["#/history", "History"], ["#/data", "Data"], ["#/methodology", "Methodology"]];
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
  // plain-language pieces shared by pages
  const EFFECT_COLOR = { "pushing price up": "var(--s2)", "pushing price down": "var(--s1)", "no clear push": "var(--muted)", "no data": "var(--axis)" };
  const STATE_PLAIN = {
    "NORMAL": "No — nothing unusual is building right now.",
    "WATCH": "Not yet — some pressure is building, worth watching.",
    "DEVELOPING INFLECTION": "Possibly — a price turn appears to be starting.",
    "STRONG INFLECTION": "Yes — a strong price turn is under way.",
    "MAJOR INFLECTION": "Yes — a major price turn is under way.",
  };
  function citation(P) {
    return h("div", { class: "cite" }, `${fmtD(P.date)} · Baiinfo market average · `, kind("observed"), " ",
      ext(P.url, "source ↗"), P.age_days > 3 ? h("span", { class: "muted" }, ` · ${P.age_days} days old`) : null);
  }
  function explainList(items) {
    return h("div", { class: "explain" }, items.map((e) => h("div", { class: "ex-row" },
      h("div", { class: "ex-head" }, h("b", {}, e.name), h("span", { class: "pill", style: { "--c": EFFECT_COLOR[e.effect] || "var(--muted)" } }, e.effect)),
      h("p", {}, e.sentence, " ", kind(e.kind)))));
  }
  function glossary() {
    const terms = [["Inflection", "A point where the price trend clearly changes - e.g. a flat price suddenly starts climbing fast."],
      ["Score (0–100)", "How unusual and broad today's pressure is. Below 25 = normal, 50+ = an inflection is likely developing."],
      ["Observed / Derived / Estimated", "Observed = printed by a source. Derived = simple maths on observed numbers. Estimated = relies on a stated assumption."],
      ["Point-in-time", "Past signals are re-checked using only what was public on that date - no hindsight."],
      ["Source family", "Websites copying the same original data count as one source, not many."]];
    return h("details", { class: "card glossary" }, h("summary", {}, "How to read this page (glossary)"),
      h("dl", { class: "kv" }, terms.map(([k, v]) => [h("dt", {}, k), h("dd", {}, v)])));
  }

  const TONE_COLOR = { up: "var(--serious)", down: "var(--s1)", flat: "var(--good)", none: "var(--axis)" };
  const CONF_WORD = { High: "High", Medium: "Moderate", Low: "Low" };
  const qualityWord = (q) => q >= 0.75 ? "Good" : q >= 0.5 ? "Fair" : "Limited";
  const COMPARE = [["hacid.quote", "Producer quotes"], ["feed.naphthalene_refined", "Refined naphthalene"], ["feed.nitric_acid", "Nitric acid"],
    ["feed.sulfuric_acid", "Sulfuric acid"], ["feed.caustic_soda", "Caustic soda"], ["dye.reactive", "Reactive dye"], ["derived.export_uv", "Export unit value"]];

  async function pageOverview(main) {
    const [S, ser, I, evs] = await Promise.all([D("summary"), D("series"), D("inflections"), D("events")]);
    const L = S.live || {}, P = S.price || {}, Q = S.quality || {};
    const today = S.generated_at ? S.generated_at.slice(0, 10) : null;
    const c20 = (S.changes || {})["20D"];
    const stColor = STATE_COLOR[L.state] || "var(--muted)";

    // 1. header
    const why = h("details", { class: "why-score" }, h("summary", {}, `Cycle score ${Math.round(L.score || 0)}`),
      h("div", { class: "why-bars" }, h("div", { class: "kicker" }, `Why ${Math.round(L.score || 0)}? (−1 lower price … +1 higher price)`),
        ["PRICE", "SUPPLY", "DEMAND", "COST", "INVENTORY", "DOWNSTREAM", "TRADE", "EVENTS"].filter((b) => (L.blocks || {})[b]).map((b) => {
          const v = L.blocks[b].value;
          const bar = h("div", { class: "diverge" });
          if (v !== null) { const w = Math.min(50, Math.abs(v) * 50); bar.appendChild(h("i", { style: { left: v >= 0 ? "50%" : (50 - w) + "%", width: w + "%", background: v >= 0 ? "var(--s2)" : "var(--s1)" } })); }
          return h("div", { class: "why-row" }, h("span", {}, b.charAt(0) + b.slice(1).toLowerCase()), bar, h("span", { class: "muted tiny" }, v === null ? "no data" : (v > 0 ? "+" : "") + v.toFixed(2)));
        }),
        h("div", { class: "tiny muted" }, "Related indicators share one vote per block. ", link("#/methodology", "How the score works"))));
    main.appendChild(h("section", { class: "ov-head" },
      h("div", { class: "ov-top" }, h("span", { class: "kicker" }, "H-ACID · CHINA"), h("span", { class: "kicker" }, fmtD(today))),
      h("div", { class: "ov-main" },
        h("div", {}, h("div", { class: "ov-price" }, fmtCNY(P.value), h("span", { class: "unit" }, " / tonne")),
          h("div", { class: "ov-sub" }, c20 ? h("b", { class: dirCls(c20.pct) }, pct(c20.pct) + " 20D") : h("span", { class: "muted" }, "20D n/a"),
            h("span", { class: "muted" }, ` · ${fmtD(P.date)} · Baiinfo market average · `), kind("observed"), " ", ext(P.url, "source ↗"))),
        h("div", { class: "ov-state" }, h("div", { class: "state-pill", style: { "--c": stColor } }, h("span", { class: "dot" }), L.state || "NO DATA"), why)),
      h("p", { class: "ov-sentence" }, S.headline || L.sentence || ""),
      h("a", { class: "dq-badge", href: "#/data" }, `Data quality: ${qualityWord(Q.overall || 0)} · ${Math.round((Q.overall || 0) * 100)}%`)));

    // 2. chart
    const chartCard = h("section", { class: "card ov-chart" });
    main.appendChild(chartCard);
    const seriesBase = [{ id: "hacid.spot", label: "H-Acid market price", color: COLORS[0], points: ser.series["hacid.spot"].points, maxGapDays: 75, extendTo: today }];
    const box = h("div", {});
    const ch = new TSChart(box, { series: seriesBase, height: Math.max(320, Math.min(520, Math.round(window.innerHeight * 0.48))), range: "MAX", xMax: today,
      markers: I.map((i) => ({ id: i.id, start: i.price_onset.best, end: i.end, direction: i.direction, onClick: () => { location.hash = "#/inflection/" + i.id; } })),
      events: evs.map((e) => ({ date: e.event_date, label: `${e.type}: ${e.company || "industry"}` })),
      yFormat: (v) => "¥" + fmtN(v / 1000) + "k", ariaLabel: "H-Acid price chart" });
    const seg = h("div", { class: "seg" });
    for (const r of ["1Y", "3Y", "MAX"]) {
      const b = h("button", { class: r === "MAX" ? "on" : "", onclick: () => { ch.setRange(r); [...seg.children].forEach((x) => x.classList.toggle("on", x === b)); } }, r);
      seg.appendChild(b);
    }
    const tog = (label, on, fn) => { const b = h("button", { class: "toggle plain", "aria-pressed": String(on) }, label); b.addEventListener("click", () => { const v = b.getAttribute("aria-pressed") !== "true"; b.setAttribute("aria-pressed", String(v)); fn(v); }); return b; };
    const legend = h("div", { class: "legend" });
    const drawLegend = () => { legend.textContent = ""; if (ch.series.length > 1) ch.series.forEach((s) => legend.appendChild(h("span", { style: { "--k": s.color } }, s.label))); };
    const cmpMenu = h("div", { class: "cmp-menu", hidden: true }, COMPARE.filter(([id]) => ser.series[id]).map(([id, label], k) => {
      const cb = h("input", { type: "checkbox", id: "cmp-" + k });
      cb.addEventListener("change", () => {
        if (cb.checked) ch.addSeries({ id, label, color: COLORS[1 + (k % 7)], points: ser.series[id].points, maxGapDays: 75, step: !id.startsWith("derived.export") });
        else ch.removeSeries(id);
        ch.setOption("indexed", ch.series.length > 1);
        note.hidden = ch.series.length < 2; drawLegend();
      });
      return h("label", {}, cb, " ", label);
    }));
    const cmpBtn = h("button", { class: "toggle plain", "aria-expanded": "false", onclick: () => { cmpMenu.hidden = !cmpMenu.hidden; cmpBtn.setAttribute("aria-expanded", String(!cmpMenu.hidden)); } }, "＋ Compare");
    const note = h("div", { class: "tiny muted", hidden: true }, "Comparing: every line = 100 on the first date all selected series have data, so different units share one axis.");
    chartCard.appendChild(h("div", { class: "chart-toolbar" }, seg,
      tog("Events", true, (v) => ch.setOption("showEvents", v)), tog("Inflections", true, (v) => ch.setOption("showMarkers", v)),
      h("div", { class: "cmp-wrap" }, cmpBtn, cmpMenu)));
    chartCard.appendChild(box); chartCard.appendChild(legend); chartCard.appendChild(note);
    chartCard.appendChild(h("div", { class: "src-line" }, "Dots are real, cited prices; dashed = no public price for over 2½ months; shaded = detected price surges (click one). ", link("#/price", "Price detail →")));

    // 3. drivers: four tiles, one reason each
    const ev = Object.fromEntries((S.evidence || []).map((e) => [e.block, e]));
    main.appendChild(h("section", { class: "tiles4" }, (S.tiles || []).map((t) => h("a", { class: "tile4", href: "#/drivers" },
      h("div", { class: "muted small" }, t.label),
      h("div", { class: "tile-word" }, h("span", { class: "dot", style: { background: TONE_COLOR[t.tone] } }), t.word),
      h("div", { class: "tiny muted" }, (ev[t.block] || {}).short || "")))));
    main.appendChild(h("div", { class: "tiny muted", style: { margin: "6px 0 18px" } },
      `Orange = pushes price up · blue = down · green = stable · grey = not enough data. Confidence: ${CONF_WORD[L.evidence_confidence] || "—"}.`));

    // 4. past surges
    const an = L.analogue || {};
    main.appendChild(h("section", { class: "card" }, h("div", { class: "kicker" }, an.id ? `Most like ${an.id} (${an.similarity}% similar)` : "Past price surges · no strong match to today"),
      h("table", { class: "past" }, h("tbody", {}, I.slice().reverse().map((f) => h("tr", { class: "click", onclick: () => { location.hash = "#/inflection/" + f.id; } },
        h("td", {}, new Date(f.price_onset.best + "T00:00:00Z").toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" })),
        h("td", {}, (f.story || {}).diagnosis ? f.story.diagnosis.split(";")[0].split(",")[0].replace(/\.$/, "") : f.driver.type),
        h("td", { class: "num " + (f.direction === "up" ? "up" : "down") }, pct(f.magnitude, 0)), h("td", { class: "num" }, "→")))))));
  }

  async function pagePrice(main) {
    const [S, sum] = await Promise.all([D("series"), D("summary")]);
    main.appendChild(h("div", { class: "section-title", style: { marginTop: 0 } }, h("div", {}, h("div", { class: "kicker" }, "H-Acid · China"), h("h1", {}, "Price"))));
    const pc = h("section", { class: "card" }, h("h2", {}, "Market price & producer quotes (¥/t)"));
    main.appendChild(pc);
    priceChart(pc, S, { quotes: true, today: sum.generated_at.slice(0, 10) });
    pc.appendChild(sourceLine(S.series["hacid.spot"] || {}));
    if (S.series["hacid.quote"]) pc.appendChild(sourceLine(S.series["hacid.quote"], h("span", {}, "Producer quotes = ex-works quotations or the midpoint of a stated ex-works range")));
    const chg = sum.changes || {};
    main.appendChild(h("div", { class: "grid g4", style: { marginTop: "16px" } }, ["1D", "5D", "20D", "60D", "1Y"].slice(0, 4).map((k) =>
      h("div", { class: "card" }, h("div", { class: "kicker" }, k + " change"), h("div", { class: "score " + (chg[k] ? dirCls(chg[k].pct) : "muted") }, chg[k] ? pct(chg[k].pct) : "n/a"),
        h("div", { class: "tiny muted" }, chg[k] ? `vs ${fmtD(chg[k].from_date)}` : "no observation near the comparison date")))));
    const scard = h("details", { class: "card", style: { marginTop: "16px" } }, h("summary", {}, "Point-in-time cycle score history"));
    main.appendChild(scard);
    const ok = (S.score || []).filter((r) => r.status === "ok").map((r) => [r.d, r.score]);
    const weak = (S.score || []).filter((r) => r.status !== "ok").map((r) => [r.d, r.score]);
    const ss = [];
    if (ok.length) ss.push({ id: "ok", label: "Score (alert-grade)", color: COLORS[6], points: ok, step: false, dots: false, maxGapDays: 4 });
    if (weak.length) ss.push({ id: "weak", label: "Raw score, insufficient evidence (capped at WATCH)", color: "var(--axis)", points: weak, step: false, dots: false, maxGapDays: 4 });
    scard.addEventListener("toggle", () => { if (scard.open && !scard.dataset.done && ss.length) { scard.dataset.done = 1; const b = h("div", {}); scard.appendChild(b); new TSChart(b, { series: ss, height: 220, yFormat: (v) => fmtN(v) }); scard.appendChild(h("div", { class: "legend" }, ss.map((x) => h("span", { style: { "--k": x.color } }, x.label)))); } });
    const rows = [];
    for (const [fam, list] of Object.entries(S.by_family || {})) for (const r of list) rows.push(Object.assign({ fam }, r));
    rows.sort((a, b) => b.d.localeCompare(a.d));
    main.appendChild(h("details", { class: "card", style: { marginTop: "16px" } }, h("summary", {}, `Every H-Acid price observation (${rows.length}) — source, publication date and original sentence`),
      h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Date", "Value", "Kind", "Family", "Published", "Vintage", "Via", "Evidence"].map((x) => h("th", { class: x === "Value" ? "num" : "" }, x)))),
        h("tbody", {}, rows.map((r) => h("tr", {}, h("td", { class: "num" }, fmtD(r.d), r.precision && r.precision !== "day" ? h("div", { class: "tiny muted" }, r.precision) : null), h("td", { class: "num" }, fmtCNY(r.v)), h("td", {}, kind(r.kind)), h("td", {}, r.fam),
          h("td", { class: "num" }, fmtD(r.pub)), h("td", {}, r.vintage), h("td", { class: "small" }, r.via || r.src, " ", ext(r.url, "↗")), h("td", { class: "small ink2", style: { maxWidth: "420px" } }, r.text || ""))))))));
  }

  async function pageDrivers(main) {
    const [ser, sum] = await Promise.all([D("series"), D("summary")]);
    main.appendChild(h("div", { class: "section-title", style: { marginTop: 0 } }, h("div", {}, h("div", { class: "kicker" }, "H-Acid · China"), h("h1", {}, "Drivers"))));
    main.appendChild(h("section", { class: "card" }, explainList(sum.explain || [])));
    const g = h("div", { class: "grid g2", style: { marginTop: "16px" } }); main.appendChild(g);
    smallChart(g, "Feedstocks (indexed)", ["feed.naphthalene_refined", "feed.naphthalene_industrial", "feed.sulfuric_acid", "feed.nitric_acid", "feed.caustic_soda"], ser, { indexed: true, badge: kind("observed") });
    smallChart(g, "Feedstock price index", ["derived.cost_idx"], ser, { badge: kind("derived"), colorOffset: 6 });
    smallChart(g, "Reactive dyes (¥/t)", ["dye.reactive", "dye.reactive_black_sci99"], ser, { badge: kind("observed"), maxGap: 400, colorOffset: 2 });
    smallChart(g, "Export / import unit value (USD/t, HS 292221)", ["derived.export_uv", "derived.export_uv_china"], ser, { badge: kind("derived"), step: false, maxGap: 70 });
    smallChart(g, "Imports from China reported by destinations (t/month)", ["mirror.ind.hacid.qty", "mirror.kor.hacid.qty", "mirror.idn.hacid.qty", "export.hacid.qty"], ser, { badge: kind("observed"), step: false, maxGap: 70 });
    smallChart(g, "Supply — available share of known capacity", ["derived.supply_index"], ser, { badge: kind("estimated"), yFormat: (v) => Math.round(v * 100) + "%", maxGap: 2000 });
    const sup = h("div", {}); main.appendChild(h("details", { class: "card", style: { marginTop: "16px" } }, h("summary", {}, "Producers and capacity"), sup));
    await pageSupplyInto(sup);
  }

  async function pageData(main) {
    const q = h("div", {}), s = h("div", {});
    await pageQuality(q); await pageSources(s);
    main.appendChild(q); main.appendChild(h("div", { style: { height: "24px" } })); main.appendChild(s);
  }

  async function pageHistory(main) {
    const [X, I] = await Promise.all([D("stats"), D("inflections")]);
    main.appendChild(h("div", { class: "section-title", style: { marginTop: 0 } }, h("div", {}, h("div", { class: "kicker" }, "H-Acid"), h("h1", {}, "History & inflections")), sampleNote(X.n_inflections, X.sample_label)));
    main.appendChild(h("p", { class: "lede" }, "Each card is a period when the H-Acid price clearly changed direction or speed. Click one for the full story. (Technical note: moves are found on the timeline of when prices actually moved; early-warning detection is tested using only data that was public at the time.)"));
    main.appendChild(h("div", { class: "grid g3", style: { marginBottom: "16px" } }, I.slice().reverse().map((f) => h("a", { class: "card story-card", href: "#/inflection/" + f.id },
      h("div", { class: "kicker" }, `${f.id} · ${fmtD(f.price_onset.best)}`),
      h("div", { class: "score " + (f.direction === "up" ? "up" : "down") }, (f.direction === "up" ? "▲ +" : "▼ ") + Math.round(Math.abs(f.magnitude) * 100) + "%"),
      h("div", { class: "small" }, `${fmtCNY(f.start_price)} → ${fmtCNY(f.end_price)}`),
      h("p", { class: "small ink2" }, (f.story || {}).diagnosis || "")))));
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
    else {
      const ser = await D("series");
      const lab = (v) => (ser.series[v] || {}).label || v;
      const best = {};
      for (const r of hr) if (!best[r.variable] || (r.lift || 0) > (best[r.variable].lift || 0)) best[r.variable] = r;
      const top = Object.values(best).filter((r) => r.hits > 0).sort((x, y) => (y.lift || 0) - (x.lift || 0));
      const table = (rows) => h("table", {}, h("thead", {}, h("tr", {}, ["Indicator", "Looked back", "Moves preceded", "Normal chance", "Lift", "Sample"].map((x) => h("th", {}, x)))),
        h("tbody", {}, rows.map((r) => h("tr", {}, h("td", {}, lab(r.variable)), h("td", { class: "num" }, r.lead_days + " days"), h("td", { class: "num" }, `${r.hits} of ${r.n_inflections}`),
          h("td", { class: "num" }, pct(r.base_rate, 0).replace("+", "")), h("td", { class: "num" }, fmtN(r.lift, 1) + "×"), h("td", {}, h("span", { class: "tag" }, r.sample_label))))));
      main.appendChild(h("p", { class: "small ink2" }, top.length ? `Only ${top.length} indicator(s) moved before any of the ${X.n_inflections} price surges, and none before more than one. With so few surges this is a lead to investigate, not proof.` : "No indicator moved before any surge."));
      if (top.length) main.appendChild(h("div", { class: "card table-wrap" }, table(top)));
      main.appendChild(h("details", { class: "card", style: { marginTop: "12px" } }, h("summary", {}, `Show all ${hr.length} indicator × look-back combinations`), h("div", { class: "table-wrap" }, table(hr))));
    }
  }

  async function pageInflection(main, id) {
    const [I, ser, evs, sum] = await Promise.all([D("inflections"), D("series"), D("events"), D("summary")]);
    const f = I.find((x) => x.id === id);
    if (!f) { main.appendChild(h("p", {}, "Unknown inflection ", id, ". ", link("#/history", "Back to history"))); return; }
    const up = f.direction === "up";
    main.appendChild(h("div", { class: "section-title", style: { marginTop: 0 } }, h("div", {}, h("div", { class: "kicker" }, link("#/history", "History"), " / " + f.id),
      h("h1", {}, `${f.id} — Price ${up ? "surge" : "drop"} from ${fmtD(f.price_onset.best)}: ${pct(f.magnitude, 0)}`)), h("span", { class: "tag" }, "Confidence: " + f.confidence)));
    const po = f.price_onset, fo = f.fundamental_onset;
    const st = f.story || { summary: "", diagnosis: "", press: [] };
    const ba = f.before_after || [];
    const wordCls = (w) => w.indexOf("higher") > 0 ? "up" : w.indexOf("lower") > 0 ? "down" : "muted";
    main.appendChild(h("section", { class: "card hero" },
      h("p", { class: "story big" }, st.summary),
      h("p", {}, h("b", {}, "Diagnosis: "), st.diagnosis, " ", kind("inferred")),
      h("div", { class: "grid g2", style: { marginTop: "8px" } },
        h("div", {}, h("div", { class: "kicker", style: { marginBottom: "6px" } }, "What each factor implied for the price (30 days before vs during the move)"),
          h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Factor"), h("th", {}, "Before"), h("th", {}, "During"))),
            h("tbody", {}, ba.map((r) => h("tr", {}, h("td", {}, r.name), h("td", { class: wordCls(r.before_word) }, r.before_word), h("td", { class: wordCls(r.during_word) }, r.during_word)))))),
        h("div", {}, h("div", { class: "kicker", style: { marginBottom: "6px" } }, "What industry press reported (dated, cited)"),
          st.press.length ? h("ul", { class: "press" }, st.press.map((n) => h("li", {}, h("span", { class: "muted small" }, fmtD(n.pub_date) + " · " + n.source + " "), ext(n.url, "↗"), h("div", {}, n.summary_en))))
            : h("p", { class: "muted small" }, "No press context recorded for this window.")))));
    main.appendChild(h("div", { class: "section-title" }, h("h2", {}, "The details"), h("span", { class: "small muted" }, "dates, detection and evidence")));
    const kv = (k, v, kd) => [h("dt", {}, k), h("dd", {}, v, kd ? [" ", kind(kd)] : null)];
    const facts = h("section", { class: "card" }, h("dl", { class: "kv", style: { marginTop: 0 } },
      kv("Fundamental onset", !fo.date ? fo.evidence : fo.weak ? `Not identified (nearest event: ${fo.evidence}, ${fo.days_before_onset} days earlier)` : `${fmtD(fo.date)}${fo.earliest && fo.earliest !== fo.latest ? ` (window ${fmtD(fo.earliest)} – ${fmtD(fo.latest)})` : ""} · ${fo.evidence}`, "inferred"),
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

  async function pageSupply(main) { return pageSupplyInto(main); }
  async function pageSupplyInto(main) {
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
  const routes = [[/^#?\/?$/, pageOverview], [/^#\/price$/, pagePrice], [/^#\/h-acid$/, pagePrice], [/^#\/drivers$/, pageDrivers], [/^#\/data$/, pageData], [/^#\/history$/, pageHistory], [/^#\/inflection\/(\w+)$/, pageInflection],
    [/^#\/events$/, pageEvents], [/^#\/supply$/, pageSupply], [/^#\/quality$/, pageQuality], [/^#\/sources$/, pageSources],
    [/^#\/methodology$/, pageMethodology], [/^#\/about$/, pageAbout]];
  async function route() {
    const hash = location.hash || "#/";
    const main = document.getElementById("main");
    main.textContent = "";
    const alias = { "#/h-acid": "#/price", "#/supply": "#/drivers", "#/quality": "#/data", "#/sources": "#/data", "#/about": "#/methodology" };
    document.querySelectorAll("nav.main a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === (alias[hash] || hash) || (hash.startsWith("#/inflection") && a.getAttribute("href") === "#/history")));
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
