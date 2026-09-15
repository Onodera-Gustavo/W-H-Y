// Pipeline: the last run, the daily ingest, the history and the top sources, all from status.json.
// The architecture diagram is static markup in pipeline.html, so it shows even without a report.

import {
  esc, fmtDate, fmtDateTime, fmtInt, hydrateChrome, loadAll, modelName, mountChrome, relTime, slug,
  stateHTML,
} from "./common.js";
import { markTips, niceCeil } from "./charts.js";

mountChrome({ page: "pipeline" });

const FRESH_HOURS = 26; // a daily run plus a margin for a slow runner
const MIN_DAYS = 14;
const MAX_DAYS = 30;
const MODEL_ORDER = ["finbert", "vader"];
const MODE_TEXT = {
  fetch: "A live run: one Google News RSS request per topic, then load, score and export.",
  replay: "A replay: a stored raw partition loaded again without any network request, then load, score and export.",
  backfill: "A backfill started by hand: past run dates collected with date searches, then load, score and export.",
};

const byId = (id) => document.getElementById(id);
const els = {
  note: byId("status-note"),
  state: byId("status-state"),
  runBlock: byId("run-block"),
  run: byId("run-card"),
  side: byId("run-side"),
  ingestBlock: byId("ingest-block"),
  ingestNote: byId("ingest-note"),
  ingest: byId("ingest"),
  historyBlock: byId("history-block"),
  historyNote: byId("history-note"),
  history: byId("history"),
  sourcesBlock: byId("sources-block"),
  sourcesNote: byId("sources-note"),
  sources: byId("sources"),
};

const int = (v) => fmtInt(v) || "n/a";
const ordered = (models) => [...new Set([...MODEL_ORDER.filter((m) => models.includes(m)), ...models])];
const pad2 = (n) => String(n).padStart(2, "0");

function addDays(iso, delta) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + delta);
  return d.toISOString().slice(0, 10);
}

const daysBetween = (a, b) => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86400000);

/** Next run for a daily cron such as "0 9 * * *"; null for anything else. */
function nextRun(cron, now) {
  const m = /^(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*$/.exec(String(cron || "").trim());
  if (!m) return null;
  const minute = Number(m[1]);
  const hour = Number(m[2]);
  if (minute > 59 || hour > 23) return null;
  const at = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), hour, minute));
  if (at <= now) at.setUTCDate(at.getUTCDate() + 1);
  return { at, hour, minute };
}

function untilText(ms) {
  const minutes = Math.max(0, Math.round(ms / 60000));
  if (minutes < 60) return `in ${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return minutes % 60 ? `in ${hours}h ${minutes % 60}m` : `in ${hours}h`;
}

function statHTML(label, value, note = "") {
  return `<div class="stat"><p class="stat-label">${esc(label)}</p><p class="stat-value">${esc(value)}</p>`
    + `${note ? `<p class="stat-note">${esc(note)}</p>` : ""}</div>`;
}


// ---------------------------------------------------------------- last run

function freshnessHTML(status, now) {
  const generated = Date.parse(status.generated_at);
  if (!Number.isFinite(generated)) return { chip: "", text: "" };
  const hours = (now - generated) / 3600000;
  const fresh = hours < FRESH_HOURS;
  const chip = `<span class="chip${fresh ? "" : " chip--alert"}"><span class="chip-dot" aria-hidden="true"></span>${fresh ? "Fresh" : "Stale"}</span>`;
  const text = `Report written ${fmtDateTime(status.generated_at)}, ${relTime(status.generated_at, now)}.`
    + (fresh ? "" : " The daily run should replace it every 24 hours, so check the pipeline runs.");
  return { chip, text };
}

function runCardHTML(status, now) {
  const run = status.run;
  const fresh = freshnessHTML(status, now);
  if (!run) {
    return `<div class="run-head"><h2 class="run-title" id="run-title">Last run</h2>${fresh.chip}</div>
      <p class="run-lede">No run is recorded in this report: it was rebuilt from the Parquet history, so only the history numbers below are known. ${esc(fresh.text)}</p>`;
  }
  const mode = String(run.mode || "unknown");
  const scored = run.scored && typeof run.scored === "object" ? run.scored : {};
  const models = ordered([...(status.models?.available || []), ...Object.keys(scored)]);
  const tiles = [
    statHTML("Raw records", int(run.raw_records), "in the loaded partitions"),
    statHTML("Inserted", int(run.inserted), "new story rows"),
    statHTML("Seen again", int(run.seen_again), "already stored"),
    ...models.map((m) => statHTML(`Scored, ${modelName(m)}`, int(scored[m] ?? 0), "new scores")),
    statHTML("Filtered", int(run.filtered_low_quality), "low quality titles"),
    statHTML("Requests", int(run.requests), mode === "replay" ? "a replay stays offline" : "to Google News"),
  ].join("");
  const failed = Array.isArray(run.failed_topics) ? run.failed_topics : [];
  const bf = run.backfill;
  const backfill = bf
    ? `<dt>Backfill</dt><dd>${esc(int(bf.days))} days, ${esc(fmtDate(bf.first_run_date, "medium"))} to ${esc(fmtDate(bf.last_run_date, "medium"))}: `
      + `${esc(int(bf.fetched?.length ?? 0))} fetched, ${esc(int(bf.skipped?.length ?? 0))} skipped, ${esc(int(bf.empty?.length ?? 0))} empty, ${esc(int(bf.records))} records</dd>`
    : "";
  return `
    <div class="run-head">
      <h2 class="run-title" id="run-title">Last run</h2>
      <span class="chip">${esc(mode)}</span>
      ${fresh.chip}
    </div>
    <p class="run-lede">${esc(MODE_TEXT[mode] || "")} Run date ${esc(fmtDate(run.run_date, "long") || "unknown")}. ${esc(fresh.text)}</p>
    <div class="stats">${tiles}</div>
    <dl class="kv">
      <dt>Failed topics</dt><dd>${failed.length ? esc(failed.join(", ")) : "None"}</dd>
      ${backfill}
    </dl>`;
}

function sideHTML(status, now) {
  const cron = String(status.schedule || "");
  const next = nextRun(cron, new Date(now));
  const cfg = status.config || {};
  const available = ordered(status.models?.available || []);
  const primary = status.models?.primary;
  const modelsText = available.map((m) => `${modelName(m)}${m === primary ? " (on the badges)" : ""}`).join(", ");
  return `
    <section class="run-side" aria-labelledby="schedule-title">
      <h2 class="kicker" id="schedule-title">Schedule</h2>
      <dl class="kv">
        <dt>Cron</dt><dd>${cron ? `<code>${esc(cron)}</code>` : "n/a"}</dd>
        <dt>When</dt><dd>${next ? `Every day at ${pad2(next.hour)}:${pad2(next.minute)} UTC` : "n/a"}</dd>
        <dt>Next run</dt><dd>${next ? `${esc(fmtDateTime(next.at))}, ${esc(untilText(next.at - now))}` : "n/a"}</dd>
      </dl>
    </section>
    <section class="run-side" aria-labelledby="config-title">
      <h2 class="kicker" id="config-title">Configuration</h2>
      <dl class="kv">
        <dt>Version</dt><dd>${esc(status.version || "n/a")}</dd>
        <dt>Models</dt><dd>${modelsText ? esc(modelsText) : "n/a"}</dd>
        <dt>Edition</dt><dd>${cfg.max_per_topic ? `up to ${esc(int(cfg.max_per_topic))} headlines per topic` : "n/a"}</dd>
        <dt>Trends</dt><dd>${cfg.trend_days ? `the last ${esc(int(cfg.trend_days))} days` : "n/a"}</dd>
      </dl>
    </section>`;
}


// ---------------------------------------------------------------- daily ingest

function ingestView(status) {
  const daily = (Array.isArray(status.daily) ? status.daily : [])
    .filter((d) => d && /^\d{4}-\d{2}-\d{2}$/.test(d.run_date))
    .sort((a, b) => (a.run_date < b.run_date ? -1 : 1));
  if (!daily.length) return null;
  const first = daily[0].run_date;
  const last = daily[daily.length - 1].run_date;
  const span = Math.min(MAX_DAYS, Math.max(MIN_DAYS, daysBetween(first, last) + 1));
  const byDate = new Map(daily.map((d) => [d.run_date, d]));
  const days = Array.from({ length: span }, (_, i) => {
    const date = addDays(last, i - span + 1);
    const d = byDate.get(date);
    const fresh = Number(d?.new_headlines) || 0;
    const seen = Number(d?.seen_again) || 0;
    return { date, run: Boolean(d), fresh, seen, total: fresh + seen, before: date < first };
  });
  const max = niceCeil(Math.max(1, ...days.map((d) => d.total)));
  return { days, max, first, last, runs: daily.length };
}

function ingestHTML(v) {
  const slots = v.days.map((d, i) => {
    if (!d.run) {
      return `<div class="col-slot" data-i="${i}">${d.before ? "" : '<span class="col-miss"></span>'}</div>`;
    }
    const height = ((d.total / v.max) * 100).toFixed(2);
    const segs = (d.seen > 0 ? `<span class="col-seg is-seen" style="flex-grow:${d.seen}"></span>` : "")
      + (d.fresh > 0 ? `<span class="col-seg" style="flex-grow:${d.fresh}"></span>` : "");
    const label = i === v.days.length - 1 ? `<span class="col-value" style="bottom:${height}%">${esc(fmtInt(d.total))}</span>` : "";
    return `<div class="col-slot" data-i="${i}">${label}<span class="col-stack" style="height:${height}%">${segs}</span></div>`;
  }).join("");
  const half = v.max / 2;
  const rows = v.days.filter((d) => d.run).map((d) =>
    `<tr><th scope="row">${esc(fmtDate(d.date, "medium"))}</th><td>${esc(fmtInt(d.fresh))}</td><td>${esc(fmtInt(d.seen))}</td><td>${esc(fmtInt(d.total))}</td></tr>`).join("");
  return `
    <p class="legend">
      <span class="legend-item"><span class="key key-new" aria-hidden="true"></span>new headlines</span>
      <span class="legend-item"><span class="key key-seen" aria-hidden="true"></span>seen again</span>
      <span class="legend-item"><span class="key-ring" aria-hidden="true"></span>no run that day</span>
    </p>
    <div class="colchart">
      <div class="colchart-axis" aria-hidden="true">
        <span style="top:0%">${esc(fmtInt(v.max))}</span>
        <span style="top:50%">${esc(Number.isInteger(half) ? fmtInt(half) : half.toFixed(1))}</span>
        <span style="top:100%">0</span>
      </div>
      <div class="colchart-plot" style="--n:${v.days.length}">
        <span class="colchart-grid" style="top:0"></span>
        <span class="colchart-grid" style="top:50%"></span>
        ${slots}
      </div>
      <div class="colchart-dates" aria-hidden="true">
        <span>${esc(fmtDate(v.days[0].date))}</span><span>${esc(fmtDate(v.days[v.days.length - 1].date))}</span>
      </div>
    </div>
    <details class="data-details"><summary>Show the numbers</summary><div class="table-scroll">
      <table class="data-table"><caption class="sr-only">Headlines per run date: new, seen again and total</caption>
        <thead><tr><th scope="col">Run date</th><th scope="col">New</th><th scope="col">Seen again</th><th scope="col">Total</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div></details>`;
}

function describeIngest(v, el) {
  const d = v.days[Number(el.dataset.i)];
  if (!d) return {};
  const title = fmtDate(d.date, "weekday");
  if (!d.run) {
    return { title, rows: [], note: d.before ? "Before the first run in this report." : "No run recorded that day." };
  }
  return {
    title,
    rows: [
      { key: "key key-new", label: "new", value: fmtInt(d.fresh) },
      { key: "key key-seen", label: "seen again", value: fmtInt(d.seen) },
      { label: "total", value: fmtInt(d.total) },
    ],
  };
}


// ---------------------------------------------------------------- history and sources

function barRowsHTML(items, { max, href = null, value, sub = null, label }) {
  return items.map((item) => {
    const name = String(label(item));
    const link = href
      ? `<a class="bar-name" href="${esc(href(item))}">${esc(name)}</a>`
      : `<span class="bar-name" title="${esc(name)}">${esc(name)}</span>`;
    const width = max ? ((Number(value(item)) || 0) / max) * 100 : 0;
    return `<div class="bar-row has-name">${link}
        <span class="bar-track"><span class="bar-fill" style="width:${width.toFixed(2)}%"></span></span>
        <span class="bar-value"><strong>${esc(fmtInt(value(item)))}</strong>${sub ? ` <span class="muted">${esc(sub(item))}</span>` : ""}</span>
      </div>`;
  }).join("");
}

function historyHTML(status) {
  const h = status.history || {};
  const sentiment = h.sentiment && typeof h.sentiment === "object" ? h.sentiment : {};
  const range = h.first_run_date && h.last_run_date
    ? `${fmtDate(h.first_run_date, "short")} to ${fmtDate(h.last_run_date, "short")}`
    : "";
  const tiles = [
    statHTML("Headlines", int(h.headlines), "story and topic rows"),
    statHTML("Run days", int(h.run_days), range),
    ...ordered(Object.keys(sentiment)).map((m) => statHTML(`Scored, ${modelName(m)}`, int(sentiment[m]), "stories")),
    statHTML("Kept out", int(h.excluded_low_quality), "low quality titles"),
    statHTML("Parquet files", int(h.parquet_files), "monthly files"),
  ].join("");
  const topics = Array.isArray(status.topics) ? status.topics : [];
  const max = Math.max(0, ...topics.map((t) => Number(t.total) || 0));
  const topicBlock = topics.length
    ? `<h3 class="rail-title sub-title">By topic <span class="rail-title-note">in the history, today's edition in brackets</span></h3>
      <div class="bars">${barRowsHTML(topics, {
    max,
    label: (t) => t.label ?? "Topic",
    href: (t) => `index.html#${slug(t.label)}`,
    value: (t) => t.total,
    sub: (t) => `[${fmtInt(t.edition ?? 0)}]`,
  })}</div>`
    : "";
  return `<div class="stats">${tiles}</div>${topicBlock}`;
}

function sourcesHTML(status) {
  const sources = (Array.isArray(status.sources) ? status.sources : []).filter((s) => s && s.source);
  if (!sources.length) return null;
  const max = Math.max(0, ...sources.map((s) => Number(s.n) || 0));
  return `<div class="bars">${barRowsHTML(sources, { max, label: (s) => s.source, value: (s) => s.n })}</div>`;
}


// ---------------------------------------------------------------- load

async function load() {
  els.state.innerHTML = stateHTML({ kind: "loading", title: "Loading the status report" });
  const data = await loadAll(["news", "trends", "agreement", "status"]);
  hydrateChrome(data);

  const status = data.status;
  if (!status) {
    const reason = data.errors.status ? ` (${data.errors.status.message || data.errors.status})` : "";
    els.note.textContent = "No status report yet.";
    els.state.innerHTML = stateHTML({
      kind: "error",
      title: "The status report is not available",
      detail: `status.json could not be loaded${reason}. The pipeline writes it on every run: `,
      html: "<code>py -m why run</code>.",
    });
    return;
  }

  const now = Date.now();
  els.state.innerHTML = "";
  els.note.textContent = status.generated_at
    ? `Read from status.json, written ${fmtDateTime(status.generated_at)}${status.version ? ` by version ${status.version}` : ""}.`
    : "Read from status.json.";

  els.run.innerHTML = runCardHTML(status, now);
  els.side.innerHTML = sideHTML(status, now);
  els.runBlock.hidden = false;

  const ingest = ingestView(status);
  els.ingestBlock.hidden = false;
  if (ingest) {
    els.ingestNote.textContent = `Headlines per run date over the last ${ingest.days.length} days: stories stored for the first time and stories seen on an earlier run. `
      + `${fmtInt(ingest.runs)} ${ingest.runs === 1 ? "run" : "runs"} in this report.`;
    els.ingest.innerHTML = ingestHTML(ingest);
    markTips(els.ingest.querySelector(".colchart-plot"), {
      selector: ".col-slot",
      start: () => ingest.days.length - 1,
      label: "Headlines per run date, new and seen again",
      describe: (el) => describeIngest(ingest, el),
    });
  } else {
    els.ingestNote.textContent = "";
    els.ingest.innerHTML = '<p class="rail-empty">No daily counts in this report yet.</p>';
  }

  els.historyBlock.hidden = false;
  els.historyNote.textContent = "Everything stored so far. Low quality titles stay in the raw files but never reach an export.";
  els.history.innerHTML = historyHTML(status);

  const sources = sourcesHTML(status);
  els.sourcesBlock.hidden = false;
  els.sourcesNote.textContent = sources ? "Publishers with the most distinct stories in the history." : "";
  els.sources.innerHTML = sources || '<p class="rail-empty">No sources in this report yet.</p>';
}

load();
