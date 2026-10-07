/* Dependency-free time-series chart. One y-axis per chart (never dual-axis).
   Prices are drawn as step lines (a quote stands until the next observation); a gap longer than a
   series' maxGapDays is drawn dashed so unobserved stretches are never mistaken for data.
   All labels use textContent (data is untrusted). */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const DAY = 86400000;
  const RANGES = { "1M": 31, "3M": 92, "6M": 183, "1Y": 366, "3Y": 1096, "MAX": null };

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  const t = (s) => Date.parse(s + "T00:00:00Z");
  const fmtDate = (ms, opt) => new Date(ms).toLocaleDateString("en-GB", Object.assign({ timeZone: "UTC", day: "numeric", month: "short", year: "numeric" }, opt || {}));

  function niceTicks(lo, hi, n) {
    if (!(hi > lo)) { hi = lo + 1; }
    const span = hi - lo, step0 = span / Math.max(1, n);
    const mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0) || 10 * mag;
    const out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9 && out.length < 50; v += step) out.push(+v.toFixed(10));
    return out;
  }
  function timeTicks(a, b, width) {
    const days = (b - a) / DAY, want = Math.max(2, Math.floor(width / 80));
    const out = [];
    const d = new Date(a);
    let stepM = days < 100 ? 0 : [1, 2, 3, 6, 12, 24].find((k) => days / 30.4 / k <= want) || 24;
    if (stepM) {
      d.setUTCDate(1); d.setUTCMonth(Math.ceil(d.getUTCMonth() / stepM) * stepM);
      while (d.getTime() <= b) { if (d.getTime() >= a) out.push(d.getTime()); d.setUTCMonth(d.getUTCMonth() + stepM); }
    } else {
      const step = Math.max(1, Math.round(days / want));
      for (let x = a; x <= b; x += step * DAY) out.push(x);
    }
    return { ticks: out, fmt: (ms) => stepM ? fmtDate(ms, { day: undefined, year: stepM >= 3 || new Date(ms).getUTCMonth() === 0 ? "2-digit" : undefined }) : fmtDate(ms, { year: undefined }) };
  }

  class TSChart {
    constructor(root, opts) {
      this.root = root; this.o = Object.assign({ height: 300, range: "MAX", yFormat: (v) => v.toLocaleString("en-US"), step: true }, opts);
      this.series = (opts.series || []).map((s) => Object.assign({ visible: s.visible !== false, maxGapDays: 60 }, s, {
        pts: s.points.map((p) => [t(p[0]), p[1]]).sort((x, y) => x[0] - y[0]) }));
      this.zoom = null; this.range = this.o.range;
      root.classList.add("chart");
      this.svg = el("svg", { role: "img", "aria-label": opts.ariaLabel || "time series chart" }, root);
      this.tip = document.createElement("div"); this.tip.className = "tooltip"; root.appendChild(this.tip);
      this.ro = new ResizeObserver(() => this.render()); this.ro.observe(root);
      this.bind();
    }
    extent() {
      let lo = Infinity, hi = -Infinity;
      for (const s of this.series) if (s.pts.length) { lo = Math.min(lo, s.pts[0][0]); hi = Math.max(hi, s.pts[s.pts.length - 1][0]); }
      if (this.o.xMax) hi = Math.max(hi, t(this.o.xMax));
      return [lo, hi];
    }
    domainX() {
      if (this.zoom) return this.zoom;
      const [lo, hi] = this.extent();
      const span = RANGES[this.range];
      return [span ? Math.max(lo, hi - span * DAY) : lo, hi];
    }
    setRange(r) { this.range = r; this.zoom = null; this.render(); }
    setVisible(id, v) { const s = this.series.find((x) => x.id === id); if (s) { s.visible = v; this.render(); } }
    valueAt(s, x) {
      let lo = 0, hi = s.pts.length - 1, ans = -1;
      while (lo <= hi) { const m = (lo + hi) >> 1; if (s.pts[m][0] <= x) { ans = m; lo = m + 1; } else hi = m - 1; }
      if (ans < 0) return null;
      const p = s.pts[ans];
      return (x - p[0]) / DAY > s.maxGapDays ? null : p;
    }
    render() {
      const W = this.root.clientWidth || 600, H = this.o.height;
      const m = { l: 56, r: 14, t: 18, b: 26 };
      this.svg.setAttribute("viewBox", `0 0 ${W} ${H}`); this.svg.setAttribute("height", H);
      while (this.svg.firstChild) this.svg.removeChild(this.svg.firstChild);
      const [x0, x1] = this.domainX();
      const vis = this.series.filter((s) => s.visible && s.pts.length);
      let ylo = Infinity, yhi = -Infinity;
      for (const s of vis) {
        const before = this.valueAt(s, x0);
        if (before) { ylo = Math.min(ylo, before[1]); yhi = Math.max(yhi, before[1]); }
        for (const p of s.pts) if (p[0] >= x0 && p[0] <= x1) { ylo = Math.min(ylo, p[1]); yhi = Math.max(yhi, p[1]); }
      }
      if (this.o.yZero) ylo = Math.min(0, ylo);
      if (!isFinite(ylo)) { ylo = 0; yhi = 1; }
      const flat = (yhi - ylo) <= 1e-9 * Math.max(1, Math.abs(yhi));
      const pad = flat ? (Math.abs(yhi) * 0.05 || 1) : (yhi - ylo) * 0.08;
      ylo -= pad; yhi += pad;
      const yt = niceTicks(ylo, yhi, 4);
      const X = (v) => m.l + (v - x0) / Math.max(1, x1 - x0) * (W - m.l - m.r);
      const Y = (v) => m.t + (1 - (v - ylo) / (yhi - ylo)) * (H - m.t - m.b);
      this.geo = { X, Y, x0, x1, m, W, H };
      const g = el("g", {}, this.svg);
      for (const v of yt) {
        if (Y(v) < m.t - 1 || Y(v) > H - m.b + 1) continue;
        el("line", { class: "gridline", x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v) }, g);
        const tx = el("text", { x: m.l - 8, y: Y(v) + 4, "text-anchor": "end" }, g); tx.textContent = this.o.yFormat(v);
      }
      el("line", { class: "axis", x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b }, g);
      const tt = timeTicks(x0, x1, W - m.l - m.r);
      for (const v of tt.ticks) { const tx = el("text", { x: X(v), y: H - 8, "text-anchor": "middle" }, g); tx.textContent = tt.fmt(v); }
      // inflection bands
      for (const mk of this.o.markers || []) {
        const a = t(mk.start), b = t(mk.end);
        if (b < x0 || a > x1) continue;
        const xa = Math.max(m.l, X(a)), xb = Math.min(W - m.r, X(b));
        const r = el("rect", { class: "imark", x: xa, y: m.t, width: Math.max(3, xb - xa), height: H - m.t - m.b,
          fill: mk.direction === "up" ? "var(--band-up)" : "var(--band-down)" }, g);
        const lab = el("text", { class: "imark", x: xa + 3, y: m.t - 5 }, g); lab.textContent = mk.id;
        lab.setAttribute("style", "fill: var(--ink-2); font-weight: 600");
        const go = () => mk.onClick && mk.onClick(mk);
        r.addEventListener("click", go); lab.addEventListener("click", go);
        r.dataset.marker = mk.id;
      }
      // event ticks
      for (const ev of this.o.events || []) {
        const x = t(ev.date); if (x < x0 || x > x1) continue;
        el("line", { class: "marker-line", x1: X(x), x2: X(x), y1: H - m.b - 10, y2: H - m.b, stroke: "var(--ink-2)" }, g);
        el("circle", { cx: X(x), cy: H - m.b - 12, r: 3.5, fill: "var(--surface)", stroke: "var(--ink-2)", "stroke-width": 1.5 }, g);
      }
      // series
      const clip = el("clipPath", { id: "c" + (this._id = this._id || Math.random().toString(36).slice(2)) }, this.svg);
      el("rect", { x: m.l, y: 0, width: W - m.l - m.r, height: H }, clip);
      const sg = el("g", { "clip-path": `url(#c${this._id})` }, this.svg);
      for (const s of vis) {
        let solid = "", dashed = "";
        const pts = s.pts;
        for (let i = 0; i < pts.length; i++) {
          const [px, py] = pts[i];
          if (i === 0) { solid += `M${X(px)},${Y(py)}`; continue; }
          const [qx, qy] = pts[i - 1];
          const gap = (px - qx) / DAY > s.maxGapDays;
          const seg = (this.o.step && s.step !== false) ? `M${X(qx)},${Y(qy)}H${X(px)}V${Y(py)}` : `M${X(qx)},${Y(qy)}L${X(px)},${Y(py)}`;
          if (gap) dashed += seg; else solid += seg;
        }
        if (s.extendTo && pts.length) { const last = pts[pts.length - 1]; solid += `M${X(last[0])},${Y(last[1])}H${X(Math.min(t(s.extendTo), x1))}`; }
        el("path", { class: "series", d: solid, stroke: s.color }, sg);
        if (dashed) el("path", { class: "series gap", d: dashed, stroke: s.color }, sg);
        const inView = pts.filter((p) => p[0] >= x0 && p[0] <= x1);
        if (s.dots !== false && (s.showPoints || inView.length <= 160)) {
          for (const p of inView) el("circle", { class: "pt", cx: X(p[0]), cy: Y(p[1]), r: s.pointR || 3.5, fill: s.color }, sg);
        }
      }
      this.xh = el("line", { class: "xhair", y1: m.t, y2: H - m.b, x1: -10, x2: -10 }, this.svg);
      this.brushRect = el("rect", { class: "brush", y: m.t, height: H - m.t - m.b, x: 0, width: 0 }, this.svg);
      if (this.o.onRender) this.o.onRender(this);
    }
    bind() {
      let drag = null;
      const pos = (e) => { const r = this.svg.getBoundingClientRect(); return (e.clientX - r.left) * (this.geo.W / r.width); };
      const inv = (px) => { const { m, W, x0, x1 } = this.geo; return x0 + (px - m.l) / (W - m.l - m.r) * (x1 - x0); };
      this.svg.addEventListener("pointermove", (e) => {
        if (!this.geo) return;
        const px = pos(e), { m, W } = this.geo;
        if (drag !== null) { const a = Math.min(drag, px), b = Math.max(drag, px); this.brushRect.setAttribute("x", a); this.brushRect.setAttribute("width", b - a); }
        if (px < m.l || px > W - m.r) { this.hide(); return; }
        const x = inv(px);
        this.xh.setAttribute("x1", px); this.xh.setAttribute("x2", px);
        this.showTip(x, e);
      });
      this.svg.addEventListener("pointerleave", () => { this.hide(); });
      this.svg.addEventListener("pointerdown", (e) => { if (e.target.classList && e.target.classList.contains("imark")) return; drag = pos(e); });
      window.addEventListener("pointerup", (e) => {
        if (drag === null) return;
        const px = pos(e), a = Math.min(drag, px), b = Math.max(drag, px); drag = null;
        this.brushRect.setAttribute("width", 0);
        if (b - a > 12) { this.zoom = [inv(a), inv(b)]; this.render(); if (this.o.onZoom) this.o.onZoom(); }
      });
      this.svg.addEventListener("dblclick", () => { this.zoom = null; this.render(); });
    }
    hide() { this.tip.style.display = "none"; if (this.xh) { this.xh.setAttribute("x1", -10); this.xh.setAttribute("x2", -10); } }
    showTip(x, e) {
      const rows = [];
      for (const s of this.series) {
        if (!s.visible) continue;
        const p = this.valueAt(s, x);
        rows.push([s, p]);
      }
      const tip = this.tip; tip.textContent = "";
      const d = document.createElement("div"); d.className = "d"; d.textContent = fmtDate(x); tip.appendChild(d);
      for (const [s, p] of rows) {
        const r = document.createElement("div"); r.className = "row";
        const l = document.createElement("span"); const k = document.createElement("span"); k.className = "k"; k.style.background = s.color;
        l.appendChild(k); l.appendChild(document.createTextNode(s.label)); l.className = "ink2";
        const v = document.createElement("b");
        v.textContent = p ? this.o.yFormat(p[1]) : "—";
        r.appendChild(v); r.appendChild(l); tip.appendChild(r);
        if (p) { const o = document.createElement("div"); o.className = "tiny muted"; o.textContent = "observed " + fmtDate(p[0]); tip.appendChild(o); }
      }
      for (const ev of this.o.events || []) {
        if (Math.abs(t(ev.date) - x) < (this.geo.x1 - this.geo.x0) / 80) { const o = document.createElement("div"); o.className = "small"; o.style.marginTop = "4px"; o.textContent = "● " + ev.label; tip.appendChild(o); }
      }
      tip.style.display = "block";
      const r = this.root.getBoundingClientRect();
      let left = e.clientX - r.left + 14; if (left + tip.offsetWidth > r.width) left = e.clientX - r.left - tip.offsetWidth - 14;
      tip.style.left = Math.max(0, left) + "px"; tip.style.top = Math.max(0, e.clientY - r.top - 20) + "px";
    }
  }
  window.TSChart = TSChart; window.TSChart.RANGES = RANGES;
})();
