// WHY shared module: data loading, escaping, formatting, theme and the site chrome
// (masthead, edition bar, nav, footer) used by every page. No build step, plain ES module.

export const SITE = {
  name: "WHY",
  tagline: "What Happened Yesterday",
  url: "https://onodera-gustavo.github.io/W-H-Y/",
  repo: "https://github.com/Onodera-Gustavo/W-H-Y",
  schedule: "Daily at 09:00 UTC",
};

export const PAGES = [
  { id: "today", href: "index.html", label: "Today" },
  { id: "trends", href: "trends.html", label: "Trends" },
  { id: "models", href: "models.html", label: "Model Lab" },
  { id: "pipeline", href: "pipeline.html", label: "Pipeline" },
];

export const MODEL_NAMES = { vader: "VADER", finbert: "FinBERT" };
export const LABELS = ["positive", "neutral", "negative"];
// same cut points the pipeline uses for VADER's compound score; used for averages
export const LABEL_CUTS = { positive: 0.05, negative: -0.05 };

// Relative URLs only: the site lives under a subpath on GitHub Pages.
export const SOURCES = {
  news: { api: "api/news", file: "data/latest.json" },
  trends: { api: "api/trends", file: "data/trends.json" },
  agreement: { api: "api/agreement", file: "data/model_agreement.json" },
  status: { api: "api/status", file: "data/status.json" },
};


// ---------------------------------------------------------------- escaping

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

/** Everything that comes from the feed goes through esc() before reaching innerHTML. */
export const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ESC[ch]);

/** Only http and https links survive; anything else becomes "#". */
export function safeUrl(value) {
  try {
    const url = new URL(value, location.href);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : "#";
  } catch {
    return "#";
  }
}


// ---------------------------------------------------------------- formatting

export const modelName = (id) => MODEL_NAMES[id] || String(id ?? "");

/** "positive" | "neutral" | "negative" for a score, null when it is not a number. */
export function labelFor(score) {
  if (score === null || score === undefined || score === "") return null;
  const n = Number(score);
  if (!Number.isFinite(n)) return null;
  if (n >= LABEL_CUTS.positive) return "positive";
  if (n <= LABEL_CUTS.negative) return "negative";
  return "neutral";
}

/** CSS tone class for a label: is-positive, is-neutral, is-negative or is-pending. */
export const labelClass = (label) => (LABELS.includes(label) ? `is-${label}` : "is-pending");

/** "+0.32", "-0.18", "0.00". Empty string for anything that is not a number. */
export function signed(score, digits = 2) {
  if (score === null || score === undefined || score === "") return "";
  const n = Number(score);
  if (!Number.isFinite(n)) return "";
  const text = Math.abs(n).toFixed(digits);
  if (Number(text) === 0) return (0).toFixed(digits);
  return (n > 0 ? "+" : "-") + text;
}

const INT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

export function fmtInt(value) {
  const n = Number(value);
  return value === null || value === undefined || !Number.isFinite(n) ? "" : INT.format(n);
}

/** 52.08 -> "52%". The value is already a percentage (0 to 100). */
export function fmtPercent(value, digits = 0) {
  const n = Number(value);
  return value === null || value === undefined || !Number.isFinite(n) ? "" : `${n.toFixed(digits)}%`;
}

function toDate(value) {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return new Date(`${value}T00:00:00Z`); // a calendar day, not a local midnight
  }
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

const DATE_STYLES = {
  short: { month: "short", day: "numeric" },
  medium: { month: "short", day: "numeric", year: "numeric" },
  weekday: { weekday: "short", month: "short", day: "numeric", year: "numeric" },
  long: { weekday: "long", month: "long", day: "numeric", year: "numeric" },
};

/** Dates are shown in UTC, the pipeline's calendar. style: short | medium | weekday | long. */
export function fmtDate(value, style = "short") {
  const d = toDate(value);
  if (!d) return "";
  return d.toLocaleDateString("en-US", { ...(DATE_STYLES[style] || DATE_STYLES.short), timeZone: "UTC" });
}

/** "Sep 15, 14:44 UTC" */
export function fmtDateTime(value) {
  const d = toDate(value);
  if (!d) return "";
  const text = d.toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "UTC",
  });
  return `${text} UTC`;
}

/** "just now", "12m ago", "3h ago", otherwise a short date. */
export function relTime(value, now = Date.now()) {
  const d = toDate(value);
  if (!d) return "";
  const minutes = Math.floor((now - d.getTime()) / 60000);
  if (minutes < 1 && minutes > -5) return "just now";
  if (minutes >= 1 && minutes < 60) return `${minutes}m ago`;
  if (minutes >= 60 && minutes < 1440) return `${Math.floor(minutes / 60)}h ago`;
  return fmtDate(d, "short");
}

/** Same rule as why.config.slug: "Model Lab" -> "model-lab". Used for #hash routes. */
export function slug(label) {
  return String(label ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "topic";
}

export const prefersReducedMotion = () =>
  typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;


// ---------------------------------------------------------------- data loading

export class DataError extends Error {
  constructor(message, { status = null, url = null } = {}) {
    super(message);
    this.name = "DataError";
    this.status = status;
    this.url = url;
  }
}

// "api" on the local Flask server, "file" on GitHub Pages or any static server.
let sourceMode = location.hostname.endsWith("github.io") ? "file" : null;
let probe = null;

/** One HEAD request per page load decides whether /api exists, so static hosts log one 404 at most. */
function detectSource() {
  if (sourceMode) return Promise.resolve(sourceMode);
  probe ??= fetch(SOURCES.news.api, { method: "HEAD", cache: "no-store" })
    .then((res) => (res.status === 404 || res.status === 405 ? "file" : "api"), () => "file")
    .then((mode) => (sourceMode = mode));
  return probe;
}

async function fetchJSON(url, cache) {
  const res = await fetch(url, { cache, headers: { Accept: "application/json" } });
  if (!res.ok) throw new DataError(`HTTP ${res.status} on ${url}`, { status: res.status, url });
  return res.json();
}

/**
 * Load one export. kind: "news" | "trends" | "agreement" | "status".
 * API first on the local server, data/*.json as the fallback (the only source on Pages).
 */
export async function loadJSON(kind, { force = false } = {}) {
  const src = SOURCES[kind];
  if (!src) throw new DataError(`unknown data kind "${kind}"`);
  const mode = await detectSource();
  const urls = mode === "api" ? [src.api, src.file] : [src.file];
  const cache = force ? "reload" : "no-cache";
  let firstError = null;
  for (const url of urls) {
    try {
      return await fetchJSON(url, cache);
    } catch (err) {
      firstError ??= err;
    }
  }
  throw firstError;
}

/** Load several kinds at once. Missing ones come back as null, with the reason in errors. */
export async function loadAll(kinds = ["news", "trends", "agreement", "status"], options = {}) {
  const results = await Promise.allSettled(kinds.map((kind) => loadJSON(kind, options)));
  const out = { errors: {} };
  kinds.forEach((kind, i) => {
    const r = results[i];
    out[kind] = r.status === "fulfilled" ? r.value : null;
    if (r.status === "rejected") out.errors[kind] = r.reason;
  });
  return out;
}

/** Edition number: status.json history.run_days when present, else days with headlines in trends. */
export function editionNumber(status, trends) {
  const runDays = status?.history?.run_days;
  if (Array.isArray(runDays)) return runDays.length || null;
  if (typeof runDays === "number" && Number.isFinite(runDays)) return runDays;
  const days = new Set();
  for (const topic of trends?.topics || []) {
    for (const point of topic.series || []) if (point.count > 0) days.add(point.date);
  }
  return days.size || null;
}

export const primaryModelOf = (news, trends) => news?.primary_model || trends?.primary_model || null;


// ---------------------------------------------------------------- theme

const THEME_KEY = "why-theme";
const darkQuery = typeof matchMedia === "function" ? matchMedia("(prefers-color-scheme: dark)") : null;

/** The theme on screen: an explicit data-theme, else the system preference. */
export function currentTheme() {
  const t = document.documentElement.dataset.theme;
  if (t === "dark" || t === "light") return t;
  return darkQuery?.matches ? "dark" : "light";
}

/** Set "dark" or "light" on <html data-theme>, remember it, notify charts via "why:themechange". */
export function setTheme(theme, { remember = true } = {}) {
  if (theme !== "dark" && theme !== "light") return;
  document.documentElement.dataset.theme = theme;
  if (remember) {
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* storage blocked: the choice lasts for this page view */
    }
  }
  syncThemeToggle();
  document.dispatchEvent(new CustomEvent("why:themechange", { detail: { theme } }));
}

function syncThemeToggle() {
  const dark = currentTheme() === "dark";
  document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
    btn.setAttribute("aria-pressed", String(dark));
  });
}


// ---------------------------------------------------------------- chrome

const ICONS = {
  code: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true" focusable="false"><path d="M8 6l-6 6 6 6M16 6l6 6-6 6"/></svg>',
  moon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5a8.5 8.5 0 1 0 10.7 10.7z"/></svg>',
};

function headerHTML(page) {
  const nav = PAGES.map((p) =>
    `<li><a href="${p.href}"${p.id === page ? ' aria-current="page"' : ""}>${esc(p.label)}</a></li>`
  ).join("");
  return `
    <div class="wrap">
      <div class="masthead-row">
        <p class="ear ear--left">
          <span class="ear-strong" data-slot="ear-date">Daily edition</span>
          <span>${esc(SITE.schedule)}</span>
        </p>
        <div class="masthead">
          <p class="masthead-title"><a href="index.html" aria-label="WHY, today's edition">WHY</a></p>
          <p class="masthead-sub">${esc(SITE.tagline)}</p>
        </div>
        <div class="ear ear--right">
          <button class="btn" type="button" data-theme-toggle aria-pressed="false" aria-label="Night edition">
            ${ICONS.moon}<span class="btn-text">night</span>
          </button>
          <a class="btn" href="${SITE.repo}" target="_blank" rel="noopener noreferrer" aria-label="Source code on GitHub">
            ${ICONS.code}<span class="btn-text">source</span>
          </a>
        </div>
      </div>
      <div class="edition-bar">
        <span class="edition-no" data-slot="edition-no">Daily</span>
        <span class="edition-date" data-slot="edition-date">Loading the edition</span>
        <span class="edition-model" data-slot="edition-model">Headline sentiment</span>
      </div>
      <nav class="site-nav" aria-label="Site"><ul>${nav}</ul></nav>
    </div>`;
}

function footerHTML(page) {
  const links = PAGES.map((p) =>
    `<li><a href="${p.href}"${p.id === page ? ' aria-current="page"' : ""}>${esc(p.label)}</a></li>`
  ).join("");
  return `
    <div class="wrap">
      <div class="footer-grid">
        <section aria-label="About WHY">
          <p class="footer-mark" aria-hidden="true">WHY</p>
          <p>Yesterday's market headlines by topic, scored for sentiment by FinBERT and VADER, with the history kept in DuckDB and Parquet.</p>
          <p class="footer-fine">Headlines and links from Google News RSS. Not affiliated with Google.</p>
        </section>
        <section aria-labelledby="footer-agreement-title">
          <h2 class="kicker" id="footer-agreement-title">Model agreement</h2>
          <div data-slot="agreement"><p>The agreement report is not available yet.</p></div>
          <p class="footer-fine">Agreement is not accuracy: there are no human labels.</p>
        </section>
        <nav aria-labelledby="footer-nav-title">
          <h2 class="kicker" id="footer-nav-title">Sections</h2>
          <ul class="footer-links">
            ${links}
            <li><a href="${SITE.repo}" target="_blank" rel="noopener noreferrer">Source on GitHub</a></li>
            <li><a href="data/latest.json">Edition JSON</a></li>
          </ul>
        </nav>
      </div>
      <div class="footer-base">
        <span data-slot="updated">Not updated yet</span>
        <span data-slot="edition-foot">${esc(SITE.schedule)}</span>
        <span>MIT licensed</span>
      </div>
    </div>`;
}

/**
 * Render the shared header and footer into #site-header and #site-footer and wire the theme toggle.
 * page: "today" | "trends" | "models" | "pipeline" (marks the nav item with aria-current).
 */
export function mountChrome({ page = "today" } = {}) {
  const header = document.getElementById("site-header");
  const footer = document.getElementById("site-footer");
  if (header) header.innerHTML = headerHTML(page);
  if (footer) footer.innerHTML = footerHTML(page);
  document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => setTheme(currentTheme() === "dark" ? "light" : "dark"));
  });
  darkQuery?.addEventListener?.("change", () => {
    syncThemeToggle();
    document.dispatchEvent(new CustomEvent("why:themechange", { detail: { theme: currentTheme() } }));
  });
  syncThemeToggle();
}

function setSlot(name, text) {
  document.querySelectorAll(`[data-slot="${name}"]`).forEach((el) => {
    el.textContent = text;
  });
}

/** Agreement summary as HTML (numbers only, no feed text). Empty string when there is no report. */
export function agreementSummaryHTML(agreement, primary = null) {
  if (!agreement?.n || !Number.isFinite(Number(agreement.percent_agreement))) return "";
  const models = [...(agreement.models || [])];
  if (primary && models.includes(primary)) models.sort((a, b) => (a === primary ? -1 : b === primary ? 1 : 0));
  const [a, b] = models.map(modelName);
  const pct = Number(agreement.percent_agreement);
  const kappa = Number(agreement.cohens_kappa);
  const kappaText = Number.isFinite(kappa) ? `, Cohen's kappa ${kappa.toFixed(2)}` : "";
  return `
    <p>${esc(a)} and ${esc(b)} give the same label to <strong>${esc(fmtPercent(pct))}</strong>
      of ${esc(fmtInt(agreement.n))} headlines${esc(kappaText)}.</p>
    <div class="agree-meter" role="img" aria-label="${esc(fmtPercent(pct))} agreement">
      <span class="is-agree" style="flex-grow:${pct.toFixed(2)}"></span>
      <span class="is-differ" style="flex-grow:${(100 - pct).toFixed(2)}"></span>
    </div>`;
}

/**
 * Fill the edition bar and footer from whatever data the page loaded.
 * Accepts the object returned by loadAll(); every field is optional.
 */
export function hydrateChrome({ news = null, trends = null, agreement = null, status = null } = {}) {
  const number = editionNumber(status, trends);
  const primary = primaryModelOf(news, trends);
  setSlot("edition-no", number ? `No. ${fmtInt(number)}` : "Daily");
  setSlot("edition-date", news?.date_label || (news ? "No edition yet" : "Edition unavailable"));
  setSlot("edition-model", primary ? `Sentiment by ${modelName(primary)}` : "Headline sentiment");
  const runDate = news?.run_date || trends?.end_date;
  if (runDate) setSlot("ear-date", fmtDate(runDate, "weekday"));
  const generated = news?.generated_at || trends?.generated_at;
  setSlot("updated", generated ? `Updated ${fmtDateTime(generated)}` : "Not updated yet");
  if (number) setSlot("edition-foot", `Edition No. ${fmtInt(number)}. ${SITE.schedule}`);
  const summary = agreementSummaryHTML(agreement, primary);
  if (summary) {
    document.querySelectorAll('[data-slot="agreement"]').forEach((el) => {
      el.innerHTML = summary;
    });
  }
}

const GLYPHS = { loading: "◎", empty: "◌", error: "◌" };

/**
 * Loading, empty and error blocks in the house style. title and detail are escaped;
 * html is trusted markup appended after the detail (use it for <code> hints only).
 */
export function stateHTML({ kind = "loading", title = "", detail = "", html = "" } = {}) {
  const live = kind === "loading" ? ' role="status" aria-live="polite"' : kind === "error" ? ' role="alert"' : "";
  return `
    <div class="state state--${esc(kind)}"${live}>
      <div class="state-glyph" aria-hidden="true">${GLYPHS[kind] || GLYPHS.empty}</div>
      <p class="state-title">${esc(title)}</p>
      ${detail || html ? `<p class="state-detail">${esc(detail)}${html}</p>` : ""}
      ${kind === "loading" ? '<div class="loading-line" aria-hidden="true"></div>' : ""}
    </div>`;
}
