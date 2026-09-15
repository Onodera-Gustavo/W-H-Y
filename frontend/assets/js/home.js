// Today: the mood strip, the topic tabs with hash routing, and each topic's stories and rail.

import {
  LABELS, esc, fmtDate, fmtDateTime, fmtInt, fmtPercent, hydrateChrome, labelClass, labelFor,
  loadAll, modelName, mountChrome, prefersReducedMotion, primaryModelOf, relTime, safeUrl,
  signed, slug, stateHTML,
} from "./common.js";
import { divergingMeter, labelBar, seriesClass, sparkline, trendChart, trendTable } from "./charts.js";

mountChrome({ page: "today" });

const els = {
  mood: document.getElementById("mood"),
  moodGrid: document.getElementById("mood-grid"),
  moodLede: document.getElementById("mood-lede"),
  moodNote: document.getElementById("mood-note"),
  topics: document.getElementById("topics"),
  tabs: document.getElementById("topic-tabs"),
  panel: document.getElementById("topic-panel"),
};

const BASE_TITLE = document.title;
const TODAY_DAYS = 14;
const state = { ctx: null, topics: [], selected: null, chart: null };


// ---------------------------------------------------------------- model

function scoreOf(article, model) {
  const s = article?.scores?.[model];
  if (!s || s.score === null || s.score === undefined) return null;
  const score = Number(s.score);
  return Number.isFinite(score) ? { label: s.label, score } : null;
}

const mean = (xs) => xs.reduce((sum, v) => sum + v, 0) / xs.length;

function modelsOf(news, primary) {
  const set = new Set(primary ? [primary] : []);
  (news.models || []).forEach((m) => set.add(m));
  for (const topic of news.topics || []) {
    for (const a of topic.articles || []) Object.keys(a.scores || {}).forEach((m) => set.add(m));
  }
  return [...set];
}

/** Edition average for the first model (primary first) that scored any story of the topic. */
function moodOf(articles, models) {
  for (const model of models) {
    const scores = articles.map((a) => scoreOf(a, model)).filter(Boolean);
    if (scores.length) {
      return {
        model,
        avg: mean(scores.map((s) => s.score)),
        n: scores.length,
        of: articles.length,
        fallback: model !== models[0],
      };
    }
  }
  return null;
}

function countLabels(articles, model) {
  const counts = { positive: 0, neutral: 0, negative: 0, n: 0 };
  for (const a of articles) {
    const s = scoreOf(a, model);
    if (s && LABELS.includes(s.label)) {
      counts[s.label] += 1;
      counts.n += 1;
    }
  }
  return counts;
}

function disagreementOf(articles, [a, b]) {
  if (!a || !b) return null;
  const both = articles.filter((x) => scoreOf(x, a) && scoreOf(x, b));
  const differ = both.filter((x) => scoreOf(x, a).label !== scoreOf(x, b).label);
  return { n: both.length, differ: differ.length, ids: new Set(differ.map((x) => x.id)), marks: both.map((x) => differ.includes(x)) };
}

function trendOf(topicTrend, trends, models) {
  if (!topicTrend?.series?.length) return null;
  // trends.json may hold a longer window (the Trends page uses it); Today shows the last 14 days
  const points = topicTrend.series.slice(-TODAY_DAYS);
  const available = trends.models || [];
  const order = [...new Set([...models.filter((m) => available.includes(m)), ...available])];
  const series = order.map((m) => ({
    id: m,
    name: modelName(m),
    values: points.map((p) => {
      const avg = p.sentiment?.[m]?.avg;
      return avg === null || avg === undefined || !Number.isFinite(Number(avg)) ? null : Number(avg);
    }),
    n: points.map((p) => p.sentiment?.[m]?.n ?? 0),
  }));
  return {
    dates: points.map((p) => p.date),
    series,
    counts: points.map((p) => Number(p.count) || 0),
    days: points.length,
  };
}

function buildContext(data) {
  const { news, trends, agreement } = data;
  const primary = primaryModelOf(news, trends);
  const models = modelsOf(news, primary);
  // the pair every story is compared on: the two models in the edition, FinBERT and VADER by default
  const pair = [...new Set([...models, "finbert", "vader"])].slice(0, 2);
  const trendTopics = trends?.topics || [];
  const topics = (news.topics || []).map((t) => {
    const articles = Array.isArray(t.articles) ? t.articles : [];
    const label = String(t.label ?? "Topic");
    return {
      label,
      query: t.query || "",
      slug: slug(label),
      articles,
      mood: moodOf(articles, models.length ? models : pair),
      mix: pair.map((model) => ({ model, counts: countLabels(articles, model) })),
      disagreement: disagreementOf(articles, pair),
      trend: trends ? trendOf(trendTopics.find((x) => x.label === t.label), trends, models) : null,
    };
  });
  const days = Math.min(Number(trends?.days) || TODAY_DAYS, TODAY_DAYS);
  return { news, trends, agreement, primary, models, pair, topics, days };
}


// ---------------------------------------------------------------- mood strip

function moodCellHTML(topic, i, ctx) {
  const m = topic.mood;
  const tone = m ? labelFor(m.avg) : null;
  const spark = topic.trend?.series.find((s) => s.id === ctx.primary) || topic.trend?.series[0];
  const days = topic.trend?.days || ctx.days;
  const value = m ? signed(m.avg) : "n/a";
  const word = tone || "unscored";
  const coverage = !topic.articles.length
    ? "no stories"
    : m && m.n < m.of ? `${m.n} of ${m.of} scored` : `${topic.articles.length} stories`;
  const modelTag = m?.fallback ? `<span class="tag">${esc(modelName(m.model))}</span>` : "";
  const aria = m
    ? `${topic.label}: average ${modelName(m.model)} score ${value}, ${word}, ${coverage}`
    : `${topic.label}: no scores yet`;
  return `
    <a class="mood-cell ${labelClass(tone)} rise" style="--i:${i}" href="#${esc(topic.slug)}"
       data-topic="${esc(topic.slug)}" aria-label="${esc(aria)}">
      <span class="mood-cell-top">
        <span class="mood-topic">${esc(topic.label)}</span>${modelTag}
      </span>
      <span class="mood-value">
        <span class="mood-number">${esc(value)}</span>
        <span class="mood-word">${esc(word)}</span>
      </span>
      ${divergingMeter(m?.avg ?? null, { width: 160, height: 6, className: "mood-meter" })}
      <span class="mood-spark">${sparkline(spark?.values || [], { width: 160, height: 30 })}</span>
      <span class="mood-foot"><span>${esc(coverage)}</span><span>${esc(days)} days</span></span>
    </a>`;
}

function placeholderCells() {
  return Array.from({ length: 6 }, () => `
    <div class="mood-cell is-placeholder" aria-hidden="true">
      <span class="mood-cell-top"><span class="mood-topic">&nbsp;</span></span>
      <span class="mood-value"><span class="mood-number">&middot;</span></span>
      ${divergingMeter(null, { width: 160, height: 6, className: "mood-meter" })}
      <span class="mood-spark">${sparkline(new Array(14).fill(null), { width: 160, height: 30 })}</span>
      <span class="mood-foot"><span>&nbsp;</span></span>
    </div>`).join("");
}

function moodLedeHTML(ctx) {
  const scored = ctx.topics.filter((t) => t.mood && !t.mood.fallback);
  if (scored.length < 2) return "";
  const sorted = [...scored].sort((a, b) => b.mood.avg - a.mood.avg);
  const hi = sorted[0];
  const lo = sorted[sorted.length - 1];
  if (hi.mood.avg === lo.mood.avg) return "";
  const phrase = (t) => `<strong>${esc(t.label)}</strong> <span class="num">${esc(signed(t.mood.avg))}</span>`;
  const top = labelFor(hi.mood.avg) === "positive" ? "the most positive" : "the least negative";
  const bottom = labelFor(lo.mood.avg) === "negative" ? "the most negative" : "the least positive";
  return `By ${esc(modelName(ctx.primary))}'s average score, ${phrase(hi)} read ${top} in this edition `
    + `and ${phrase(lo)} ${bottom}.`;
}


// ---------------------------------------------------------------- topic panel

function metaHTML(a) {
  const time = a.published
    ? `<span class="sep" aria-hidden="true">&middot;</span><time datetime="${esc(a.published)}" title="${esc(fmtDateTime(a.published))}">${esc(relTime(a.published))}</time>`
    : "";
  return `<p class="story-meta"><span class="story-source">${esc(a.source || "Unknown source")}</span>${time}</p>`;
}

function scoreCardHTML(a, model) {
  const s = scoreOf(a, model);
  const shown = a.sentiment?.model === model;
  const name = esc(modelName(model));
  if (!s) {
    return `<div class="score-card is-missing">
        <p class="score-card-model">${name}</p>
        <p class="score-card-value"><span class="score-card-number">Not scored yet</span></p>
        ${divergingMeter(null, { width: 200 })}
      </div>`;
  }
  return `<div class="score-card ${labelClass(s.label)}">
      <p class="score-card-model">${name}${shown ? '<span class="tag">on badge</span>' : ""}</p>
      <p class="score-card-value">
        <span class="score-card-number">${esc(signed(s.score))}</span>
        <span class="score-card-label">${esc(s.label)}</span>
      </p>
      ${divergingMeter(s.score, { width: 200, label: s.label })}
    </div>`;
}

function leadHTML(a, topic, ctx) {
  const disagree = topic.disagreement?.ids.has(a.id);
  return `
    <article class="lead rise" aria-labelledby="lead-title">
      <p class="lead-kicker">
        <span class="kicker">Lead story</span>
        ${disagree ? '<span class="chip chip--alert">Models disagree</span>' : ""}
      </p>
      <h3 class="lead-title" id="lead-title">
        <a href="${esc(safeUrl(a.link))}" target="_blank" rel="noopener noreferrer">${esc(a.title)}</a>
      </h3>
      ${metaHTML(a)}
      <div class="score-pair">${ctx.pair.map((m) => scoreCardHTML(a, m)).join("")}</div>
    </article>`;
}

function badgeHTML(a, ctx, uid, disagree) {
  const s = a.sentiment;
  const score = s ? Number(s.score) : NaN;
  if (!s || s.score === null || !Number.isFinite(score)) {
    return '<span class="badge is-pending">unscored</span>';
  }
  const fallback = ctx.primary && s.model !== ctx.primary;
  const tipId = `tip-${uid}`;
  const rows = ctx.pair.map((m) => {
    const sc = scoreOf(a, m);
    // spaces and the hidden period keep the tooltip readable as a description for screen readers
    if (!sc) {
      return `<span class="tip-row is-missing"><span class="tip-model">${esc(modelName(m))}</span> `
        + '<span class="tip-label">not scored yet</span><span class="tip-score"></span><span class="sr-only">. </span></span>';
    }
    return `<span class="tip-row ${labelClass(sc.label)}"><span class="tip-model">${esc(modelName(m))}</span> `
      + `<span class="tip-label">${esc(sc.label)}</span> <span class="tip-score">${esc(signed(sc.score))}</span>`
      + `${divergingMeter(sc.score, { width: 200, height: 4, label: sc.label })}<span class="sr-only">. </span></span>`;
  }).join("");
  const note = disagree ? '<span class="tip-note">The two models disagree on this headline.</span>' : "";
  return `
    <button class="badge ${labelClass(s.label)}" type="button" aria-expanded="false" aria-describedby="${tipId}">
      <span class="badge-label">${esc(s.label)}</span>
      <span class="badge-score">${esc(signed(score))}</span>
      ${divergingMeter(score, { width: 28, height: 6, label: s.label, className: "badge-meter" })}
      ${fallback ? `<span class="badge-model">${esc(modelName(s.model))}</span>` : ""}
    </button>
    <span class="tip" role="tooltip" id="${tipId}"><span class="tip-title">Both models<span class="sr-only">: </span></span>${rows}${note}</span>`;
}

function storyHTML(a, topic, ctx, i) {
  const disagree = topic.disagreement?.ids.has(a.id);
  return `
    <li class="story rise" style="--i:${i + 1}">
      <h3 class="story-title">
        <a class="story-link" href="${esc(safeUrl(a.link))}" target="_blank" rel="noopener noreferrer">${esc(a.title)}</a>
      </h3>
      <div class="story-foot">
        ${metaHTML(a)}
        <div class="story-badge">${badgeHTML(a, ctx, `${topic.slug}-${i}`, disagree)}</div>
      </div>
    </li>`;
}

function mixHTML(topic) {
  const total = topic.articles.length;
  const rows = topic.mix.map(({ model, counts }) => {
    const name = esc(modelName(model));
    if (!counts.n) {
      return `<div class="mix-row is-empty">
          <p class="mix-head"><span class="mix-model">${name}</span><span class="mix-n">0 of ${total}</span></p>
          ${labelBar({})}
          <p class="mix-counts">No ${name} scores in this edition yet.</p>
        </div>`;
    }
    const legend = LABELS.map((l) =>
      `<span class="mix-count"><span class="key is-${l}" aria-hidden="true"></span>${counts[l]} ${l}</span>`).join("");
    return `<div class="mix-row">
        <p class="mix-head"><span class="mix-model">${name}</span><span class="mix-n">${counts.n} of ${total} scored</span></p>
        ${labelBar(counts)}
        <p class="mix-counts">${legend}</p>
      </div>`;
  }).join("");
  return `<section class="rail-block" aria-labelledby="mix-title">
      <h3 class="rail-title" id="mix-title">Label mix <span class="rail-title-note">this edition</span></h3>
      ${rows}
    </section>`;
}

function trendBlockHTML(topic, ctx) {
  const t = topic.trend;
  const days = t?.days || ctx.days;
  if (!t || !t.series.length) {
    return `<section class="rail-block" aria-labelledby="trend-title">
        <h3 class="rail-title" id="trend-title">${esc(days)}-day trend</h3>
        <p class="rail-empty">No trend data yet. It fills in as daily runs add up.</p>
      </section>`;
  }
  const legend = t.series.map((s) =>
    `<span class="legend-item"><span class="key-line ${seriesClass(s.id)}" aria-hidden="true"></span>${esc(s.name)}</span>`).join("");
  const total = t.counts.reduce((sum, c) => sum + c, 0);
  const active = t.counts.filter((c) => c > 0).length;
  return `<section class="rail-block" aria-labelledby="trend-title">
      <h3 class="rail-title" id="trend-title">${esc(days)}-day trend
        <span class="rail-title-note">${esc(fmtDate(t.dates[0]))} to ${esc(fmtDate(t.dates[t.dates.length - 1]))}</span>
      </h3>
      <p class="legend">${legend}<span class="legend-item"><span class="key key-count" aria-hidden="true"></span>headlines</span></p>
      <div class="trend" data-trend></div>
      <p class="rail-caption">Daily average score. ${esc(fmtInt(total))} headlines on ${active} ${active === 1 ? "day" : "days"} with data.</p>
      ${trendTable(t, { caption: `${topic.label}: daily average score and headlines` })}
    </section>`;
}

function disagreeHTML(topic, ctx) {
  const d = topic.disagreement;
  const [a, b] = ctx.pair.map(modelName);
  let body;
  if (d && d.n) {
    const tally = d.marks.map((differ) => `<span class="tally-mark${differ ? " is-differ" : ""}"></span>`).join("");
    body = `<p class="figure"><span class="figure-value">${d.differ}</span><span class="figure-of">of ${d.n}</span></p>
      <p class="figure-caption">Models disagree on ${d.differ} of ${d.n}: stories where ${esc(a)} and ${esc(b)} gave ${esc(topic.label)} headlines different labels.</p>
      <div class="tally" role="img" aria-label="${d.differ} of ${d.n} stories with different labels">${tally}</div>`;
  } else {
    body = `<p class="figure-caption">No ${esc(topic.label)} story in this edition has both a ${esc(a)} and a ${esc(b)} score yet, so there is nothing to compare.</p>`;
  }
  const r = ctx.agreement;
  const overall = r?.n && Number.isFinite(Number(r.percent_agreement))
    ? `<p class="rail-caption">Across all ${esc(fmtInt(r.n))} headlines both models scored, they agree ${esc(fmtPercent(r.percent_agreement))} of the time.</p>`
    : "";
  return `<section class="rail-block" aria-labelledby="check-title">
      <h3 class="rail-title" id="check-title">Model check</h3>
      ${body}${overall}
      <a class="text-link" href="models.html">Open the Model Lab</a>
    </section>`;
}

function panelHTML(topic, ctx) {
  const count = topic.articles.length;
  const head = `
    <header class="topic-head">
      <h2 class="topic-title">${esc(topic.label)}</h2>
      <p class="topic-meta">${topic.query ? `<span class="nowrap">Search &ldquo;${esc(topic.query)}&rdquo;</span> <span class="sep" aria-hidden="true">/</span> ` : ""}<span class="nowrap">${count} ${count === 1 ? "story" : "stories"}</span> <span class="sep" aria-hidden="true">/</span> <span class="nowrap">${esc(ctx.news.date_label || "")}</span></p>
    </header>`;
  if (!count) {
    return head + stateHTML({
      kind: "empty",
      title: `No ${topic.label} stories in this edition`,
      detail: "The feed returned nothing for this topic on the last run.",
    });
  }
  const [lead, ...rest] = topic.articles;
  return `${head}
    <div class="topic-layout">
      <div class="topic-main">
        ${leadHTML(lead, topic, ctx)}
        ${rest.length ? `<ol class="stories" aria-label="More ${esc(topic.label)} stories">${rest.map((a, i) => storyHTML(a, topic, ctx, i)).join("")}</ol>` : ""}
      </div>
      <aside class="rail" aria-label="${esc(topic.label)} analysis">
        ${mixHTML(topic)}
        ${trendBlockHTML(topic, ctx)}
        ${disagreeHTML(topic, ctx)}
      </aside>
    </div>`;
}


// ---------------------------------------------------------------- selection and routing

function topicFromHash() {
  const raw = decodeURIComponent(location.hash.replace(/^#/, "")).toLowerCase();
  return state.topics.find((t) => t.slug === raw)?.slug || null;
}

/** Scroll the tab strip sideways so the tab is visible, without moving the page. */
function revealTab(tab) {
  const strip = els.tabs;
  const left = tab.getBoundingClientRect().left - strip.getBoundingClientRect().left + strip.scrollLeft;
  const right = left + tab.offsetWidth;
  if (left < strip.scrollLeft) strip.scrollLeft = Math.max(0, left - 16);
  else if (right > strip.scrollLeft + strip.clientWidth) strip.scrollLeft = right - strip.clientWidth + 16;
}

function select(slugValue,{ history: mode = null, focusTab = false, scroll = false } = {}) {
  const topic = state.topics.find((t) => t.slug === slugValue) || state.topics[0];
  if (!topic) return;
  state.selected = topic.slug;

  els.tabs.querySelectorAll('[role="tab"]').forEach((tab) => {
    const on = tab.dataset.topic === topic.slug;
    tab.setAttribute("aria-selected", String(on));
    tab.tabIndex = on ? 0 : -1;
    if (on && focusTab) tab.focus({ preventScroll: true });
    if (on) revealTab(tab);
  });
  els.moodGrid.querySelectorAll("[data-topic]").forEach((cell) => {
    if (cell.dataset.topic === topic.slug) cell.setAttribute("aria-current", "true");
    else cell.removeAttribute("aria-current");
  });

  state.chart?.destroy();
  els.panel.setAttribute("aria-labelledby", `tab-${topic.slug}`);
  els.panel.innerHTML = panelHTML(topic, state.ctx);
  const chartBox = els.panel.querySelector("[data-trend]");
  state.chart = chartBox && topic.trend
    ? trendChart(chartBox, { ...topic.trend, label: `${topic.label}, daily average score by model` })
    : null;

  document.title = `${topic.label} | ${BASE_TITLE}`;
  if (mode === "push") history.pushState({ topic: topic.slug }, "", `#${topic.slug}`);
  if (mode === "replace") history.replaceState({ topic: topic.slug }, "", `#${topic.slug}`);

  if (scroll) {
    const top = els.topics.getBoundingClientRect().top;
    if (top < 0 || top > window.innerHeight * 0.7) {
      els.topics.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
    }
  }
}

/** Fade the edge of the tab strip that hides more tabs (phones). */
function updateTabFade() {
  const strip = els.tabs;
  const max = strip.scrollWidth - strip.clientWidth;
  strip.classList.toggle("is-clipped-start", strip.scrollLeft > 2);
  strip.classList.toggle("is-clipped-end", max - strip.scrollLeft > 2);
}

function syncFromHash() {
  const target = topicFromHash();
  if (target && target !== state.selected) select(target, { scroll: true });
}

function closeTips(except = null) {
  els.panel.querySelectorAll('button.badge[aria-expanded="true"]').forEach((b) => {
    if (b !== except) b.setAttribute("aria-expanded", "false");
  });
}

function wireEvents() {
  els.tabs.addEventListener("click", (event) => {
    const tab = event.target.closest('[role="tab"]');
    if (tab && tab.dataset.topic !== state.selected) select(tab.dataset.topic, { history: "push" });
  });

  els.tabs.addEventListener("keydown", (event) => {
    const keys = ["ArrowRight", "ArrowLeft", "Home", "End"];
    if (!keys.includes(event.key) || !state.topics.length) return;
    event.preventDefault();
    const last = state.topics.length - 1;
    const i = state.topics.findIndex((t) => t.slug === state.selected);
    const j = event.key === "Home" ? 0
      : event.key === "End" ? last
        : event.key === "ArrowRight" ? (i + 1) % (last + 1)
          : (i - 1 + last + 1) % (last + 1);
    select(state.topics[j].slug, { history: "replace", focusTab: true });
  });

  els.moodGrid.addEventListener("click", (event) => {
    const cell = event.target.closest("a[data-topic]");
    if (!cell || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button) return;
    event.preventDefault();
    const same = cell.dataset.topic === state.selected;
    select(cell.dataset.topic, { history: same ? null : "push", scroll: true });
  });

  els.panel.addEventListener("click", (event) => {
    const badge = event.target.closest("button.badge");
    closeTips(badge);
    if (badge) {
      els.panel.classList.remove("tips-off"); // Safari does not focus buttons on click
      const open = badge.getAttribute("aria-expanded") === "true";
      badge.setAttribute("aria-expanded", String(!open));
    }
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest?.(".story-badge")) closeTips();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    closeTips();
    els.panel.classList.add("tips-off");
  });
  els.panel.addEventListener("focusin", () => els.panel.classList.remove("tips-off"));
  els.panel.addEventListener("pointerover", (event) => {
    if (event.target.closest(".story-badge")) els.panel.classList.remove("tips-off");
  });

  els.tabs.addEventListener("scroll", updateTabFade, { passive: true });
  window.addEventListener("resize", updateTabFade, { passive: true });
  window.addEventListener("hashchange", syncFromHash);
  window.addEventListener("popstate", syncFromHash);
}


// ---------------------------------------------------------------- load

function showError(title, detail, html = "") {
  els.mood.hidden = true;
  els.tabs.hidden = true;
  els.panel.removeAttribute("aria-labelledby");
  els.panel.innerHTML = stateHTML({ kind: "error", title, detail, html });
}

async function load() {
  els.moodGrid.innerHTML = placeholderCells();
  els.panel.innerHTML = stateHTML({ kind: "loading", title: "Loading yesterday's edition" });

  const data = await loadAll(["news", "trends", "agreement", "status"]);
  hydrateChrome(data);

  if (!data.news) {
    const reason = data.errors.news ? ` (${data.errors.news.message || data.errors.news})` : "";
    showError("No edition yet", `The daily export could not be loaded${reason}. Build one locally with `,
      "<code>py -m why run</code>.");
    return;
  }

  try {
    state.ctx = buildContext(data);
  } catch (err) {
    showError("This edition could not be read", String(err?.message || err));
    return;
  }
  state.topics = state.ctx.topics;
  if (!state.topics.length) {
    showError("The edition is empty", "The last run produced no topics.");
    return;
  }

  const ctx = state.ctx;
  const lede = moodLedeHTML(ctx);
  els.moodLede.innerHTML = lede;
  els.moodLede.hidden = !lede;
  els.moodNote.textContent = ctx.primary
    ? `Average ${modelName(ctx.primary)} score of each topic's stories, from -1 to +1. Lines show the last ${ctx.days} days.`
    : "Headlines have not been scored yet.";
  els.moodGrid.innerHTML = state.topics.map((t, i) => moodCellHTML(t, i, ctx)).join("");

  els.tabs.innerHTML = state.topics.map((t) => `
    <button class="tab" type="button" role="tab" id="tab-${esc(t.slug)}" data-topic="${esc(t.slug)}"
            aria-controls="topic-panel" aria-selected="false" tabindex="-1">
      <span class="tab-dot ${labelClass(t.mood ? labelFor(t.mood.avg) : null)}" aria-hidden="true"></span>${esc(t.label)}
    </button>`).join("");

  const fromHash = topicFromHash();
  select(fromHash || state.topics[0].slug);
  updateTabFade();
  if (fromHash) {
    const top = els.topics.getBoundingClientRect().top;
    if (top > window.innerHeight * 0.75) els.topics.scrollIntoView({ block: "start" });
  }
}

wireEvents();
load();
