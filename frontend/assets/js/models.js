// Model Lab: how VADER and FinBERT compare, read from model_agreement.json.

import {
  LABELS, esc, fmtDate, fmtDateTime, fmtInt, fmtPercent, hydrateChrome, labelClass, loadAll, modelName,
  mountChrome, safeUrl, signed, slug, stateHTML,
} from "./common.js";
import { divergingMeter, scatterPlot, seriesClass } from "./charts.js";

mountChrome({ page: "models" });

const PAGE_SIZE = 10;
const MODEL_ORDER = ["finbert", "vader"];

// Landis, J. R. and Koch, G. G. (1977), The Measurement of Observer Agreement for Categorical Data.
const KAPPA_BANDS = [
  { word: "poor", range: "below 0", test: (k) => k < 0 },
  { word: "slight", range: "0 to 0.20", test: (k) => k <= 0.2 },
  { word: "fair", range: "0.21 to 0.40", test: (k) => k <= 0.4 },
  { word: "moderate", range: "0.41 to 0.60", test: (k) => k <= 0.6 },
  { word: "substantial", range: "0.61 to 0.80", test: (k) => k <= 0.8 },
  { word: "almost perfect", range: "0.81 to 1", test: () => true },
];

const byId = (id) => document.getElementById(id);
const els = {
  note: byId("lab-note"),
  state: byId("lab-state"),
  body: byId("lab-body"),
  kpis: byId("kpis"),
  cm: byId("cm"),
  cmNote: byId("cm-note"),
  dist: byId("dist"),
  distNote: byId("dist-note"),
  scatter: byId("scatter"),
  scatterNote: byId("scatter-note"),
  topics: byId("by-topic"),
  topicNote: byId("topic-note"),
  dis: byId("dis"),
  disNote: byId("dis-note"),
};
const state = { chart: null, shown: 0 };

const num = (v) => (v === null || v === undefined || v === "" || !Number.isFinite(Number(v)) ? null : Number(v));
const sum = (xs) => xs.reduce((total, x) => total + (Number(x) || 0), 0);
const share = (part, whole) => (whole ? (part / whole) * 100 : null);

function kappaBand(kappa) {
  const k = num(kappa);
  return k === null ? -1 : KAPPA_BANDS.findIndex((b) => b.test(k));
}

function correlationWord(r) {
  const a = Math.abs(r);
  const word = a < 0.1 ? "negligible" : a < 0.3 ? "weak" : a < 0.5 ? "moderate" : "strong";
  return r < 0 && a >= 0.1 ? `${word}, negative` : word;
}

const ordered = (models) => [...new Set([...MODEL_ORDER.filter((m) => models.includes(m)), ...models])];


// ---------------------------------------------------------------- KPI row

function kpisHTML(r, A, B) {
  const pct = num(r.percent_agreement);
  const kappa = num(r.cohens_kappa);
  const corr = num(r.score_correlation);
  const band = kappaBand(kappa);
  const tile = ({ label, value, word = "", visual = "", note }) => `
    <div class="kpi">
      <p class="kpi-label">${esc(label)}</p>
      <p class="kpi-value"><span class="kpi-number">${esc(value)}</span>${word ? `<span class="kpi-word">${esc(word)}</span>` : ""}</p>
      ${visual}
      <p class="kpi-note">${esc(note)}</p>
    </div>`;
  const scale = band < 0 ? "" : `<div class="kscale" role="img" aria-label="${esc(`${KAPPA_BANDS[band].word}, step ${band + 1} of 6 on the Landis and Koch scale`)}">`
    + KAPPA_BANDS.map((_, i) => `<span class="kscale-seg${i === band ? " is-on" : ""}"></span>`).join("") + "</div>";
  return [
    tile({
      label: "Scored by both",
      value: fmtInt(r.n),
      word: Number(r.n) === 1 ? "headline" : "headlines",
      note: `Headlines with both a ${A} and a ${B} label, each story counted once.`,
    }),
    tile({
      label: "Percent agreement",
      value: pct === null ? "n/a" : fmtPercent(pct),
      visual: pct === null ? "" : `<div class="agree-meter" role="img" aria-label="${esc(fmtPercent(pct))} same label">`
        + `<span class="is-agree" style="flex-grow:${pct.toFixed(2)}"></span><span class="is-differ" style="flex-grow:${(100 - pct).toFixed(2)}"></span></div>`,
      note: "Share of those headlines where both models chose the same label.",
    }),
    tile({
      label: "Cohen's kappa",
      value: kappa === null ? "n/a" : kappa.toFixed(2),
      word: band < 0 ? "" : KAPPA_BANDS[band].word,
      visual: scale,
      note: band < 0
        ? "Agreement corrected for chance."
        : `Agreement corrected for chance. Landis and Koch call ${KAPPA_BANDS[band].range} ${KAPPA_BANDS[band].word}.`,
    }),
    tile({
      label: "Score correlation",
      value: corr === null ? "n/a" : corr.toFixed(2),
      word: corr === null ? "" : correlationWord(corr),
      visual: corr === null ? "" : divergingMeter(corr, { width: 200, height: 8, label: "neutral", className: "kpi-meter" }),
      note: `Pearson r between the ${A} and ${B} scores, from -1 to +1.`,
    }),
  ].join("");
}


// ---------------------------------------------------------------- confusion matrix

function cmHTML(r) {
  const cm = r.confusion_matrix;
  const labels = r.labels?.length ? r.labels : LABELS;
  const matrix = cm?.matrix;
  if (!Array.isArray(matrix) || matrix.length !== labels.length) {
    return { html: '<p class="rail-empty">The confusion matrix is not in this report.</p>', note: "" };
  }
  const rowsName = modelName(cm.rows);
  const colsName = modelName(cm.columns);
  const rowTotals = matrix.map((row) => sum(row));
  const colTotals = labels.map((_, j) => sum(matrix.map((row) => row[j])));
  const total = sum(rowTotals);
  const max = Math.max(1, ...matrix.flat().map(Number));
  const step = (c) => (c > 0 ? Math.max(1, Math.ceil((c / max) * 5)) : 0);

  const body = matrix.map((row, i) => {
    const cells = row.map((value, j) => {
      const c = Number(value) || 0;
      const pct = share(c, rowTotals[i]);
      const diag = i === j;
      return `<td class="cm-cell cm-${step(c)}${diag ? " is-diag" : ""}">`
        + `<span class="cm-count">${esc(fmtInt(c))}</span>`
        + `<span class="cm-share">${pct === null ? "" : esc(fmtPercent(pct))}<span class="sr-only"> of ${esc(rowsName)} ${esc(labels[i])}${diag ? ", same label" : ""}</span></span></td>`;
    }).join("");
    const group = i === 0
      ? `<th scope="rowgroup" rowspan="${labels.length}" class="cm-group">${esc(rowsName)} label</th>`
      : "";
    return `<tr>${group}<th scope="row">${esc(labels[i])}</th>${cells}<td class="cm-total">${esc(fmtInt(rowTotals[i]))}</td></tr>`;
  }).join("");

  let worst = null;
  matrix.forEach((row, i) => row.forEach((value, j) => {
    if (i !== j && Number(value) > (worst?.c ?? 0)) worst = { i, j, c: Number(value) };
  }));
  const note = worst
    ? `The largest mismatch: ${worst.c} headlines ${rowsName} calls ${labels[worst.i]} and ${colsName} calls ${labels[worst.j]}.`
    : "No off-diagonal cells: the two models agree on every headline.";

  const html = `
    <div class="cm-scroll">
      <table class="cm">
        <caption>Rows are ${esc(rowsName)} labels and columns are ${esc(colsName)} labels. Framed cells on the diagonal are headlines both models labeled the same; percentages are shares of the row.</caption>
        <thead>
          <tr><td colspan="2"></td><th scope="colgroup" colspan="${labels.length}" class="cm-group">${esc(colsName)} label</th><td></td></tr>
          <tr><td colspan="2"></td>${labels.map((l) => `<th scope="col">${esc(l)}</th>`).join("")}<th scope="col" class="cm-total">total</th></tr>
        </thead>
        <tbody>${body}</tbody>
        <tfoot>
          <tr><td></td><th scope="row">total</th>${colTotals.map((c) => `<td class="cm-total">${esc(fmtInt(c))}</td>`).join("")}<td class="cm-total">${esc(fmtInt(total))}</td></tr>
        </tfoot>
      </table>
    </div>
    <p class="cm-key" aria-hidden="true">
      <span class="legend-item">fewer <span class="cm-key-ramp"><span class="cm-1"></span><span class="cm-2"></span><span class="cm-3"></span><span class="cm-4"></span><span class="cm-5"></span></span> more headlines</span>
      <span class="legend-item"><span class="cm-key-diag"></span>same label</span>
    </p>`;
  return { html, note };
}


// ---------------------------------------------------------------- label distribution

function distHTML(r) {
  const dist = r.label_distribution;
  const labels = r.labels?.length ? r.labels : LABELS;
  if (!dist) return { html: '<p class="rail-empty">The label distribution is not in this report.</p>', note: "" };
  const models = ordered(Object.keys(dist));
  const totals = Object.fromEntries(models.map((m) => [m, sum(labels.map((l) => dist[m]?.[l]))]));
  const max = Math.max(1, ...models.flatMap((m) => labels.map((l) => Number(dist[m]?.[l]) || 0)));

  const groups = labels.map((l) => {
    const rows = models.map((m) => {
      const c = Number(dist[m]?.[l]) || 0;
      const pct = share(c, totals[m]);
      return `<div class="bar-row">
          <span class="bar-track"><span class="bar-fill ${seriesClass(m)}" style="width:${((c / max) * 100).toFixed(2)}%"></span></span>
          <span class="bar-value"><strong>${esc(fmtInt(c))}</strong> ${esc(modelName(m))} <span class="muted">${pct === null ? "" : esc(fmtPercent(pct))}</span></span>
        </div>`;
    }).join("");
    return `<div class="bar-group">
        <p class="bar-group-name"><span class="key is-${esc(l)}" aria-hidden="true"></span>${esc(l)}</p>
        <div class="bar-group-rows">${rows}</div>
      </div>`;
  }).join("");

  let gap = null;
  if (models.length >= 2) {
    const [m1, m2] = models;
    for (const l of labels) {
      const d = Math.abs((share(dist[m1]?.[l] || 0, totals[m1]) ?? 0) - (share(dist[m2]?.[l] || 0, totals[m2]) ?? 0));
      if (!gap || d > gap.d) gap = { l, d };
    }
    gap.text = models.slice(0, 2)
      .map((m) => `${modelName(m)} ${fmtPercent(share(dist[m]?.[gap.l] || 0, totals[m]))}`).join(", ");
  }
  const legend = `<p class="legend">${models.map((m) => `<span class="legend-item"><span class="key key-series ${seriesClass(m)}" aria-hidden="true"></span>${esc(modelName(m))}</span>`).join("")}</p>`;
  return {
    html: `${legend}<div class="bars">${groups}</div>`,
    note: gap ? `How often each model uses each label. The widest gap is on ${gap.l}: ${gap.text}.` : "How often each model uses each label.",
  };
}


// ---------------------------------------------------------------- scatter

function quadrantTable(points, A, B) {
  const sign = (v) => (v > 0 ? 0 : v < 0 ? 2 : 1);
  const names = ["above 0", "exactly 0", "below 0"];
  const grid = names.map(() => [0, 0, 0]);
  for (const p of points) grid[sign(p.x)][sign(p.y)] += 1;
  const head = `<tr><th scope="col">${esc(A)} score</th>${names.map((n) => `<th scope="col">${esc(B)} ${esc(n)}</th>`).join("")}</tr>`;
  const body = grid.map((row, i) => `<tr><th scope="row">${esc(names[i])}</th>${row.map((c) => `<td>${esc(fmtInt(c))}</td>`).join("")}</tr>`).join("");
  return `<details class="data-details"><summary>Show the counts by sign</summary><div class="table-scroll">`
    + `<table class="data-table"><caption class="sr-only">Headlines by the sign of each model's score: rows ${esc(A)}, columns ${esc(B)}</caption>`
    + `<thead>${head}</thead><tbody>${body}</tbody></table></div></details>`;
}

function renderScatter(r, a, b) {
  const A = modelName(a);
  const B = modelName(b);
  const points = (r.score_pairs || [])
    .map((p) => ({ x: num(p.a), y: num(p.b), group: p.same ? "same" : "differ" }))
    .filter((p) => p.x !== null && p.y !== null);
  if (!points.length) {
    els.scatterNote.textContent = "";
    els.scatter.innerHTML = '<p class="rail-empty">No score pairs in this report yet.</p>';
    return;
  }
  const same = points.filter((p) => p.group === "same").length;
  const differ = points.length - same;
  const sampled = Number(r.n) > points.length;
  const band = a === "vader";
  els.scatterNote.textContent = `One dot per headline: ${A} score across, ${B} score up.`
    + (sampled ? ` A fixed sample of ${fmtInt(points.length)} of ${fmtInt(r.n)} headlines.` : "");
  els.scatter.innerHTML = `
    <p class="legend">
      <span class="legend-item"><span class="key-dot" aria-hidden="true"></span>different labels (${esc(fmtInt(differ))})</span>
      <span class="legend-item"><span class="key-ring" aria-hidden="true"></span>same label (${esc(fmtInt(same))})</span>
      ${band ? '<span class="legend-item"><span class="key-band" aria-hidden="true"></span>VADER neutral band</span>' : ""}
    </p>
    <div class="scatter-wrap" data-scatter></div>
    <p class="rail-caption">${esc(fmtInt(points.length))} headlines, ${esc(fmtInt(same))} with the same label and ${esc(fmtInt(differ))} with different labels.
      Dots far from the diagonal are the headlines the two models read in opposite ways.</p>
    ${quadrantTable(points, A, B)}`;
  state.chart?.destroy();
  state.chart = scatterPlot(els.scatter.querySelector("[data-scatter]"), {
    points,
    xName: `${A} score`,
    yName: `${B} score`,
    label: `Scatter of ${A} score against ${B} score for ${points.length} headlines`,
    band: band ? { lo: -0.05, hi: 0.05 } : null,
    corners: { tl: `${A} -, ${B} +`, tr: "both positive", bl: "both negative", br: `${A} +, ${B} -` },
    describe: (p) => ({
      title: p.group === "differ" ? "Different labels" : "Same label",
      rows: [
        { label: A, value: signed(p.x) },
        { label: B, value: signed(p.y) },
        { label: "gap", value: signed(p.y - p.x) },
      ],
    }),
  });
}


// ---------------------------------------------------------------- by topic

function topicsHTML(r) {
  const topics = Array.isArray(r.by_topic) ? r.by_topic : [];
  if (!topics.length) return { html: '<p class="rail-empty">No per topic numbers in this report.</p>', note: "" };
  const overall = num(r.percent_agreement);
  const ref = overall === null ? "" : `<span class="bar-ref" style="left:${overall.toFixed(2)}%"></span>`;
  const rows = topics.map((t) => {
    const name = String(t.topic ?? "Topic");
    const link = `<a class="bar-name" href="index.html#${esc(slug(name))}">${esc(name)}</a>`;
    const pct = num(t.percent_agreement);
    if (!Number(t.n) || pct === null) {
      return `<div class="bar-row has-name">${link}<span class="bar-track has-track">${ref}</span><span class="bar-value muted">no pairs yet</span></div>`;
    }
    const kappa = num(t.cohens_kappa);
    const band = kappaBand(kappa);
    const sub = `kappa ${kappa === null ? "n/a" : kappa.toFixed(2)}${band < 0 ? "" : `, ${KAPPA_BANDS[band].word}`}, ${fmtInt(t.n)} ${Number(t.n) === 1 ? "headline" : "headlines"}`;
    return `<div class="bar-row has-name">${link}
        <span class="bar-track has-track" role="img" aria-label="${esc(`${name}: ${fmtPercent(pct)} agreement, ${sub}`)}"><span class="bar-fill" style="width:${pct.toFixed(2)}%"></span>${ref}</span>
        <span class="bar-value"><strong>${esc(fmtPercent(pct))}</strong></span>
        <span class="bar-sub" aria-hidden="true">${esc(sub)}</span>
      </div>`;
  }).join("");
  const legend = overall === null ? "" : `<p class="legend"><span class="legend-item"><span class="key-tick" aria-hidden="true"></span>all topics, ${esc(fmtPercent(overall))}</span></p>`;
  return {
    html: `${legend}<div class="bars bars--topics">${rows}</div>`,
    note: "Percent agreement per topic, with kappa underneath. A story filed under two topics counts in both.",
  };
}


// ---------------------------------------------------------------- disagreements

function badgeHTML(model, s) {
  const score = num(s?.score);
  return `<span class="badge ${labelClass(s?.label)}">`
    + `<span class="badge-who">${esc(modelName(model))}</span>`
    + `<span class="badge-label">${esc(s?.label || "n/a")}</span>`
    + `<span class="badge-score">${esc(signed(score))}</span>`
    + `${divergingMeter(score, { width: 28, height: 6, label: s?.label, className: "badge-meter" })}</span>`;
}

function disItemHTML(d, a, b, i) {
  const topic = String(d.topic ?? "");
  return `
    <li class="dis" data-i="${i}">
      <div class="dis-main">
        <h3 class="dis-title"><a href="${esc(safeUrl(d.link))}" target="_blank" rel="noopener noreferrer">${esc(d.title)}</a></h3>
        <p class="dis-meta">
          ${topic ? `<a class="chip" href="index.html#${esc(slug(topic))}">${esc(topic)}</a>` : ""}
          <span class="story-source">${esc(d.source || "Unknown source")}</span>
          ${d.run_date ? `<span class="sep" aria-hidden="true">&middot;</span><time datetime="${esc(d.run_date)}">${esc(fmtDate(d.run_date, "medium"))}</time>` : ""}
        </p>
      </div>
      <div class="dis-scores">
        ${badgeHTML(a, d.a)}
        ${badgeHTML(b, d.b)}
        <p class="dis-gap">gap <strong>${esc(signed(d.gap))}</strong></p>
      </div>
    </li>`;
}

function renderDisagreements(r, a, b) {
  const list = Array.isArray(r.disagreements) ? r.disagreements : [];
  const A = modelName(a);
  const B = modelName(b);
  if (!list.length) {
    els.disNote.textContent = "";
    els.dis.innerHTML = stateHTML({
      kind: "empty",
      title: "No disagreements to show",
      detail: `${A} and ${B} gave the same label to every headline they both scored.`,
    });
    return;
  }
  els.disNote.textContent = `The most recent headlines with different labels, newest run first and the largest gap first within a day. Gap is the ${B} score minus the ${A} score.`;
  els.dis.innerHTML = `<ol class="dis-list" aria-label="Headlines the models label differently"></ol>
    <div class="more-row">
      <button class="btn" type="button" data-more>Show more</button>
      <span data-count aria-live="polite"></span>
    </div>`;
  const ol = els.dis.querySelector("ol");
  const more = els.dis.querySelector("[data-more]");
  const count = els.dis.querySelector("[data-count]");
  state.shown = 0;

  const showNext = () => {
    const next = list.slice(state.shown, state.shown + PAGE_SIZE);
    ol.insertAdjacentHTML("beforeend", next.map((d, i) => disItemHTML(d, a, b, state.shown + i)).join(""));
    const firstNew = ol.querySelector(`[data-i="${state.shown}"] a`);
    state.shown += next.length;
    const left = list.length - state.shown;
    count.textContent = `Showing ${fmtInt(state.shown)} of ${fmtInt(list.length)}`;
    more.hidden = left <= 0;
    more.textContent = `Show ${Math.min(PAGE_SIZE, left)} more`;
    return firstNew;
  };
  showNext();
  more.addEventListener("click", () => showNext()?.focus());
}


// ---------------------------------------------------------------- load

async function load() {
  els.state.innerHTML = stateHTML({ kind: "loading", title: "Loading the agreement report" });
  const data = await loadAll(["news", "trends", "agreement", "status"]);
  hydrateChrome(data);

  const r = data.agreement;
  if (!r) {
    const reason = data.errors.agreement ? ` (${data.errors.agreement.message || data.errors.agreement})` : "";
    els.state.innerHTML = stateHTML({
      kind: "error",
      title: "The agreement report is not available",
      detail: `model_agreement.json could not be loaded${reason}. Build it with `,
      html: "<code>py -m why compare</code>.",
    });
    return;
  }
  if (r.generated_at) {
    els.note.textContent = `Computed by why compare over the whole history. Updated ${fmtDateTime(r.generated_at)}.`;
  }
  const [a, b] = Array.isArray(r.models) && r.models.length >= 2 ? r.models : ["vader", "finbert"];
  if (!Number(r.n)) {
    els.state.innerHTML = stateHTML({
      kind: "empty",
      title: "Nothing to compare yet",
      detail: `No headline has both a ${modelName(a)} and a ${modelName(b)} score. FinBERT runs in GitHub Actions; locally it needs `,
      html: "<code>py -m why run --models vader,finbert</code> and then <code>py -m why compare</code>.",
    });
    return;
  }

  els.state.innerHTML = "";
  els.body.hidden = false;
  els.kpis.innerHTML = kpisHTML(r, modelName(a), modelName(b));
  const cm = cmHTML(r);
  els.cm.innerHTML = cm.html;
  els.cmNote.textContent = cm.note;
  const dist = distHTML(r);
  els.dist.innerHTML = dist.html;
  els.distNote.textContent = dist.note;
  renderScatter(r, a, b);
  const topics = topicsHTML(r);
  els.topics.innerHTML = topics.html;
  els.topicNote.textContent = topics.note;
  renderDisagreements(r, a, b);
}

load();
