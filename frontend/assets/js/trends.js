// Trends: the trends.json window as a heat strip, a daily label mix and one small chart per topic.
// The window (7, 14 or 30 days) and the model live in the URL hash: trends.html#days=14&model=vader

import {
  LABELS, esc, fmtDate, fmtDateTime, fmtInt, hydrateChrome, labelClass, labelFor, loadAll, modelName,
  mountChrome, signed, slug, stateHTML,
} from "./common.js";
import {
  heatClass, heatLegendHTML, markTips, seriesClass, symmetricDomain, trendChart, trendTable,
} from "./charts.js";

mountChrome({ page: "trends" });

const WINDOWS = [7, 14, 30];
const MODEL_ORDER = ["finbert", "vader"];

const byId = (id) => document.getElementById(id);
const els = {
  note: byId("trends-note"),
  controls: byId("controls"),
  windows: byId("window-group"),
  models: byId("model-group"),
  coverage: byId("coverage"),
  state: byId("trends-state"),
  blocks: [...document.querySelectorAll("[data-block]")],
  heatNote: byId("heat-note"),
  heatLegend: byId("heat-legend"),
  heat: byId("heat"),
  mixNote: byId("mix-note"),
  mix: byId("mixday"),
  multNote: byId("multiples-note"),
  multLegend: byId("multiples-legend"),
  multiples: byId("multiples"),
};

const state = {
  trends: null,
  windows: WINDOWS,
  models: [],
  days: 30,
  model: null,
  firstDate: null,
  charts: [],
  tips: [],
};

const isNum = (v) => v !== null && v !== undefined && v !== "" && Number.isFinite(Number(v));
const sum = (xs) => xs.reduce((total, x) => total + x, 0);

function addDays(iso, delta) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + delta);
  return d.toISOString().slice(0, 10);
}


// ---------------------------------------------------------------- hash state

function readHash() {
  const params = new URLSearchParams(location.hash.replace(/^#/, ""));
  const days = Number(params.get("days"));
  const model = (params.get("model") || "").toLowerCase();
  return {
    days: state.windows.includes(days) ? days : null,
    model: state.models.includes(model) ? model : null,
  };
}

function writeHash() {
  const hash = `#days=${state.days}&model=${encodeURIComponent(state.model)}`;
  if (location.hash !== hash) history.replaceState(null, "", hash);
}


// ---------------------------------------------------------------- view model

/** Points for the selected window and model. A day without data keeps avg null: a gap, never a zero. */
function buildView() {
  const { trends, days, model } = state;
  const dates = Array.from({ length: days }, (_, i) => addDays(trends.end_date, i - days + 1));
  const topics = (trends.topics || []).map((topic) => {
    const byDate = new Map((topic.series || []).map((p) => [p.date, p]));
    const points = dates.map((date) => {
      const p = byDate.get(date);
      const s = p?.sentiment?.[model];
      const n = Number(s?.n) || 0;
      const scored = n > 0 && isNum(s?.avg);
      return {
        date,
        count: Number(p?.count) || 0,
        n: scored ? n : 0,
        avg: scored ? Number(s.avg) : null,
        mix: scored ? Object.fromEntries(LABELS.map((l) => [l, Number(s[l]) || 0])) : null,
      };
    });
    const label = String(topic.label ?? "Topic");
    const scored = sum(points.map((p) => p.n));
    return {
      label,
      slug: slug(label),
      points,
      total: sum(points.map((p) => p.count)),
      scored,
      activeDays: points.filter((p) => p.count > 0).length,
      average: scored ? sum(points.map((p) => (p.avg === null ? 0 : p.avg * p.n))) / scored : null,
    };
  });
  const dayWith = (test) => dates.filter((_, i) => topics.some((t) => test(t.points[i]))).length;
  return {
    dates,
    model,
    name: modelName(model),
    topics,
    total: sum(topics.map((t) => t.total)),
    scored: sum(topics.map((t) => t.scored)),
    headlineDays: dayWith((p) => p.count > 0),
    scoredDays: dayWith((p) => p.avg !== null),
  };
}

function lastScored(points) {
  for (let i = points.length - 1; i >= 0; i--) if (points[i].avg !== null) return points[i];
  return null;
}

/** Tooltip content shared by the heat strip and the label mix. */
function describeDay(v, el) {
  const topic = v.topics[Number(el.dataset.r)];
  const p = topic?.points[Number(el.dataset.c)];
  if (!p) return {};
  const title = `${topic.label}, ${fmtDate(p.date, "medium")}`;
  if (!p.count) {
    const before = state.firstDate && p.date < state.firstDate;
    return { title, rows: [], note: before ? "Before the history starts." : "No headlines this day." };
  }
  const rows = [];
  if (p.avg !== null) {
    rows.push({ key: `key ${labelClass(labelFor(p.avg))}`, label: `${v.name} average`, value: signed(p.avg) });
  } else {
    rows.push({ label: `${v.name} average`, value: "not scored", muted: true });
  }
  rows.push({ label: "Scored", value: `${fmtInt(p.n)} of ${fmtInt(p.count)}` });
  if (p.mix) for (const l of LABELS) rows.push({ key: `key is-${l}`, label: l, value: fmtInt(p.mix[l]) });
  return { title, rows };
}


// ---------------------------------------------------------------- heat strip and label mix

function axisHTML(v, endText) {
  const dates = v.dates;
  const mid = dates[Math.floor((dates.length - 1) / 2)];
  return `<div class="hm-row hm-axis" aria-hidden="true">
      <span class="hm-label"></span>
      <div class="hm-cells"><span>${esc(fmtDate(dates[0]))}</span>${dates.length > 7 ? `<span>${esc(fmtDate(mid))}</span>` : ""}<span>${esc(fmtDate(dates[dates.length - 1]))}</span></div>
      <span class="hm-end">${esc(endText)}</span>
    </div>`;
}

function daysTable(v, { caption, cell }) {
  const rows = v.dates.map((date, i) => ({ date, i })).filter(({ i }) => v.topics.some((t) => t.points[i].count > 0));
  if (!rows.length) return "";
  const head = `<tr><th scope="col">Day</th>${v.topics.map((t) => `<th scope="col">${esc(t.label)}</th>`).join("")}</tr>`;
  const body = rows.map(({ date, i }) => `<tr><th scope="row">${esc(fmtDate(date, "short"))}</th>`
    + v.topics.map((t) => `<td>${esc(cell(t.points[i]))}</td>`).join("") + "</tr>").join("");
  return `<details class="data-details"><summary>Show the numbers</summary><div class="table-scroll">`
    + `<table class="data-table"><caption class="sr-only">${esc(caption)}</caption><thead>${head}</thead>`
    + `<tbody>${body}</tbody></table></div></details>`;
}

function heatHTML(v) {
  const rows = v.topics.map((t, r) => {
    const cells = t.points.map((p, c) => {
      const cls = p.avg !== null ? heatClass(p.avg) : p.count > 0 ? "heat-unscored" : "heat-none";
      return `<span class="hm-cell ${cls}" data-r="${r}" data-c="${c}"></span>`;
    }).join("");
    const last = lastScored(t.points);
    return `<div class="hm-row">
        <a class="hm-label" href="index.html#${esc(t.slug)}">${esc(t.label)}</a>
        <div class="hm-cells" style="--n:${v.dates.length}">${cells}</div>
        <span class="hm-end">${last ? esc(signed(last.avg)) : "n/a"}</span>
      </div>`;
  }).join("");
  const table = daysTable(v, {
    caption: `Daily average ${v.name} score by topic, with the number of scored headlines in parentheses`,
    cell: (p) => (p.avg !== null ? `${signed(p.avg)} (${p.n})` : p.count ? "not scored" : ""),
  });
  return `<div class="hm">${rows}</div>${axisHTML(v, "latest")}${table}`;
}

function mixHTML(v) {
  const rows = v.topics.map((t, r) => {
    const cols = t.points.map((p, c) => {
      const total = p.mix ? sum(LABELS.map((l) => p.mix[l])) : 0;
      if (!total) {
        const before = state.firstDate && p.date < state.firstDate ? " is-before" : "";
        return `<span class="mixday-col is-empty${before}" data-r="${r}" data-c="${c}"></span>`;
      }
      const segs = LABELS.filter((l) => p.mix[l] > 0)
        .map((l) => `<span class="mixday-seg is-${l}" style="flex-grow:${p.mix[l]}"></span>`).join("");
      return `<span class="mixday-col" data-r="${r}" data-c="${c}">${segs}</span>`;
    }).join("");
    return `<div class="hm-row">
        <a class="hm-label" href="index.html#${esc(t.slug)}">${esc(t.label)}</a>
        <div class="hm-cells" style="--n:${v.dates.length}">${cols}</div>
        <span class="hm-end">${esc(fmtInt(t.scored))}</span>
      </div>`;
  }).join("");
  const table = daysTable(v, {
    caption: `Daily ${v.name} labels by topic: positive, neutral and negative counts`,
    cell: (p) => (p.mix ? LABELS.map((l) => p.mix[l]).join(" / ") : p.count ? "not scored" : ""),
  });
  return `<div class="hm mixday">${rows}</div>${axisHTML(v, "scored")}${table}`;
}


// ---------------------------------------------------------------- small multiples

function seriesOf(t, v) {
  return {
    dates: v.dates,
    series: [{
      id: v.model,
      name: v.name,
      values: t.points.map((p) => p.avg),
      n: t.points.map((p) => p.n),
      mix: t.points.map((p) => p.mix),
    }],
    counts: t.points.map((p) => p.count),
  };
}

function multiplesHTML(v) {
  return v.topics.map((t, i) => {
    const id = `multiple-${esc(t.slug)}`;
    const caption = t.total
      ? `${fmtInt(t.total)} headlines on ${t.activeDays} of ${v.dates.length} days, ${fmtInt(t.scored)} scored by ${v.name}.`
      : `No headlines in the last ${v.dates.length} days.`;
    return `
      <article class="multiple" aria-labelledby="${id}">
        <header class="multiple-head">
          <h3 class="multiple-title" id="${id}"><a href="index.html#${esc(t.slug)}">${esc(t.label)}</a></h3>
          <p class="multiple-figure">
            <span class="multiple-value">${t.average === null ? "n/a" : esc(signed(t.average))}</span>
            <span class="multiple-meta">${v.dates.length}-day average</span>
          </p>
        </header>
        <div class="trend" data-multiple="${i}"></div>
        <p class="rail-caption">${esc(caption)}</p>
        ${trendTable(seriesOf(t, v), { caption: `${t.label}: daily average ${v.name} score and headlines` })}
      </article>`;
  }).join("");
}


// ---------------------------------------------------------------- render

function syncControls() {
  els.windows.querySelectorAll("[data-days]").forEach((b) => {
    b.setAttribute("aria-pressed", String(Number(b.dataset.days) === state.days));
  });
  els.models.querySelectorAll("[data-model]").forEach((b) => {
    b.setAttribute("aria-pressed", String(b.dataset.model === state.model));
  });
}

function render() {
  state.charts.forEach((c) => c.destroy());
  state.tips.forEach((t) => t.destroy());
  state.charts = [];
  state.tips = [];
  syncControls();
  writeHash();

  const v = buildView();
  els.coverage.textContent = `${v.headlineDays} of ${v.dates.length} days with headlines, `
    + `${fmtDate(v.dates[0])} to ${fmtDate(v.dates[v.dates.length - 1])}`;

  if (!v.total) {
    els.blocks.forEach((b) => { b.hidden = true; });
    const longer = state.days < state.windows[state.windows.length - 1];
    els.state.innerHTML = stateHTML({
      kind: "empty",
      title: `No headlines in the last ${v.dates.length} days`,
      detail: longer
        ? "Try a longer window. The trends fill in as daily runs add up."
        : "The history has no runs in this window yet. The trends fill in as daily runs add up.",
    });
    return;
  }
  els.blocks.forEach((b) => { b.hidden = false; });
  els.state.innerHTML = v.scored
    ? ""
    : `<p class="block-foot">No ${esc(v.name)} scores in this window yet${v.model === "finbert" ? ": FinBERT runs only in GitHub Actions" : ""}. Outlined cells have headlines without a score.</p>`;

  const thin = v.headlineDays < 3 ? " Only a few days have data so far, so most of the window is empty." : "";
  els.heatNote.textContent = `Each cell is a topic's average ${v.name} score for one day. Gray is neutral; hollow cells had no headlines.${thin}`;
  els.heatLegend.innerHTML = heatLegendHTML({
    extra: [{ className: "heat-unscored", label: "not scored" }, { className: "heat-none", label: "no headlines" }],
  });
  els.heat.innerHTML = heatHTML(v);
  const columns = v.dates.length;
  state.tips.push(markTips(els.heat.querySelector(".hm"), {
    selector: ".hm-cell",
    columns,
    start: () => columns - 1,
    label: `Daily average ${v.name} score, one row per topic and one cell per day`,
    describe: (el) => describeDay(v, el),
  }));

  els.mixNote.textContent = `Each column splits one day's ${v.name} labels into positive, neutral and negative, as shares of that day. The number on the right counts scored headlines in the window.`;
  els.mix.innerHTML = mixHTML(v);
  state.tips.push(markTips(els.mix.querySelector(".hm"), {
    selector: ".mixday-col",
    columns,
    start: () => columns - 1,
    label: `Daily ${v.name} label mix, one row per topic and one column per day`,
    describe: (el) => describeDay(v, el),
  }));

  els.multNote.textContent = `Daily average score on one shared scale, so topics compare directly. Gaps are days without scored headlines. The figure is the ${v.dates.length}-day average, weighted by headlines.`;
  els.multLegend.innerHTML = `<span class="legend-item"><span class="key-line ${seriesClass(v.model)}" aria-hidden="true"></span>${esc(v.name)} daily average</span>`
    + '<span class="legend-item"><span class="key key-count" aria-hidden="true"></span>headlines per day</span>';
  els.multiples.innerHTML = multiplesHTML(v);
  const domain = symmetricDomain(v.topics.flatMap((t) => t.points.map((p) => p.avg)), 0.25);
  els.multiples.querySelectorAll("[data-multiple]").forEach((box) => {
    const t = v.topics[Number(box.dataset.multiple)];
    state.charts.push(trendChart(box, {
      ...seriesOf(t, v),
      label: `${t.label}, daily average ${v.name} score and headlines per day`,
      domain,
      plotHeight: 100,
    }));
  });
}

function wire() {
  els.controls.addEventListener("click", (event) => {
    const btn = event.target.closest("button");
    if (!btn) return;
    if (btn.dataset.days && Number(btn.dataset.days) !== state.days) {
      state.days = Number(btn.dataset.days);
      render();
    } else if (btn.dataset.model && btn.dataset.model !== state.model) {
      state.model = btn.dataset.model;
      render();
    }
  });
  window.addEventListener("hashchange", () => {
    if (!state.trends) return;
    const next = readHash();
    const days = next.days ?? state.days;
    const model = next.model ?? state.model;
    if (days !== state.days || model !== state.model) {
      state.days = days;
      state.model = model;
      render();
    }
  });
}


// ---------------------------------------------------------------- load

async function load() {
  els.state.innerHTML = stateHTML({ kind: "loading", title: "Loading the trends" });
  const data = await loadAll(["news", "trends", "agreement", "status"]);
  hydrateChrome(data);

  const trends = data.trends;
  if (!trends) {
    const reason = data.errors.trends ? ` (${data.errors.trends.message || data.errors.trends})` : "";
    els.state.innerHTML = stateHTML({
      kind: "error",
      title: "The trends are not available",
      detail: `trends.json could not be loaded${reason}. Build it locally with `,
      html: "<code>py -m why run</code>.",
    });
    return;
  }
  const models = trends.models || [];
  if (!trends.end_date || !(trends.topics || []).length || !models.length) {
    els.state.innerHTML = stateHTML({
      kind: "empty",
      title: "No trend history yet",
      detail: "trends.json has no scored days. It fills in after the first daily run.",
    });
    return;
  }

  state.trends = trends;
  const longest = Math.max(1, Number(trends.days) || Math.max(...trends.topics.map((t) => t.series?.length || 0)));
  state.windows = WINDOWS.filter((w) => w <= longest);
  if (!state.windows.length) state.windows = [longest];
  state.models = [...new Set([...MODEL_ORDER.filter((m) => models.includes(m)), ...models])];
  let first = null;
  for (const t of trends.topics) {
    for (const p of t.series || []) if (Number(p.count) > 0 && (!first || p.date < first)) first = p.date;
  }
  state.firstDate = first;

  const fromHash = readHash();
  state.days = fromHash.days ?? state.windows[state.windows.length - 1];
  state.model = fromHash.model
    ?? (state.models.includes(trends.primary_model) ? trends.primary_model : state.models[0]);

  els.windows.innerHTML = state.windows.map((d) =>
    `<button class="btn" type="button" data-days="${d}" aria-pressed="false">${d} days</button>`).join("");
  els.models.innerHTML = state.models.map((m) =>
    `<button class="btn" type="button" data-model="${esc(m)}" aria-pressed="false">${esc(modelName(m))}</button>`).join("");
  els.note.textContent = `Data through ${fmtDate(trends.end_date, "long")}, updated ${fmtDateTime(trends.generated_at)}. `
    + "Headlines count on the run date they were first seen.";
  els.state.innerHTML = "";
  els.controls.hidden = false;
  render();
}

wire();
load();
