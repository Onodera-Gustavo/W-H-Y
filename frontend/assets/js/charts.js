// Small chart helpers, hand-written SVG and HTML. No colors live here: every mark gets a class
// (is-positive, series-finbert, ...) and why.css paints it from tokens, so charts follow the theme.

import { LABELS, esc, fmtDate, fmtInt, labelFor, signed } from "./common.js";

const round = (v) => Math.round(v * 10) / 10;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const isNum = (v) => typeof v === "number" && Number.isFinite(v);

/** CSS class that carries a model's identity color: series-finbert, series-vader or series-other. */
export const seriesClass = (id) => `series-${id === "finbert" || id === "vader" ? id : "other"}`;

/** Smallest symmetric domain, in steps, that holds every value: 0.18 -> 0.25, 0.4 -> 0.5. */
export function symmetricDomain(values, min = 0.25, step = 0.25) {
  const max = Math.max(0, ...values.filter(isNum).map(Math.abs));
  return Math.max(min, Math.ceil(max / step - 1e-9) * step);
}

/** Split a series into runs of consecutive days that have values. */
function runsOf(values, x, y) {
  const runs = [];
  let run = [];
  values.forEach((v, i) => {
    if (!isNum(v)) {
      if (run.length) runs.push(run);
      run = [];
    } else {
      run.push([round(x(i)), round(y(v)), i]);
    }
  });
  if (run.length) runs.push(run);
  return runs;
}

/**
 * Sparkline as an SVG string. values: (number|null)[] from -1 to +1, oldest first.
 * The line is drawn per run of known days, the last known value gets a tone-colored end dot.
 * options: width, height (viewBox units, the SVG scales to its box), domain, label (adds role=img).
 */
export function sparkline(values = [], { width = 160, height = 36, domain, label = "", className = "" } = {}) {
  const pad = 4;
  const n = values.length;
  const d = domain ?? symmetricDomain(values, 0.25);
  const x = (i) => pad + (n > 1 ? (i * (width - 2 * pad)) / (n - 1) : (width - 2 * pad) / 2);
  const y = (v) => height / 2 - (clamp(v, -d, d) / d) * (height / 2 - pad);
  const runs = runsOf(values, x, y);
  // one tick per day on the zero line, so an empty history still reads as a 14 day window
  const ticks = values.map((_, i) => `<line class="spark-tick" x1="${round(x(i))}" x2="${round(x(i))}" y1="${height / 2 - 2}" y2="${height / 2 + 2}"/>`).join("");
  const marks = runs.map((r) => (r.length > 1
    ? `<polyline class="spark-line" points="${r.map((p) => `${p[0]},${p[1]}`).join(" ")}"/>`
    : `<circle class="spark-point" cx="${r[0][0]}" cy="${r[0][1]}" r="2"/>`)).join("");
  let end = "";
  for (let i = n - 1; i >= 0; i--) {
    if (isNum(values[i])) {
      end = `<circle class="spark-end is-${labelFor(values[i])}" cx="${round(x(i))}" cy="${round(y(values[i]))}" r="4"/>`;
      break;
    }
  }
  const a11y = label ? `role="img" aria-label="${esc(label)}"` : 'aria-hidden="true" focusable="false"';
  return `<svg class="spark${runs.length ? "" : " is-empty"} ${esc(className)}" viewBox="0 0 ${width} ${height}" ${a11y}>`
    + `<line class="spark-zero" x1="0" x2="${width}" y1="${height / 2}" y2="${height / 2}"/>${ticks}${marks}${end}</svg>`;
}

/**
 * Diverging meter as an SVG string: a track, a center tick at 0 and a fill from the center
 * toward the score. value from -domain to +domain; null draws the empty track.
 * options.label overrides the tone (a model's own label can differ from the score cut points).
 */
export function divergingMeter(value, { width = 120, height = 6, domain = 1, label = null, className = "" } = {}) {
  const mid = width / 2;
  const v = value === null || value === undefined || value === "" ? NaN : Number(value);
  let fill = "";
  if (Number.isFinite(v)) {
    const w = Math.max(1.5, clamp(Math.abs(v) / domain, 0, 1) * mid);
    const tone = LABELS.includes(label) ? label : labelFor(v);
    fill = `<rect class="meter-fill is-${tone}" x="${round(v >= 0 ? mid : mid - w)}" y="0" width="${round(w)}" height="${height}"/>`;
  }
  return `<svg class="meter ${esc(className)}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true" focusable="false">`
    + `<rect class="meter-track" width="${width}" height="${height}" rx="1"/>${fill}`
    + `<line class="meter-mid" x1="${mid}" x2="${mid}" y1="-2" y2="${height + 2}"/></svg>`;
}

/**
 * Stacked positive / neutral / negative bar as an HTML string (flex segments with 2px gaps,
 * so it stays crisp at any width). counts: { positive, neutral, negative }.
 */
export function labelBar(counts = {}, { labels = LABELS, className = "" } = {}) {
  const total = labels.reduce((sum, l) => sum + (Number(counts[l]) || 0), 0);
  if (!total) return `<div class="labelbar is-empty ${esc(className)}" aria-hidden="true"></div>`;
  const text = labels.map((l) => `${Number(counts[l]) || 0} ${l}`).join(", ");
  const segs = labels.filter((l) => Number(counts[l]) > 0)
    .map((l) => `<span class="labelbar-seg is-${l}" style="flex-grow:${Number(counts[l])}"></span>`).join("");
  return `<div class="labelbar ${esc(className)}" role="img" aria-label="${esc(text)}">${segs}</div>`;
}

/** Visually hidden-by-default table twin of a trend chart, inside <details>. */
export function trendTable({ dates = [], series = [], counts = null } = {}, { caption = "Daily values", summary = "Show the numbers" } = {}) {
  const rows = dates.map((date, i) => ({ date, i }))
    .filter(({ i }) => (counts && counts[i] > 0) || series.some((s) => isNum(s.values[i])));
  if (!rows.length) return "";
  const head = `<tr><th scope="col">Day</th>${series.map((s) => `<th scope="col">${esc(s.name)}</th>`).join("")}`
    + `${counts ? '<th scope="col">Headlines</th>' : ""}</tr>`;
  const body = rows.map(({ date, i }) => `<tr><td>${esc(fmtDate(date, "short"))}</td>`
    + series.map((s) => `<td>${isNum(s.values[i]) ? esc(signed(s.values[i])) : ""}</td>`).join("")
    + `${counts ? `<td>${esc(fmtInt(counts[i]))}</td>` : ""}</tr>`).join("");
  return `<details class="data-details"><summary>${esc(summary)}</summary><div class="table-scroll">`
    + `<table class="data-table"><caption class="sr-only">${esc(caption)}</caption><thead>${head}</thead>`
    + `<tbody>${body}</tbody></table></div></details>`;
}

function node(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

/**
 * Interactive daily trend: one 2px line per model on a symmetric score axis, plus headline
 * counts as small columns in their own band underneath (no second axis on the same plot).
 * Crosshair and tooltip on pointer; arrow keys, Home and End on keyboard focus.
 *
 * container: element to render into (its content is replaced)
 * data: { dates: string[], series: [{ id, name, values: (number|null)[], n?: number[],
 *         mix?: ({positive, neutral, negative}|null)[] }], counts?: number[], label?: string,
 *         domain?: number (shared score axis for small multiples), plotHeight?: number }
 * series.mix adds the day's label counts to the tooltip.
 * returns { destroy() }
 */
export function trendChart(container, {
  dates = [], series = [], counts = null, label = "Daily sentiment", domain = null, plotHeight = 116,
} = {}) {
  if (!container) return { destroy() {} };
  const measure = () => Math.max(220, Math.round(container.clientWidth || 300));
  let W = measure();
  let unbind = draw();

  // the viewBox matches the rendered width, so tick labels keep their real size at any width
  const observer = typeof ResizeObserver === "function"
    ? new ResizeObserver(() => {
      const next = measure();
      if (Math.abs(next - W) > 1) {
        W = next;
        unbind();
        unbind = draw();
      }
    })
    : null;
  observer?.observe(container);

  return {
    destroy() {
      observer?.disconnect();
      unbind();
    },
  };

  function draw() {
    const padL = 40;
    const padR = 8;
    const top = 8;
    const plotH = plotHeight;
    const gap = 22;
    const countH = counts ? 30 : 0;
    const axisH = 24;
    const countTop = top + plotH + gap;
    const H = top + plotH + (counts ? gap + countH : 0) + axisH;
    const n = dates.length;
    const innerW = W - padL - padR;
    const step = n > 1 ? innerW / (n - 1) : 0;
    const d = domain ?? symmetricDomain(series.flatMap((s) => s.values), 0.25);
    const x = (i) => padL + (n > 1 ? i * step : innerW / 2);
    const y = (v) => top + plotH / 2 - (clamp(v, -d, d) / d) * (plotH / 2);
    const maxCount = Math.max(1, ...(counts || [0]));
    const colH = (c) => (c / maxCount) * countH;

    const grid = [d, 0, -d].map((v) => `<line class="${v === 0 ? "trend-zero" : "trend-grid"}" x1="${padL}" x2="${W - padR}" y1="${round(y(v))}" y2="${round(y(v))}"/>`
      + `<text class="trend-tick" x="${padL - 7}" y="${round(y(v)) + 4}" text-anchor="end">${v === 0 ? "0" : signed(v)}</text>`).join("");

    const lines = series.map((s) => {
      const runs = runsOf(s.values, x, y);
      const cls = seriesClass(s.id);
      const paths = runs.filter((r) => r.length > 1)
        .map((r) => `<polyline class="trend-line ${cls}" points="${r.map((p) => `${p[0]},${p[1]}`).join(" ")}"/>`).join("");
      const dots = runs.flat().map((p) => `<circle class="trend-dot ${cls}" data-i="${p[2]}" cx="${p[0]}" cy="${p[1]}" r="3.5"/>`).join("");
      return paths + dots;
    }).join("");

    let band = "";
    if (counts) {
      const bw = Math.max(3, Math.min(10, (n > 1 ? step : innerW) * 0.55));
      const base = countTop + countH;
      band = `<line class="trend-grid" x1="${padL}" x2="${W - padR}" y1="${base}" y2="${base}"/>`
        + `<text class="trend-tick" x="${padL - 7}" y="${countTop + 8}" text-anchor="end">${fmtInt(maxCount)}</text>`
        + counts.map((c, i) => (c > 0
          ? `<rect class="trend-count" data-i="${i}" x="${round(x(i) - bw / 2)}" y="${round(base - colH(c))}" width="${round(bw)}" height="${round(colH(c))}" rx="1"/>`
          : "")).join("");
    }

    const axisY = H - 6;
    const xLabels = n
      ? `<text class="trend-tick" x="${padL}" y="${axisY}" text-anchor="start">${esc(fmtDate(dates[0]))}</text>`
        + (n > 1 ? `<text class="trend-tick" x="${W - padR}" y="${axisY}" text-anchor="end">${esc(fmtDate(dates[n - 1]))}</text>` : "")
      : "";
    const crossBottom = counts ? countTop + countH : top + plotH;

    container.innerHTML = `
      <div class="trend-frame" tabindex="0" role="group" aria-label="${esc(label)}. Use the arrow keys to read each day.">
        <svg class="trend-svg" viewBox="0 0 ${W} ${H}" aria-hidden="true" focusable="false">
          ${grid}${band}
          <line class="trend-cross" x1="0" x2="0" y1="${top}" y2="${crossBottom}"/>
          ${lines}${xLabels}
          <rect class="trend-hit" x="0" y="0" width="${W}" height="${H}"/>
        </svg>
        <div class="trend-tip" aria-hidden="true"></div>
        <p class="sr-only" aria-live="polite"></p>
      </div>`;

    const frame = container.querySelector(".trend-frame");
    const svg = frame.querySelector("svg");
    const tip = frame.querySelector(".trend-tip");
    const live = frame.querySelector("[aria-live]");
    const cross = svg.querySelector(".trend-cross");
    let active = -1;

    const lastWithData = () => {
      for (let i = n - 1; i >= 0; i--) {
        if ((counts && counts[i] > 0) || series.some((s) => isNum(s.values[i]))) return i;
      }
      return n - 1;
    };

    function fillTip(i) {
      tip.replaceChildren(node("span", "trend-tip-date", fmtDate(dates[i], "medium")));
      const spoken = [fmtDate(dates[i], "medium")];
      for (const s of series) {
        const row = node("span", "trend-tip-row");
        row.append(node("span", `key-line ${seriesClass(s.id)}`));
        const count = s.n?.[i];
        row.append(node("span", "", count ? `${s.name} (${fmtInt(count)})` : s.name));
        const value = isNum(s.values[i]) ? signed(s.values[i]) : "no data";
        row.append(node("span", isNum(s.values[i]) ? "trend-tip-value" : "trend-tip-value trend-tip-muted", value));
        tip.append(row);
        spoken.push(`${s.name} ${value}`);
        const mix = s.mix?.[i];
        if (mix && LABELS.some((l) => Number(mix[l]) > 0)) {
          const counts = node("span", "trend-tip-mix");
          for (const l of LABELS) {
            const item = node("span", "trend-tip-mix-item");
            item.append(node("span", `key is-${l}`), node("span", "", `${fmtInt(Number(mix[l]) || 0)} ${l}`));
            counts.append(item);
          }
          tip.append(counts);
          spoken.push(LABELS.map((l) => `${Number(mix[l]) || 0} ${l}`).join(", "));
        }
      }
      if (counts) {
        const row = node("span", "trend-tip-row");
        row.append(node("span", "key key-count"), node("span", "", "Headlines"), node("span", "trend-tip-value", fmtInt(counts[i])));
        tip.append(row);
        spoken.push(`${fmtInt(counts[i])} headlines`);
      }
      return spoken.join(", ");
    }

    function show(i, announce = false) {
      if (!n) return;
      active = clamp(i, 0, n - 1);
      const cx = round(x(active));
      cross.setAttribute("x1", cx);
      cross.setAttribute("x2", cx);
      cross.classList.add("is-visible");
      svg.querySelectorAll("[data-i]").forEach((el) => el.classList.toggle("is-active", Number(el.dataset.i) === active));
      const text = fillTip(active);
      tip.classList.add("is-visible");
      const box = svg.getBoundingClientRect();
      const scale = box.width / W || 1;
      const px = x(active) * scale;
      const tw = tip.offsetWidth;
      let left = px + 14;
      if (left + tw > box.width) left = px - 14 - tw;
      left = clamp(left, -4, Math.max(-4, box.width - tw + 4));
      tip.style.transform = `translate(${Math.round(left)}px, ${Math.round(top * scale)}px)`;
      if (announce) live.textContent = text;
    }

    function hide() {
      active = -1;
      cross.classList.remove("is-visible");
      tip.classList.remove("is-visible");
      svg.querySelectorAll(".is-active").forEach((el) => el.classList.remove("is-active"));
    }

    const onPointer = (event) => {
      const box = svg.getBoundingClientRect();
      const vx = (event.clientX - box.left) * (W / box.width);
      show(n > 1 ? Math.round((vx - padL) / step) : 0);
    };
    const onLeave = () => {
      if (document.activeElement !== frame) hide();
    };
    const onFocus = () => show(active >= 0 ? active : lastWithData(), true);
    const onKey = (event) => {
      const moves = { ArrowLeft: -1, ArrowRight: 1 };
      let next = null;
      if (event.key in moves) next = (active < 0 ? lastWithData() : active) + moves[event.key];
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = n - 1;
      else if (event.key === "Escape") hide();
      if (next === null) return;
      event.preventDefault();
      show(next, true);
    };

    svg.addEventListener("pointermove", onPointer);
    svg.addEventListener("pointerdown", onPointer);
    svg.addEventListener("pointerleave", onLeave);
    frame.addEventListener("focus", onFocus);
    frame.addEventListener("blur", hide);
    frame.addEventListener("keydown", onKey);

    return () => {
      svg.removeEventListener("pointermove", onPointer);
      svg.removeEventListener("pointerdown", onPointer);
      svg.removeEventListener("pointerleave", onLeave);
      frame.removeEventListener("focus", onFocus);
      frame.removeEventListener("blur", hide);
      frame.removeEventListener("keydown", onKey);
    };
  }
}


// ---------------------------------------------------------------- helpers for Trends, Model Lab, Pipeline

/** Rounded ceiling for a count axis, so 0, half and max read as clean numbers: 7 -> 8, 71 -> 80. */
export function niceCeil(value) {
  const v = Math.max(1, Number(value) || 0);
  const mag = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 4, 5, 6, 8, 10]) if (m * mag >= v) return m * mag;
  return 10 * mag;
}

/**
 * Diverging heat scale: a gray neutral band that matches the label cut points (+/-0.05), then
 * three steps per side. Seven classes at most, so neighbours stay apart.
 */
export const HEAT_BINS = [0.05, 0.2, 0.4];

/** heat-n3 .. heat-0 .. heat-p3 for a score, heat-none for a missing value. */
export function heatClass(value) {
  if (!isNum(value)) return "heat-none";
  const a = Math.abs(value);
  const step = a < HEAT_BINS[0] ? 0 : a < HEAT_BINS[1] ? 1 : a < HEAT_BINS[2] ? 2 : 3;
  if (!step) return "heat-0";
  return value > 0 ? `heat-p${step}` : `heat-n${step}`;
}

/**
 * Legend for the heat scale as HTML: seven swatches with the bin edges under their joins, plus
 * swatches for the two kinds of empty cell. extra: [{ className, label }].
 */
export function heatLegendHTML({ extra = [{ className: "heat-none", label: "no headlines" }] } = {}) {
  const steps = ["heat-n3", "heat-n2", "heat-n1", "heat-0", "heat-p1", "heat-p2", "heat-p3"];
  const edges = [-HEAT_BINS[2], -HEAT_BINS[1], -HEAT_BINS[0], HEAT_BINS[0], HEAT_BINS[1], HEAT_BINS[2]];
  const swatches = steps.map((c) => `<span class="heat-swatch ${c}"></span>`).join("");
  const ticks = edges.map((v, i) => `<span class="heat-edge" style="left:${(((i + 1) / 7) * 100).toFixed(3)}%">${signed(v, v === HEAT_BINS[0] || v === -HEAT_BINS[0] ? 2 : 1)}</span>`).join("");
  const empties = extra.map((e) => `<span class="heat-legend-item"><span class="heat-swatch ${esc(e.className)}"></span>${esc(e.label)}</span>`).join("");
  const spoken = `Color scale from red for negative to green for positive. Gray is neutral, from -0.05 to +0.05; steps at 0.2 and 0.4 on each side. ${extra.map((e) => `${e.label}: ${e.className === "heat-none" ? "hollow cell" : "outlined cell"}`).join(". ")}.`;
  return `<div class="heat-legend" role="img" aria-label="${esc(spoken)}">`
    + `<span class="heat-legend-end" aria-hidden="true">negative</span>`
    + `<span class="heat-scale" aria-hidden="true"><span class="heat-swatches">${swatches}</span><span class="heat-edges">${ticks}</span></span>`
    + `<span class="heat-legend-end" aria-hidden="true">positive</span>`
    + `<span class="heat-legend-empty" aria-hidden="true">${empties}</span></div>`;
}

/**
 * Tooltip and keyboard reading for marks (HTML or SVG) inside one focusable frame.
 * The frame is a single tab stop: arrow keys move between marks (ArrowUp and ArrowDown jump by
 * `columns` in a grid), Home and End go to the start and end of the row, Escape hides the tip,
 * and an aria-live line reads the value. Pointer hover shows the same tooltip.
 *
 * describe(mark) -> { title, rows: [{ key?, label, value, muted? }], note?, spoken? }
 *   key is a class list for a small swatch ("key is-positive", "key-line series-vader").
 *   Every string is inserted with textContent, so feed text is safe here.
 * pick(event, marks) -> mark | null replaces hit testing (nearest point on a scatter).
 * start(marks) -> index of the mark to show first on keyboard focus.
 * Marks with data-order are read in that order instead of document order.
 * returns { destroy(), hide() }
 */
export function markTips(frame, {
  selector = "[data-mark]", columns = 0, describe, pick = null, start = null, label = "",
} = {}) {
  if (!frame || typeof describe !== "function") return { destroy() {}, hide() {} };
  frame.classList.add("chart-frame");
  frame.tabIndex = 0;
  if (!frame.hasAttribute("role")) frame.setAttribute("role", "group");
  if (label) frame.setAttribute("aria-label", `${label}. Use the arrow keys to read each value.`);
  const tip = node("div", "chart-tip");
  tip.setAttribute("aria-hidden", "true");
  const live = node("p", "sr-only");
  live.setAttribute("aria-live", "polite");
  frame.append(tip, live);
  let active = -1;

  const marks = () => {
    const list = [...frame.querySelectorAll(selector)];
    if (list.length && list[0].dataset.order !== undefined) {
      list.sort((a, b) => Number(a.dataset.order) - Number(b.dataset.order));
    }
    return list;
  };

  function fill(d) {
    const kids = [node("span", "chart-tip-title", d.title || "")];
    for (const r of d.rows || []) {
      const row = node("span", `chart-tip-row${r.muted ? " is-muted" : ""}`);
      row.append(node("span", r.key ? `chart-tip-key ${r.key}` : "chart-tip-key"));
      row.append(node("span", "chart-tip-label", String(r.label ?? "")));
      row.append(node("span", "chart-tip-value", String(r.value ?? "")));
      kids.push(row);
    }
    if (d.note) kids.push(node("span", "chart-tip-note", d.note));
    tip.replaceChildren(...kids);
  }

  function place(mark) {
    const fb = frame.getBoundingClientRect();
    const mb = mark.getBoundingClientRect();
    const tw = tip.offsetWidth;
    const th = tip.offsetHeight;
    const left = clamp(mb.left - fb.left + mb.width / 2 - tw / 2, 0, Math.max(0, fb.width - tw));
    let top = mb.top - fb.top - th - 10;
    // not enough room above the mark inside the viewport (sticky bars live there): go below it
    if (fb.top + top < 64) top = mb.bottom - fb.top + 10;
    tip.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
  }

  function show(i, announce = false) {
    const list = marks();
    if (!list.length) return;
    active = clamp(i, 0, list.length - 1);
    const mark = list[active];
    list.forEach((m) => m.classList.toggle("is-active", m === mark));
    const d = describe(mark) || {};
    fill(d);
    tip.classList.add("is-visible");
    place(mark);
    if (announce) {
      live.textContent = d.spoken
        || [d.title, ...(d.rows || []).map((r) => `${r.label} ${r.value}`), d.note].filter(Boolean).join(", ");
    }
  }

  function hide() {
    active = -1;
    tip.classList.remove("is-visible");
    frame.querySelectorAll(`${selector}.is-active`).forEach((m) => m.classList.remove("is-active"));
  }

  const onMove = (event) => {
    const list = marks();
    const mark = pick ? pick(event, list) : event.target.closest?.(selector);
    if (!mark || !frame.contains(mark)) {
      if (pick) hide();
      return;
    }
    const i = list.indexOf(mark);
    if (i !== active || !tip.classList.contains("is-visible")) show(i);
  };
  const onLeave = () => {
    if (document.activeElement !== frame) hide();
  };
  const onFocus = () => {
    if (!frame.matches(":focus-visible")) return;
    const list = marks();
    show(active >= 0 ? active : start ? start(list) : 0, true);
  };
  const onKey = (event) => {
    if (event.target !== frame) return;
    const list = marks();
    const n = list.length;
    if (!n) return;
    const cur = active < 0 ? (start ? start(list) : 0) : active;
    const rowStart = columns ? cur - (cur % columns) : 0;
    let next;
    switch (event.key) {
      case "ArrowRight": next = cur + 1; break;
      case "ArrowLeft": next = cur - 1; break;
      case "ArrowDown": next = cur + (columns || 1); break;
      case "ArrowUp": next = cur - (columns || 1); break;
      case "Home": next = rowStart; break;
      case "End": next = columns ? Math.min(n - 1, rowStart + columns - 1) : n - 1; break;
      case "Escape": hide(); return;
      default: return;
    }
    event.preventDefault();
    if (next < 0 || next >= n) next = columns ? cur : clamp(next, 0, n - 1);
    show(next, true);
  };

  frame.addEventListener("pointermove", onMove);
  frame.addEventListener("pointerdown", onMove);
  frame.addEventListener("pointerleave", onLeave);
  frame.addEventListener("focus", onFocus);
  frame.addEventListener("blur", hide);
  frame.addEventListener("keydown", onKey);

  return {
    hide,
    destroy() {
      frame.removeEventListener("pointermove", onMove);
      frame.removeEventListener("pointerdown", onMove);
      frame.removeEventListener("pointerleave", onLeave);
      frame.removeEventListener("focus", onFocus);
      frame.removeEventListener("blur", hide);
      frame.removeEventListener("keydown", onKey);
      tip.remove();
      live.remove();
    },
  };
}

/**
 * Scatter of two scores from -1 to +1 on one square plot, with zero crosshairs.
 * points: [{ x, y, group }] where group is a class suffix ("same", "differ") painted by CSS.
 * options: xName, yName (axis titles), label, band ({ lo, hi } shaded along x), corners
 * ({ tl, tr, bl, br } short notes drawn when the plot is wide enough), describe(point) for the
 * tooltip (same shape as markTips). Nearest point within 16px wins on hover; arrow keys walk
 * the points from left to right.
 * returns { destroy() }
 */
export function scatterPlot(container, {
  points = [], xName = "x", yName = "y", label = "Scatter plot", band = null, corners = null,
  describe = null,
} = {}) {
  if (!container) return { destroy() {} };
  const measure = () => clamp(Math.round(container.clientWidth || 320), 240, 640);
  let W = measure();
  let cleanup = draw();
  const observer = typeof ResizeObserver === "function"
    ? new ResizeObserver(() => {
      const next = measure();
      if (Math.abs(next - W) > 1) {
        W = next;
        cleanup();
        cleanup = draw();
      }
    })
    : null;
  observer?.observe(container);
  return {
    destroy() {
      observer?.disconnect();
      cleanup();
    },
  };

  function draw() {
    const padL = 44;
    const padR = 12;
    const padT = 12;
    const padB = 46;
    const side = W - padL - padR;
    const H = padT + side + padB;
    const x = (v) => padL + ((clamp(v, -1, 1) + 1) / 2) * side;
    const y = (v) => padT + (1 - (clamp(v, -1, 1) + 1) / 2) * side;
    const ticks = [-1, -0.5, 0, 0.5, 1];
    const tickText = (v) => (v === 0 ? "0" : signed(v, v % 1 ? 1 : 0));

    const grid = ticks.map((v) => {
      const cls = v === 0 ? "trend-zero" : "trend-grid";
      return `<line class="${cls}" x1="${round(x(v))}" x2="${round(x(v))}" y1="${padT}" y2="${padT + side}"/>`
        + `<line class="${cls}" x1="${padL}" x2="${padL + side}" y1="${round(y(v))}" y2="${round(y(v))}"/>`
        + `<text class="trend-tick" x="${round(x(v))}" y="${padT + side + 16}" text-anchor="middle">${tickText(v)}</text>`
        + `<text class="trend-tick" x="${padL - 7}" y="${round(y(v)) + 4}" text-anchor="end">${tickText(v)}</text>`;
    }).join("");
    const shade = band
      ? `<rect class="scatter-band" x="${round(x(band.lo))}" y="${padT}" width="${round(x(band.hi) - x(band.lo))}" height="${side}"/>`
      : "";
    let notes = "";
    if (corners && side >= 340) {
      const inset = 8;
      const spots = {
        tl: [padL + inset, padT + inset + 10, "start"],
        tr: [padL + side - inset, padT + inset + 10, "end"],
        bl: [padL + inset, padT + side - inset, "start"],
        br: [padL + side - inset, padT + side - inset, "end"],
      };
      notes = Object.entries(spots).filter(([k]) => corners[k])
        .map(([k, [cx, cy, anchor]]) => `<text class="scatter-corner" x="${cx}" y="${cy}" text-anchor="${anchor}">${esc(corners[k])}</text>`).join("");
    }
    const axes = `<text class="scatter-axis" x="${round(padL + side / 2)}" y="${H - 6}" text-anchor="middle">${esc(xName)}</text>`
      + `<text class="scatter-axis" transform="translate(11 ${round(padT + side / 2)}) rotate(-90)" text-anchor="middle">${esc(yName)}</text>`;

    const order = points.map((p, i) => i).sort((a, b) => points[a].x - points[b].x || points[a].y - points[b].y);
    const rank = new Map(order.map((i, r) => [i, r]));
    const pos = points.map((p) => [round(x(p.x)), round(y(p.y))]);
    // "same" first so the points that matter sit on top
    const drawOrder = points.map((p, i) => i).sort((a, b) => (points[a].group === "differ") - (points[b].group === "differ"));
    const dots = drawOrder.map((i) => `<circle class="scatter-dot is-${esc(points[i].group || "same")}" data-i="${i}" data-order="${rank.get(i)}" cx="${pos[i][0]}" cy="${pos[i][1]}" r="4"/>`).join("");

    container.innerHTML = `<div class="scatter-frame">
        <svg class="scatter-svg" viewBox="0 0 ${W} ${H}" aria-hidden="true" focusable="false">${shade}${grid}${notes}${axes}${dots}</svg>
      </div>`;
    const frame = container.querySelector(".scatter-frame");
    const svg = frame.querySelector("svg");

    const pick = (event, list) => {
      const box = svg.getBoundingClientRect();
      const scale = box.width / W || 1;
      const vx = (event.clientX - box.left) / scale;
      const vy = (event.clientY - box.top) / scale;
      let best = -1;
      let bestD = (16 / scale) ** 2;
      pos.forEach(([px, py], i) => {
        const dd = (px - vx) ** 2 + (py - vy) ** 2;
        if (dd <= bestD) {
          bestD = dd;
          best = i;
        }
      });
      return best < 0 ? null : list.find((el) => Number(el.dataset.i) === best) || null;
    };
    const fallback = (p) => ({
      title: p.group === "differ" ? "Different labels" : "Same label",
      rows: [{ label: xName, value: signed(p.x) }, { label: yName, value: signed(p.y) }],
    });
    const tips = markTips(frame, {
      selector: ".scatter-dot",
      pick,
      label,
      describe: (el) => (describe || fallback)(points[Number(el.dataset.i)]),
    });
    return () => tips.destroy();
  }
}
