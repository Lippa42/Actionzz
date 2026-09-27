/* Actionzz – dashboard statica (GitHub Pages).
 * Legge i JSON dal branch `data` e salva config/config.json tramite l'API di GitHub. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const LS_KEY = "actionzz.settings";
// ?dati=cartella/ legge i JSON da una cartella locale (prove e demo, sola lettura)
const LOCAL = new URLSearchParams(location.search).get("dati");
const DATA_FILES = ["snapshot", "universe", "alerts", "backtest", "market_history", "summary", "state"];

const S = {
  settings: { repo: "", branch: "", token: "" },
  data: {},
  config: null, // salvata su GitHub
  draft: null, // in modifica
  configSha: null,
  sort: {},
};

/* ----------------------------------------------------------- formattazione */

const nf = (d) => new Intl.NumberFormat("it-IT", { minimumFractionDigits: d, maximumFractionDigits: d });
const NF = [nf(0), nf(1), nf(2)];
const num = (x, d = 2) => (x == null || Number.isNaN(x) ? "—" : NF[d].format(x));
const pct = (x, d = 1) => (x == null ? "—" : (x < 0 ? "−" : "+") + NF[d].format(Math.abs(x)) + "%");
const pts = (x) => (x == null ? "—" : (x < 0 ? "−" : "+") + NF[1].format(Math.abs(x)) + " pt");
const cls = (x) => (x == null ? "" : x < 0 ? "neg" : x > 0 ? "pos" : "");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const yahoo = (t) => `https://finance.yahoo.com/quote/${encodeURIComponent(t)}`;
const time = (iso) => (iso ? iso.slice(11, 16) : "—");
const dateIt = (iso) => (iso ? iso.slice(0, 10).split("-").reverse().join("/") : "—");

/* ---------------------------------------------------------------- settings */

function loadSettings() {
  try {
    Object.assign(S.settings, JSON.parse(localStorage.getItem(LS_KEY) || "{}"));
  } catch (_) { /* storage non disponibile */ }
  if (!S.settings.repo) {
    const host = location.hostname;
    const seg = location.pathname.split("/").filter(Boolean)[0];
    if (host.endsWith(".github.io") && seg) S.settings.repo = `${host.split(".")[0]}/${seg}`;
  }
}

function storeSettings() {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(S.settings));
  } catch (_) { /* ignora */ }
}

/* ------------------------------------------------------------- accesso dati */

const b64enc = (s) => {
  let bin = "";
  new TextEncoder().encode(s).forEach((b) => (bin += String.fromCharCode(b)));
  return btoa(bin);
};
const b64dec = (b) => new TextDecoder().decode(Uint8Array.from(atob(b.replace(/\n/g, "")), (c) => c.charCodeAt(0)));

function apiHeaders(extra = {}) {
  const h = { Accept: "application/vnd.github+json", ...extra };
  if (S.settings.token) h.Authorization = `Bearer ${S.settings.token}`;
  return h;
}

async function fetchFile(path, ref) {
  const { repo, token } = S.settings;
  let res;
  if (LOCAL) {
    res = await fetch(LOCAL + (ref === "data" ? path : path.split("/").pop()), { cache: "no-store" });
  } else if (token) {
    res = await fetch(`https://api.github.com/repos/${repo}/contents/${path}?ref=${ref}`, {
      headers: apiHeaders({ Accept: "application/vnd.github.raw+json" }),
      cache: "no-store",
    });
  } else {
    res = await fetch(`https://raw.githubusercontent.com/${repo}/${ref}/${path}?t=${Date.now()}`, { cache: "no-store" });
  }
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

async function loadConfig() {
  const { repo, branch, token } = S.settings;
  if (token && !LOCAL) {
    const res = await fetch(`https://api.github.com/repos/${repo}/contents/config/config.json?ref=${branch}`, {
      headers: apiHeaders(),
      cache: "no-store",
    });
    if (!res.ok) throw new Error(`config: HTTP ${res.status}`);
    const body = await res.json();
    S.configSha = body.sha;
    return JSON.parse(b64dec(body.content));
  }
  return fetchFile("config/config.json", branch);
}

async function saveConfig() {
  const { repo, branch, token } = S.settings;
  if (!token) {
    toast("Per salvare serve un token GitHub: aprilo in Impostazioni → Collegamento.");
    selectTab("settings");
    $("#gh-token").focus();
    return;
  }
  const btn = $("#save-config");
  btn.disabled = true;
  btn.textContent = "Salvataggio…";
  try {
    if (!S.configSha) await loadConfig();
    const res = await fetch(`https://api.github.com/repos/${repo}/contents/config/config.json`, {
      method: "PUT",
      headers: apiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        message: "Impostazioni aggiornate dalla dashboard",
        content: b64enc(JSON.stringify(S.draft, null, 2) + "\n"),
        sha: S.configSha,
        branch,
      }),
    });
    if (res.status === 409 || res.status === 422) {
      // qualcuno (es. un comando Telegram) ha cambiato il file nel frattempo
      const remote = await loadConfig();
      S.config = remote;
      toast("Il file è cambiato su GitHub nel frattempo: ho ricaricato la versione attuale, riprova a salvare.");
      renderAll();
      return;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${(await res.json()).message || ""}`);
    const body = await res.json();
    S.configSha = body.content.sha;
    S.config = structuredClone(S.draft);
    toast("✅ Impostazioni salvate. Valgono dalla prossima scansione.");
    renderAll();
  } catch (err) {
    toast("Salvataggio non riuscito: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Salva su GitHub";
  }
}

// Se l'utente non ha indicato il branch, uso quello predefinito del repository.
async function resolveBranch() {
  if (S.settings.branch || LOCAL) return;
  try {
    const res = await fetch(`https://api.github.com/repos/${S.settings.repo}`, { headers: apiHeaders() });
    if (res.ok) S.settings.branch = (await res.json()).default_branch;
  } catch (_) { /* rete assente: ripiego su main */ }
  S.settings.branch ||= "main";
}

async function loadAll() {
  if (S.settings.repo) await resolveBranch();
  if (!S.settings.repo && !LOCAL) {
    banner("Imposta il repository in <b>Impostazioni → Collegamento a GitHub</b> per vedere i dati.", true);
    selectTab("settings");
    renderAll();
    return;
  }
  banner("Caricamento dati…");
  const results = await Promise.allSettled(DATA_FILES.map((f) => fetchFile(`${f}.json`, "data")));
  const errors = [];
  results.forEach((r, i) => {
    if (r.status === "fulfilled") S.data[DATA_FILES[i]] = r.value;
    else errors.push(r.reason.message);
  });
  try {
    const cfg = await loadConfig();
    if (cfg) {
      const dirty = isDirty();
      S.config = cfg;
      if (!dirty) S.draft = structuredClone(cfg);
    }
  } catch (err) {
    errors.push(err.message);
  }
  if (errors.length) {
    const hint = S.settings.token ? "Controlla repository e permessi del token." : "Se il repository è privato serve un token (Impostazioni).";
    banner(`Alcuni dati non sono stati caricati (${esc(errors[0])}). ${hint}`, true);
  } else if (!S.data.snapshot && !S.data.universe) {
    banner("Ancora nessun dato: il primo avvio del workflow <b>Scanner</b> o <b>Universo e backtest</b> li creerà.");
  } else {
    banner(null);
  }
  renderAll();
}

/* ------------------------------------------------------------------ UI base */

function banner(html, error = false) {
  const el = $("#banner");
  el.hidden = !html;
  el.className = "banner" + (error ? " error" : "");
  el.innerHTML = html || "";
}

let toastTimer;
function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 5000);
}

function selectTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  document.querySelectorAll(".tab").forEach((s) => (s.hidden = s.id !== `tab-${name}`));
  try {
    localStorage.setItem("actionzz.tab", name);
  } catch (_) { /* ignora */ }
  renderCharts();
}

function applyTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}

const tip = $("#tooltip");
function showTip(html, ev) {
  tip.innerHTML = html;
  tip.hidden = false;
  const pad = 14;
  const r = tip.getBoundingClientRect();
  let x = ev.clientX + pad;
  let y = ev.clientY + pad;
  if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - pad;
  if (y + r.height > innerHeight - 8) y = ev.clientY - r.height - pad;
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${Math.max(8, y)}px`;
}
const hideTip = () => (tip.hidden = true);

/* -------------------------------------------------------------- tabella */

function table(el, id, columns, rows, opts = {}) {
  const st = (S.sort[id] ||= { key: opts.sortKey, dir: opts.sortDir || 1 });
  const col = columns.find((c) => c.key === st.key);
  if (col) {
    const val = col.sort || ((r) => r[col.key]);
    rows = [...rows].sort((a, b) => {
      const va = val(a), vb = val(b);
      if (va == null) return 1;
      if (vb == null) return -1;
      return (va > vb ? 1 : va < vb ? -1 : 0) * st.dir;
    });
  }
  const head = columns
    .map((c) => {
      const aria = c.key === st.key ? ` aria-sort="${st.dir > 0 ? "ascending" : "descending"}"` : "";
      return `<th class="${c.num ? "num" : ""} ${c.cls || ""}" ${c.nosort ? "" : `data-sort="${c.key}"`}${aria}>${c.label}</th>`;
    })
    .join("");
  const limit = opts.limit || 600;
  const body = rows
    .slice(0, limit)
    .map((r) => `<tr class="${opts.rowClass ? opts.rowClass(r) : ""}">${columns
      .map((c) => `<td class="${c.num ? "num" : ""} ${c.cls || ""}">${c.fmt ? c.fmt(r) : esc(r[c.key])}</td>`)
      .join("")}</tr>`)
    .join("");
  el.innerHTML = `<thead><tr>${head}</tr></thead><tbody>${body || `<tr><td colspan="${columns.length}" class="empty">Nessun dato</td></tr>`}</tbody>`;
  el.querySelectorAll("th[data-sort]").forEach((th) =>
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      S.sort[id] = { key, dir: st.key === key ? -st.dir : 1 };
      table(el, id, columns, rows, opts);
    }),
  );
}

/* --------------------------------------------------------------- grafici */

// Barre divergenti (negativo rosso, positivo blu) con tooltip al passaggio.
function barChart(el, items, { value, tooltip, xLabel, highlight, height = 220, signed = true, format = (v) => pct(v) }) {
  if (!el) return;
  if (!items.length) {
    el.innerHTML = `<div class="empty">Nessun dato</div>`;
    return;
  }
  const W = Math.max(el.clientWidth, 280);
  const H = height;
  const m = { t: 10, r: 8, b: 26, l: 44 };
  const vals = items.map(value).map((v) => v ?? 0);
  let max = Math.max(...vals.map(Math.abs), 0.0001);
  const step = niceStep(max / 2);
  max = Math.ceil(max / step) * step;
  const min = signed && Math.min(...vals) < 0 ? -max : 0;
  const top = signed || Math.min(...vals) >= 0 ? max : 0;
  const y = (v) => m.t + ((top - v) / (top - min)) * (H - m.t - m.b);
  const bw = (W - m.l - m.r) / items.length;
  const gap = bw > 6 ? 2 : bw > 3 ? 1 : 0;
  let lastLabelX = -Infinity;

  let svg = "";
  for (let v = min; v <= top + 1e-9; v += step) {
    const yy = y(v).toFixed(1);
    svg += `<line class="${Math.abs(v) < 1e-9 ? "baseline" : "gridline"}" x1="${m.l}" x2="${W - m.r}" y1="${yy}" y2="${yy}"/>`;
    svg += `<text x="${m.l - 6}" y="${yy}" dy="0.32em" text-anchor="end">${format(Math.abs(v) < 1e-9 ? 0 : v).replace("+0", "0")}</text>`;
  }
  items.forEach((it, i) => {
    const v = vals[i];
    const x = m.l + i * bw + gap / 2;
    const w = Math.max(bw - gap, 1);
    const y0 = y(0), y1 = y(v);
    const h = Math.max(Math.abs(y1 - y0), v === 0 ? 0 : 1);
    const r = Math.min(4, w / 2, h);
    const neg = v < 0;
    const yTop = neg ? y0 : y1;
    // estremità arrotondata dal lato del valore, base piatta sullo zero
    const path = neg
      ? `M${x},${yTop}h${w}v${h - r}q0,${r} ${-r},${r}h${-(w - 2 * r)}q${-r},0 ${-r},${-r}z`
      : `M${x},${yTop + h}v${-(h - r)}q0,${-r} ${r},${-r}h${w - 2 * r}q${r},0 ${r},${r}v${h - r}z`;
    const hl = highlight && highlight(it) ? " hl" : "";
    svg += `<path class="${neg ? "bar-neg" : "bar-pos"}${hl}" d="${path}"/>`;
    const lbl = xLabel && xLabel(it, i);
    const cx = x + w / 2;
    if (lbl && cx - lastLabelX >= 34) {
      lastLabelX = cx;
      svg += `<text x="${(x + w / 2).toFixed(1)}" y="${H - 8}" text-anchor="middle">${esc(lbl)}</text>`;
    }
    svg += `<rect class="hit" data-i="${i}" x="${m.l + i * bw}" y="${m.t}" width="${bw}" height="${H - m.t - m.b}"/>`;
  });
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img">${svg}</svg>`;
  el.querySelectorAll(".hit").forEach((r) => {
    const show = (ev) => showTip(tooltip(items[+r.dataset.i]), ev);
    r.addEventListener("pointermove", show);
    r.addEventListener("pointerdown", show);
    r.addEventListener("pointerleave", hideTip);
  });
}

function niceStep(x) {
  const p = 10 ** Math.floor(Math.log10(x));
  const f = x / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}

function renderCharts() {
  const hist = (S.data.market_history || []).slice(-90);
  let lastMonth = "";
  barChart($("#market-chart"), hist, {
    value: (h) => h.market_pct,
    xLabel: (h) => {
      const mo = h.day.slice(0, 7);
      if (mo === lastMonth) return null;
      lastMonth = mo;
      return ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"][+h.day.slice(5, 7) - 1];
    },
    tooltip: (h) => `<div>${dateIt(h.day)}</div><div>Mercato <b>${pct(h.market_pct, 2)}</b></div>
      <div class="muted">${h.down} in calo · ${h.up} in rialzo · ${h.alerts} avvisi</div>`,
  });

  const bt = S.data.backtest;
  if (bt) {
    const th = (S.draft || {}).drop_threshold_pct ?? bt.params.drop_threshold_pct;
    barChart($("#sweep-chart"), bt.sweep, {
      value: (r) => r.ret20,
      xLabel: (r) => `−${num(r.threshold, 0)}%`,
      highlight: (r) => r.threshold === th,
      tooltip: (r) => `<div>Soglia <b>−${num(r.threshold, 0)}%</b></div>
        <div>${r.signals} segnali (${num(r.per_year, 1)}/anno)</div>
        <div>Rendimento medio a 20 sedute <b>${pct(r.ret20, 2)}</b></div>
        <div>Positivi ${num(r.hit20, 0)}% · vs mercato ${pts(r.excess20)}</div>`,
    });
    const years = Object.entries(bt.by_year || {}).map(([year, n]) => ({ year, n }));
    barChart($("#year-chart"), years, {
      value: (r) => r.n,
      signed: false,
      format: (v) => num(v, 0),
      xLabel: (r) => r.year,
      tooltip: (r) => `<div>${r.year}</div><div><b>${r.n}</b> segnali</div>`,
    });
  }
}

/* ------------------------------------------------------------- render */

function metas() {
  const map = {};
  ((S.data.universe || {}).items || []).forEach((i) => (map[i.ticker] = i));
  return map;
}

function kpi(label, value, sub = "", valueCls = "") {
  return `<div class="kpi"><div class="label">${label}</div><div class="value ${valueCls}">${value}</div><div class="sub">${sub}</div></div>`;
}

function romeNow() {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: (S.draft || {}).timezone || "Europe/Rome",
    weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false,
  }).formatToParts(new Date());
  const get = (t) => parts.find((p) => p.type === t).value;
  return { weekday: get("weekday"), hm: `${get("hour")}:${get("minute")}` };
}

function renderMarketPill() {
  const cfg = S.draft || {};
  const { weekday, hm } = romeNow();
  const open = !["Sat", "Sun"].includes(weekday) && hm >= (cfg.market_open || "09:00") && hm <= (cfg.market_close || "17:30");
  const paused = cfg.paused ? " · avvisi in pausa" : "";
  const el = $("#market-pill");
  el.className = "pill " + (open ? "open" : "closed");
  el.innerHTML = `<span class="dot"></span>Borsa ${open ? "aperta" : "chiusa"} · ${hm}${paused}`;
}

function renderOverview() {
  const snap = S.data.snapshot;
  const uni = S.data.universe;
  const cfg = S.draft || {};
  const alerts = S.data.alerts || [];
  const today = snap ? snap.day : null;
  const todays = alerts.filter((a) => a.day === today);
  const quotes = snap ? snap.quotes : [];
  const down = quotes.filter((q) => q.pct < 0).length;

  $("#kpis").innerHTML = [
    kpi("Titoli monitorati", snap ? num(snap.monitored, 0) : uni ? num(uni.items.length, 0) : "—",
      uni ? `universo del ${dateIt(uni.generated)}` : "universo non calcolato"),
    kpi("Mercato oggi", snap ? pct(snap.market_pct, 2) : "—", snap ? `${down} in calo · ${quotes.length - down} in rialzo` : "", snap ? cls(snap.market_pct) : ""),
    kpi("Avvisi oggi", todays.length, cfg.drop_threshold_pct ? `soglia ${pct(-cfg.drop_threshold_pct)}${cfg.market_filter ? ` e ${num(cfg.relative_threshold_pct, 1)} pt sotto il mercato` : ""}` : ""),
    kpi("Ultima scansione", snap ? time(snap.time) : "—", snap ? dateIt(snap.day) : "nessuna scansione"),
  ].join("");

  $("#alerts-today-count").textContent = today ? dateIt(today) : "";
  const m = metas();
  $("#alerts-today").innerHTML = todays.length
    ? `<div class="list">${todays
        .slice()
        .reverse()
        .map((a) => `<div class="list-item"><div class="left"><div><a class="tk" href="${yahoo(a.ticker)}" target="_blank" rel="noopener">${esc(a.ticker)}</a> ${esc(a.name)}</div>
          <div class="muted small">${time(a.time)} · ${a.repeat ? "nuovo calo" : "primo avviso"} · vs mercato ${pts(a.relative)}</div></div>
          <div class="num neg"><b>${pct(a.pct)}</b></div></div>`)
        .join("")}</div>`
    : `<div class="empty">Nessun calo anomalo oggi 😌</div>`;

  const worst = quotes.slice(0, 10);
  const maxDrop = Math.max(...worst.map((q) => -q.pct), 0.1);
  $("#worst").innerHTML = worst.length
    ? `<div class="list">${worst
        .map((q) => `<div class="list-item"><div class="left"><div><a class="tk" href="${yahoo(q.ticker)}" target="_blank" rel="noopener">${esc(q.ticker)}</a> ${esc((m[q.ticker] || {}).name || "")}</div>
          <div class="muted small">${num(q.price)} ${esc((m[q.ticker] || {}).currency || "")} · vs mercato ${pts(q.rel)}</div></div>
          <div class="bar-cell"><div class="minibar" style="width:${Math.max(0, (-q.pct / maxDrop) * 80)}px"></div><span class="num ${cls(q.pct)}"><b>${pct(q.pct)}</b></span></div></div>`)
        .join("")}</div>`
    : `<div class="empty">Nessuna scansione disponibile</div>`;

  const sum = S.data.summary;
  $("#summary-day").textContent = sum ? dateIt(sum.day) : "";
  $("#summary").innerHTML = sum ? sanitize(sum.text) : `<div class="empty">Il riepilogo arriva dopo la chiusura della borsa.</div>`;
}

// Il riepilogo è HTML di Telegram: tengo solo b, i, code, a.
function sanitize(html) {
  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, "text/html");
  const walk = (node) => {
    [...node.childNodes].forEach((ch) => {
      if (ch.nodeType === 1) {
        walk(ch);
        const tag = ch.tagName.toLowerCase();
        if (!["b", "i", "code", "a"].includes(tag)) {
          ch.replaceWith(...ch.childNodes);
        } else {
          const href = ch.getAttribute("href");
          [...ch.attributes].forEach((a) => ch.removeAttribute(a.name));
          if (tag === "a" && href && /^https?:/i.test(href)) {
            ch.setAttribute("href", href);
            ch.setAttribute("target", "_blank");
            ch.setAttribute("rel", "noopener");
          }
        }
      }
    });
  };
  walk(doc.body.firstChild);
  return doc.body.firstChild.innerHTML;
}

function fillCountries(select, items) {
  const current = select.value;
  const countries = [...new Set(items.map((i) => i.country).filter(Boolean))].sort();
  select.innerHTML = `<option value="">Tutti i paesi</option>` + countries.map((c) => `<option>${esc(c)}</option>`).join("");
  select.value = countries.includes(current) ? current : "";
}

function renderToday() {
  const snap = S.data.snapshot;
  const m = metas();
  const cfg = S.draft || {};
  $("#today-time").textContent = snap ? `aggiornato ${dateIt(snap.day)} alle ${time(snap.time)} · mercato ${pct(snap.market_pct, 2)}` : "";
  const rows = (snap ? snap.quotes : []).map((q) => ({ ...q, ...(m[q.ticker] ? { name: m[q.ticker].name, country: m[q.ticker].country, currency: m[q.ticker].currency } : {}) }));
  fillCountries($("#today-country"), rows);
  const qtext = $("#today-search").value.trim().toLowerCase();
  const country = $("#today-country").value;
  const below = $("#today-below").checked;
  const th = cfg.drop_threshold_pct || 5;
  const filtered = rows.filter((r) =>
    (!qtext || r.ticker.toLowerCase().includes(qtext) || (r.name || "").toLowerCase().includes(qtext)) &&
    (!country || r.country === country) &&
    (!below || r.pct <= -th));
  table($("#today-table"), "today", [
    { key: "ticker", label: "Ticker", fmt: (r) => `<a class="tk" href="${yahoo(r.ticker)}" target="_blank" rel="noopener">${esc(r.ticker)}</a>` },
    { key: "name", label: "Nome", cls: "name", fmt: (r) => esc(r.name || "") },
    { key: "country", label: "Paese", cls: "hide-sm", fmt: (r) => esc(r.country || "") },
    { key: "price", label: "Prezzo", num: true, fmt: (r) => `${num(r.price)} <span class="muted small">${esc(r.currency || "")}</span>` },
    { key: "pct", label: "Var. vs ieri", num: true, fmt: (r) => `<b class="${cls(r.pct)}">${pct(r.pct, 2)}</b>` },
    { key: "low_pct", label: "Minimo", num: true, cls: "hide-sm", fmt: (r) => `<span class="${cls(r.low_pct)}">${pct(r.low_pct, 2)}</span>` },
    { key: "rel", label: "vs mercato", num: true, fmt: (r) => `<span class="${cls(r.rel)}">${pts(r.rel)}</span>` },
    { key: "vol_ratio", label: "Volume", num: true, cls: "hide-sm", fmt: (r) => (r.vol_ratio == null ? "—" : `${num(r.vol_ratio, 1)}×`) },
  ], filtered, { sortKey: "pct", rowClass: (r) => (r.pct <= -th ? "hit" : "") });
}

function renderAlerts() {
  const q = $("#alerts-search").value.trim().toLowerCase();
  const rows = (S.data.alerts || []).filter((a) => !q || a.ticker.toLowerCase().includes(q) || (a.name || "").toLowerCase().includes(q));
  $("#alerts-count").textContent = `${(S.data.alerts || []).length} avvisi registrati`;
  table($("#alerts-table"), "alerts", [
    { key: "time", label: "Quando", fmt: (a) => `${dateIt(a.day)} <span class="muted">${time(a.time)}</span>` },
    { key: "ticker", label: "Ticker", fmt: (a) => `<a class="tk" href="${yahoo(a.ticker)}" target="_blank" rel="noopener">${esc(a.ticker)}</a>` },
    { key: "name", label: "Nome", cls: "name" },
    { key: "pct", label: "Calo", num: true, fmt: (a) => `<b class="neg">${pct(a.pct, 2)}</b>` },
    { key: "relative", label: "vs mercato", num: true, fmt: (a) => pts(a.relative) },
    { key: "market_pct", label: "Mercato", num: true, cls: "hide-sm", fmt: (a) => pct(a.market_pct, 2) },
    { key: "price", label: "Prezzo", num: true, cls: "hide-sm", fmt: (a) => num(a.price) },
    { key: "repeat", label: "Tipo", fmt: (a) => `<span class="tag">${a.repeat ? "nuovo calo" : "primo avviso"}</span>` },
  ], rows, { sortKey: "time", sortDir: -1 });
}

function renderUniverse() {
  const uni = S.data.universe;
  const cfg = S.draft || { include: [], exclude: [] };
  const snap = S.data.snapshot;
  const todayPct = {};
  (snap ? snap.quotes : []).forEach((q) => (todayPct[q.ticker] = q.pct));
  const items = uni ? uni.items : [];

  if (uni) {
    const s = uni.stats;
    $("#universe-kpis").innerHTML = [
      kpi("Titoli scelti", num(s.selected, 0), `su ${s.with_data} candidati con dati (${s.candidates} totali)`),
      kpi("Volatilità mediana", `${num(s.vol_median, 1)}%`, `annua · massima ${num(s.vol_max, 1)}%`),
      kpi("Storico", `${uni.params.lookback_years} anni`, `minimo ${num(uni.params.min_history_years, 1)} anni di dati`),
      kpi("Calcolato il", dateIt(uni.generated), "si ricalcola il 1° di ogni mese"),
    ].join("");
  } else {
    $("#universe-kpis").innerHTML = kpi("Universo", "—", "non ancora calcolato: avvia il workflow «Universo e backtest»");
  }

  $("#manual-lists").innerHTML =
    cfg.include.map((t) => `<span class="chip inc">+ ${esc(t)}<button data-unlist="include" data-t="${esc(t)}" title="Rimuovi">×</button></span>`).join("") +
    cfg.exclude.map((t) => `<span class="chip exc">− ${esc(t)}<button data-unlist="exclude" data-t="${esc(t)}" title="Rimuovi">×</button></span>`).join("");

  fillCountries($("#universe-country"), items);
  const q = $("#universe-search").value.trim().toLowerCase();
  const country = $("#universe-country").value;
  const rows = items.filter((i) =>
    (!q || i.ticker.toLowerCase().includes(q) || (i.name || "").toLowerCase().includes(q) || (i.sector || "").toLowerCase().includes(q)) &&
    (!country || i.country === country)).map((i) => ({ ...i, today: todayPct[i.ticker] }));

  table($("#universe-table"), "universe", [
    { key: "rank", label: "#", num: true },
    { key: "ticker", label: "Ticker", fmt: (r) => `<a class="tk" href="${yahoo(r.ticker)}" target="_blank" rel="noopener">${esc(r.ticker)}</a>` },
    { key: "name", label: "Nome", cls: "name" },
    { key: "country", label: "Paese", cls: "hide-sm" },
    { key: "sector", label: "Settore", cls: "name hide-sm" },
    { key: "vol", label: "Volatilità", num: true, fmt: (r) => `${num(r.vol, 1)}%` },
    { key: "max_drawdown", label: "Max calo", num: true, cls: "hide-sm", fmt: (r) => pct(r.max_drawdown) },
    { key: "return_1y", label: "1 anno", num: true, cls: "hide-sm", fmt: (r) => `<span class="${cls(r.return_1y)}">${pct(r.return_1y)}</span>` },
    { key: "return_total", label: "5 anni", num: true, cls: "hide-sm", fmt: (r) => `<span class="${cls(r.return_total)}">${pct(r.return_total)}</span>` },
    { key: "today", label: "Oggi", num: true, fmt: (r) => `<span class="${cls(r.today)}">${pct(r.today, 2)}</span>` },
    { key: "act", label: "", nosort: true, fmt: (r) => cfg.exclude.includes(r.ticker)
      ? `<button class="btn small" data-toggle="${esc(r.ticker)}">Riattiva</button>`
      : `<button class="btn small danger" data-toggle="${esc(r.ticker)}">Escludi</button>` },
  ], rows, { sortKey: "rank", rowClass: (r) => (cfg.exclude.includes(r.ticker) ? "excluded" : "") });
}

function renderBacktest() {
  const bt = S.data.backtest;
  $("#backtest-empty").hidden = !!bt;
  $("#backtest-body").hidden = !bt;
  if (!bt) return;
  const p = bt.params;
  const main = bt.main;
  $("#backtest-intro").innerHTML = `Dal ${dateIt(bt.period.start)} al ${dateIt(bt.period.end)}, sui <b>${bt.tickers}</b> titoli dell'universo,
    con soglia <b>${pct(-p.drop_threshold_pct)}</b>${p.market_filter ? ` e filtro mercato (${num(p.relative_threshold_pct, 1)} pt)` : " senza filtro mercato"},
    il bot avrebbe inviato <b>${num(main.signals, 0)}</b> segnali, circa <b>${num(main.per_year, 1)} l'anno</b>.
    ${S.draft && S.draft.drop_threshold_pct !== p.drop_threshold_pct ? `<br><span class="muted">Nota: calcolato con la soglia ${pct(-p.drop_threshold_pct)}; la tabella sotto mostra anche le altre soglie.</span>` : ""}`;
  const h = main.horizons;
  const hk = (k, label) => {
    const r = h[k].return, e = h[k].excess;
    return kpi(`Dopo ${label}`, `<span class="${cls(r.mean)}">${pct(r.mean, 2)}</span>`,
      `mediana ${pct(r.median, 2)} · positivi ${num(r.hit_rate, 0)}% · vs mercato ${pts(e.mean)}`);
  };
  $("#backtest-kpis").innerHTML = [
    kpi("Segnali", num(main.signals, 0), `${num(main.per_year, 1)} all'anno · max 1 per titolo ogni ${p.cooldown_days} sedute`),
    hk("5", "5 sedute"), hk("20", "20 sedute (~1 mese)"), hk("60", "60 sedute (~3 mesi)"),
  ].join("");

  const th = (S.draft || {}).drop_threshold_pct;
  table($("#sweep-table"), "sweep", [
    { key: "threshold", label: "Soglia", fmt: (r) => `${r.threshold === th ? "▶ " : ""}−${num(r.threshold, 0)}%` },
    { key: "signals", label: "Segnali", num: true, fmt: (r) => num(r.signals, 0) },
    { key: "per_year", label: "/anno", num: true, fmt: (r) => num(r.per_year, 1) },
    { key: "ret20", label: "Rend. 20 g", num: true, fmt: (r) => `<span class="${cls(r.ret20)}">${pct(r.ret20, 2)}</span>` },
    { key: "hit20", label: "Positivi", num: true, fmt: (r) => `${num(r.hit20, 0)}%` },
    { key: "excess20", label: "vs mercato", num: true, fmt: (r) => pts(r.excess20) },
    { key: "ret60", label: "Rend. 60 g", num: true, cls: "hide-sm", fmt: (r) => `<span class="${cls(r.ret60)}">${pct(r.ret60, 2)}</span>` },
  ], bt.sweep, { sortKey: "threshold" });

  table($("#events-table"), "events", [
    { key: "day", label: "Giorno", fmt: (r) => dateIt(r.day) },
    { key: "ticker", label: "Ticker", fmt: (r) => `<a class="tk" href="${yahoo(r.ticker)}" target="_blank" rel="noopener">${esc(r.ticker)}</a>` },
    { key: "name", label: "Nome", cls: "name hide-sm" },
    { key: "low_pct", label: "Minimo", num: true, fmt: (r) => `<span class="neg">${pct(r.low_pct)}</span>` },
    { key: "close_pct", label: "Chiusura", num: true, fmt: (r) => `<span class="${cls(r.close_pct)}">${pct(r.close_pct)}</span>` },
    { key: "market_pct", label: "Mercato", num: true, cls: "hide-sm", fmt: (r) => pct(r.market_pct) },
    { key: "ret5", label: "+5 g", num: true, fmt: (r) => `<span class="${cls(r.ret5)}">${pct(r.ret5)}</span>` },
    { key: "ret20", label: "+20 g", num: true, fmt: (r) => `<span class="${cls(r.ret20)}">${pct(r.ret20)}</span>` },
    { key: "ret60", label: "+60 g", num: true, fmt: (r) => `<span class="${cls(r.ret60)}">${pct(r.ret60)}</span>` },
  ], bt.events, { sortKey: "day", sortDir: -1 });
}

/* ---------------------------------------------------------- impostazioni */

const SCHEMA = [
  { title: "Rilevamento dei cali", fields: [
    ["drop_threshold_pct", "number", "Soglia di calo (%)", "Avviso quando un titolo scende almeno di questa percentuale rispetto alla chiusura di ieri.", { min: 0.5, max: 50, step: 0.5 }],
    ["market_filter", "bool", "Filtro mercato", "Ignora i cali che seguono solo l'andamento di tutto il mercato."],
    ["relative_threshold_pct", "number", "Punti peggio del mercato", "Con il filtro attivo, il titolo deve fare almeno così peggio della mediana dell'universo.", { min: 0, max: 50, step: 0.5 }],
    ["realert_step_pct", "number", "Nuovo avviso dopo un ulteriore calo di (punti)", "Se un titolo già segnalato oggi continua a scendere, ti riavviso ogni volta che perde altri N punti.", { min: 0.1, max: 50, step: 0.5 }],
    ["market_crash_pct", "number", "Avviso di calo generalizzato (%)", "Un solo messaggio quando la mediana di tutto l'universo scende oltre questa soglia.", { min: 0.5, max: 50, step: 0.5 }],
    ["max_alerts_per_scan", "int", "Schede dettagliate per scansione", "Oltre questo numero, gli altri titoli arrivano in un unico elenco.", { min: 1, max: 50, step: 1 }],
  ] },
  { title: "Notifiche", fields: [
    ["paused", "bool", "Avvisi in pausa", "Le scansioni continuano (la dashboard si aggiorna) ma non arrivano messaggi."],
    ["daily_summary", "bool", "Riepilogo giornaliero", "Un messaggio dopo la chiusura con avvisi, peggiori e migliori del giorno."],
    ["summary_time", "time", "Ora del riepilogo", "Ora locale; il riepilogo parte alla prima scansione dopo quest'ora."],
    ["send_news", "bool", "Notizie nelle schede", "Aggiunge le ultime notizie da Yahoo Finance."],
    ["send_chart", "bool", "Grafico nelle schede", "Invia il grafico degli ultimi 6 mesi."],
  ] },
  { title: "Universo dei titoli", fields: [
    ["universe_size", "int", "Numero di titoli", "Quanti titoli tenere, i meno volatili tra i candidati. Vale dal prossimo ricalcolo mensile (o avvia il workflow a mano).", { min: 50, max: 900, step: 10 }],
    ["lookback_years", "int", "Anni di storico", "Periodo su cui misurare la stabilità.", { min: 1, max: 20, step: 1 }],
    ["min_history_years", "number", "Anni minimi di quotazione", "Scarta i titoli quotati da meno tempo.", { min: 0, max: 20, step: 0.5 }],
  ] },
  { title: "Orari di borsa", fields: [
    ["timezone", "text", "Fuso orario", "Nome IANA, es. Europe/Rome."],
    ["market_open", "time", "Apertura", "Le borse europee principali aprono alle 9:00 (ora italiana)."],
    ["market_close", "time", "Chiusura", ""],
    ["data_delay_minutes", "int", "Scansioni dopo la chiusura (minuti)", "I dati gratuiti arrivano con circa 15 minuti di ritardo.", { min: 0, max: 120, step: 5 }],
    ["scan_interval_minutes", "int", "Intervallo scansioni (min)", "Solo per l'esecuzione continua su PC/server; su GitHub lo decide il workflow.", { min: 1, max: 60, step: 1 }],
  ] },
];

function renderSettings() {
  const cfg = S.draft;
  const form = $("#settings-form");
  if (!cfg) {
    form.innerHTML = `<div class="card span2"><p>Impostazioni non caricate. Controlla il collegamento a GitHub qui sotto.</p></div>`;
  } else if (!form.dataset.ready) {
    form.innerHTML = SCHEMA.map((g) => `<div class="card"><div class="card-head"><h2>${g.title}</h2></div><div class="form-grid">${g.fields
      .map(([key, type, label, help, o = {}]) => {
        if (type === "bool") {
          return `<label class="field toggle span2" data-key="${key}"><input type="checkbox" name="${key}"><span>${label}<br><span class="help">${help}</span></span></label>`;
        }
        const inputType = type === "time" ? "time" : type === "text" ? "text" : "number";
        const attrs = Object.entries(o).map(([k, v]) => `${k}="${v}"`).join(" ");
        return `<label class="field" data-key="${key}">${label}<input type="${inputType}" name="${key}" ${attrs}><span class="help">${help}</span></label>`;
      })
      .join("")}</div></div>`).join("");
    form.dataset.ready = "1";
    form.addEventListener("input", (ev) => {
      const el = ev.target;
      const f = SCHEMA.flatMap((g) => g.fields).find((x) => x[0] === el.name);
      if (!f) return;
      let v = el.type === "checkbox" ? el.checked : el.value;
      if (f[1] === "number") v = parseFloat(v);
      if (f[1] === "int") v = parseInt(v, 10);
      if ((f[1] === "number" || f[1] === "int") && Number.isNaN(v)) return;
      S.draft[el.name] = v;
      onDraftChange();
    });
  }
  if (cfg) {
    SCHEMA.flatMap((g) => g.fields).forEach(([key, type]) => {
      const el = form.elements[key];
      if (!el) return;
      if (type === "bool") el.checked = !!cfg[key];
      else if (document.activeElement !== el) el.value = cfg[key] ?? "";
      const changed = S.config && JSON.stringify(S.config[key]) !== JSON.stringify(cfg[key]);
      el.closest(".field").classList.toggle("changed", !!changed);
    });
  }
  $("#gh-repo").value = S.settings.repo;
  $("#gh-branch").value = S.settings.branch;
  $("#gh-token").value = S.settings.token ? "••••••••" : "";
}

const isDirty = () => !!(S.config && S.draft && JSON.stringify(S.config) !== JSON.stringify(S.draft));

function onDraftChange() {
  $("#savebar").hidden = !isDirty();
  renderSettings();
  renderMarketPill();
}

function renderAll() {
  renderMarketPill();
  renderOverview();
  renderToday();
  renderAlerts();
  renderUniverse();
  renderBacktest();
  renderSettings();
  renderCharts();
  $("#savebar").hidden = !isDirty();
}

/* --------------------------------------------------------------- eventi */

function setList(ticker, list) {
  const other = list === "include" ? "exclude" : "include";
  S.draft[other] = S.draft[other].filter((t) => t !== ticker);
  if (!S.draft[list].includes(ticker)) S.draft[list] = [...S.draft[list], ticker];
}

function bind() {
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => selectTab(b.dataset.tab)));
  $("#refresh").addEventListener("click", loadAll);
  $("#theme").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    applyTheme(next);
    try {
      localStorage.setItem("actionzz.theme", next);
    } catch (_) { /* ignora */ }
  });

  ["#today-search", "#today-country", "#today-below"].forEach((s) => $(s).addEventListener("input", renderToday));
  $("#alerts-search").addEventListener("input", renderAlerts);
  ["#universe-search", "#universe-country"].forEach((s) => $(s).addEventListener("input", renderUniverse));

  $("#tab-universe").addEventListener("click", (ev) => {
    const btn = ev.target.closest("button");
    if (!btn || !S.draft) return;
    if (btn.dataset.toggle) {
      const t = btn.dataset.toggle;
      if (S.draft.exclude.includes(t)) S.draft.exclude = S.draft.exclude.filter((x) => x !== t);
      else setList(t, "exclude");
    } else if (btn.dataset.unlist) {
      S.draft[btn.dataset.unlist] = S.draft[btn.dataset.unlist].filter((x) => x !== btn.dataset.t);
    } else return;
    renderUniverse();
    onDraftChange();
  });

  $("#add-ticker").addEventListener("submit", (ev) => {
    ev.preventDefault();
    if (!S.draft) return;
    const input = $("#add-ticker-input");
    const tickers = input.value.toUpperCase().split(/[\s,;]+/).filter(Boolean);
    tickers.forEach((t) => setList(t, "include"));
    input.value = "";
    renderUniverse();
    onDraftChange();
    if (tickers.length) toast(`Aggiunti: ${tickers.join(", ")}. Ricordati di salvare.`);
  });

  $("#save-config").addEventListener("click", saveConfig);
  $("#discard").addEventListener("click", () => {
    S.draft = structuredClone(S.config);
    renderAll();
  });
  $("#download-config").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify(S.draft, null, 2) + "\n"], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "config.json";
    a.click();
    URL.revokeObjectURL(a.href);
  });

  $("#gh-save").addEventListener("click", () => {
    S.settings.repo = $("#gh-repo").value.trim().replace(/^https:\/\/github\.com\//, "").replace(/\/$/, "");
    S.settings.branch = $("#gh-branch").value.trim();
    const tok = $("#gh-token").value.trim();
    if (tok && !tok.startsWith("•")) S.settings.token = tok;
    storeSettings();
    toast("Collegamento salvato.");
    S.configSha = null;
    loadAll();
  });
  $("#gh-forget").addEventListener("click", () => {
    S.settings.token = "";
    storeSettings();
    toast("Token rimosso da questo browser.");
    renderSettings();
  });

  addEventListener("beforeunload", (ev) => {
    if (isDirty()) ev.preventDefault();
  });
  let rt;
  addEventListener("resize", () => {
    clearTimeout(rt);
    rt = setTimeout(renderCharts, 150);
  });
  setInterval(renderMarketPill, 30000);
  setInterval(() => {
    if (!document.hidden && !isDirty()) loadAll();
  }, 5 * 60 * 1000);
}

/* ---------------------------------------------------------------- avvio */

(function init() {
  try {
    applyTheme(localStorage.getItem("actionzz.theme"));
  } catch (_) { /* ignora */ }
  loadSettings();
  bind();
  let tab = "overview";
  try {
    tab = localStorage.getItem("actionzz.tab") || tab;
  } catch (_) { /* ignora */ }
  selectTab(document.getElementById(`tab-${tab}`) ? tab : "overview");
  loadAll();
})();
