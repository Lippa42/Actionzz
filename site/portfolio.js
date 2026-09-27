/* Actionzz – accesso con password, cifratura e gestione del portafoglio.
 * Caricato prima di app.js: definisce solo funzioni, usate da app.js dopo l'avvio.
 *
 * Il portafoglio è salvato cifrato (AES-256-GCM, chiave PBKDF2-SHA256 dalla password)
 * in config/portfolio.enc.json; lo scanner lo decifra con il secret PORTFOLIO_PASSWORD
 * e pubblica il resoconto, anch'esso cifrato, nel branch `data`. */
"use strict";

const PF_PATH = "config/portfolio.enc.json";
const PF_REPORT = "portfolio_report.enc.json";
const PW_SESSION = "actionzz.pw";
const MIN_PASSWORD = 10;
const PF_DEFAULTS = { take_profit_pct: 25, stop_loss_pct: 15, trailing_stop_pct: 12, tax_rate_pct: 26, sell_alerts: true };

/* ------------------------------------------------------------------ cifratura */

const u8 = (s) => new TextEncoder().encode(s);
function bufToB64(buf) {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}
const b64ToBuf = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

const keyCache = new Map();
async function deriveKey(password, salt, iterations) {
  const id = `${iterations}:${bufToB64(salt)}:${password}`;
  if (!keyCache.has(id)) {
    const base = await crypto.subtle.importKey("raw", u8(password), "PBKDF2", false, ["deriveKey"]);
    keyCache.set(id, await crypto.subtle.deriveKey(
      { name: "PBKDF2", salt, iterations, hash: "SHA-256" }, base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"],
    ));
  }
  return keyCache.get(id);
}

async function encryptJSON(obj, password, iterations = 310000) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await deriveKey(password, salt, iterations);
  const data = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, u8(JSON.stringify(obj)));
  return { v: 1, kdf: "PBKDF2-SHA256", iter: iterations, salt: bufToB64(salt), iv: bufToB64(iv), data: bufToB64(data) };
}

async function decryptJSON(env, password) {
  const key = await deriveKey(password, b64ToBuf(env.salt), env.iter);
  const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64ToBuf(env.iv) }, key, b64ToBuf(env.data));
  return JSON.parse(new TextDecoder().decode(plain));
}

/* ------------------------------------------------------------ file su GitHub */

async function getRepoFile(path) {
  const { repo, branch } = S.settings;
  const res = await fetch(`https://api.github.com/repos/${repo}/contents/${path}?ref=${branch}`, { headers: apiHeaders(), cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  const body = await res.json();
  return { sha: body.sha, text: b64dec(body.content) };
}

async function putRepoFile(path, text, sha, message) {
  const { repo, branch } = S.settings;
  const res = await fetch(`https://api.github.com/repos/${repo}/contents/${path}`, {
    method: "PUT",
    headers: apiHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ message, content: b64enc(text), branch, ...(sha ? { sha } : {}) }),
  });
  if (!res.ok) {
    const err = new Error(`HTTP ${res.status}: ${(await res.json().catch(() => ({}))).message || ""}`);
    err.status = res.status;
    throw err;
  }
  return (await res.json()).content.sha;
}

// Busta cifrata del portafoglio (senza token: il repository è pubblico).
async function fetchPortfolioEnvelope() {
  if (LOCAL) {
    const res = await fetch(LOCAL + "portfolio.enc.json", { cache: "no-store" });
    return res.ok ? res.json() : null;
  }
  if (S.token) {
    const f = await getRepoFile(PF_PATH);
    if (f) S.pfSha = f.sha;
    return f ? JSON.parse(f.text) : null;
  }
  return fetchFile(PF_PATH, S.settings.branch);
}

/* ------------------------------------------------------------------ accesso */

function showLock(mode, message = "") {
  document.body.classList.add("locked");
  const lock = $("#lock");
  lock.hidden = false;
  lock.dataset.mode = mode;
  $("#lock-title").textContent = mode === "setup" ? "Crea la tua password" : "Accedi";
  $("#lock-intro").innerHTML = mode === "setup"
    ? `Primo accesso: scegli una password di almeno ${MIN_PASSWORD} caratteri. Serve a entrare e a <b>cifrare il tuo portafoglio</b>: senza di lei nessuno può leggerlo, nemmeno dal repository pubblico. Non si può recuperare, conservala bene.`
    : "Inserisci la password per aprire la dashboard.";
  $("#lock-confirm-row").hidden = mode !== "setup";
  $("#lock-repo-row").hidden = !!S.settings.repo || !!LOCAL;
  $("#lock-error").textContent = message;
  $("#lock-password").value = "";
  $("#lock-confirm").value = "";
  setTimeout(() => $("#lock-password").focus(), 50);
}

async function startLock() {
  document.body.classList.add("locked");
  $("#lock").hidden = false;
  $("#lock-error").textContent = "";
  if (!S.settings.repo && !LOCAL) {
    showLock("login", "Indica il repository GitHub (utente/repository).");
    return;
  }
  try {
    await resolveBranch();
    S.pfEnvelope = await fetchPortfolioEnvelope();
  } catch (err) {
    showLock("login", "Impossibile contattare GitHub: " + err.message);
    return;
  }
  const mode = S.pfEnvelope ? "login" : "setup";
  let remembered = null;
  try {
    remembered = sessionStorage.getItem(PW_SESSION);
  } catch (_) { /* ignora */ }
  if (remembered && mode === "login" && (await tryUnlock(remembered, true))) return;
  showLock(mode);
}

async function tryUnlock(password, remember) {
  try {
    const pf = await decryptJSON(S.pfEnvelope, password);
    await unlocked(password, normalizePortfolio(pf), true, remember);
    return true;
  } catch (_) {
    return false;
  }
}

async function unlocked(password, pf, exists, remember) {
  S.password = password;
  S.pf = exists ? pf : null;
  S.pfDraft = structuredClone(pf);
  S.pfExists = exists;
  // token GitHub: cifrato con la stessa password (migra quello vecchio in chiaro)
  if (S.settings.token) {
    S.token = S.settings.token;
    delete S.settings.token;
    S.settings.tokenEnc = await encryptJSON(S.token, password);
    storeSettings();
  } else if (S.settings.tokenEnc) {
    try {
      S.token = await decryptJSON(S.settings.tokenEnc, password);
    } catch (_) {
      S.token = "";
    }
  }
  try {
    if (remember) sessionStorage.setItem(PW_SESSION, password);
  } catch (_) { /* ignora */ }
  document.body.classList.remove("locked");
  $("#lock").hidden = true;
  if (!exists) toast("Password creata. Salva il portafoglio (anche vuoto) su GitHub per attivarla.");
  loadAll();
}

async function submitLock(ev) {
  ev.preventDefault();
  const mode = $("#lock").dataset.mode;
  const pw = $("#lock-password").value;
  const remember = $("#lock-remember").checked;
  const err = $("#lock-error");
  if (!$("#lock-repo-row").hidden) {
    S.settings.repo = $("#lock-repo").value.trim().replace(/^https:\/\/github\.com\//, "").replace(/\/$/, "");
    storeSettings();
    if (!S.settings.repo) return;
    await startLock();
    return;
  }
  const btn = $("#lock-submit");
  btn.disabled = true;
  try {
    if (mode === "setup") {
      if (pw.length < MIN_PASSWORD) {
        err.textContent = `La password deve avere almeno ${MIN_PASSWORD} caratteri.`;
        return;
      }
      if (pw !== $("#lock-confirm").value) {
        err.textContent = "Le due password non coincidono.";
        return;
      }
      await unlocked(pw, normalizePortfolio({}), false, remember);
    } else if (!(await tryUnlock(pw, remember))) {
      err.textContent = "Password errata.";
      $("#lock-password").select();
    }
  } finally {
    btn.disabled = false;
  }
}

function logout() {
  try {
    sessionStorage.removeItem(PW_SESSION);
  } catch (_) { /* ignora */ }
  location.reload();
}

async function changePassword(ev) {
  ev.preventDefault();
  const cur = $("#pw-current").value, next = $("#pw-new").value, conf = $("#pw-confirm").value;
  if (cur !== S.password) return toast("La password attuale non è corretta.");
  if (next.length < MIN_PASSWORD) return toast(`La nuova password deve avere almeno ${MIN_PASSWORD} caratteri.`);
  if (next !== conf) return toast("Le due nuove password non coincidono.");
  if (!S.token) return toast("Per cambiare password serve il token GitHub (il portafoglio va ricifrato e salvato).");
  const old = S.password;
  S.password = next;
  try {
    await savePortfolio(true);
    if (S.token) S.settings.tokenEnc = await encryptJSON(S.token, next);
    storeSettings();
    try {
      if (sessionStorage.getItem(PW_SESSION)) sessionStorage.setItem(PW_SESSION, next);
    } catch (_) { /* ignora */ }
    ev.target.reset();
    toast("✅ Password cambiata. Aggiorna anche il secret PORTFOLIO_PASSWORD su GitHub.");
  } catch (err) {
    S.password = old;
    toast("Cambio password non riuscito: " + err.message);
  }
}

/* --------------------------------------------------------------- portafoglio */

function normalizePortfolio(pf) {
  return {
    version: 1,
    positions: Array.isArray(pf.positions) ? pf.positions : [],
    sales: Array.isArray(pf.sales) ? pf.sales : [],
    settings: { ...PF_DEFAULTS, ...(pf.settings || {}) },
  };
}

const pfDirty = () => !!(S.pfDraft && (!S.pfExists || JSON.stringify(S.pf) !== JSON.stringify(S.pfDraft)));
const newId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
const todayIso = () => new Date().toISOString().slice(0, 10);

function aggregate(positions) {
  const out = {};
  positions.forEach((p) => {
    const q = +p.quantity;
    if (!(q > 0)) return;
    const h = (out[p.ticker] ||= { ticker: p.ticker, name: p.name || p.ticker, quantity: 0, cost: 0, first_date: null, lots: [] });
    h.quantity += q;
    h.cost += q * +p.price + (+p.fees || 0);
    if (p.date && (!h.first_date || p.date < h.first_date)) h.first_date = p.date;
    h.lots.push(p);
  });
  Object.values(out).forEach((h) => (h.avg_price = h.cost / h.quantity));
  return out;
}

async function savePortfolio(force = false) {
  if (!S.token) {
    toast("Per salvare serve un token GitHub: aprilo in Impostazioni → Collegamento.");
    selectTab("settings");
    return false;
  }
  if (!force && !pfDirty()) return true;
  if (!S.pfSha && S.pfExists) {
    const f = await getRepoFile(PF_PATH);
    S.pfSha = f && f.sha;
  }
  const env = await encryptJSON(S.pfDraft, S.password);
  try {
    S.pfSha = await putRepoFile(PF_PATH, JSON.stringify(env) + "\n", S.pfSha, "Portafoglio aggiornato (cifrato)");
  } catch (err) {
    if (err.status === 409 || err.status === 422) {
      const f = await getRepoFile(PF_PATH);
      S.pfSha = f && f.sha;
      throw new Error("il file è cambiato su GitHub nel frattempo, riprova a salvare");
    }
    throw err;
  }
  S.pf = structuredClone(S.pfDraft);
  S.pfExists = true;
  return true;
}

function addPurchase(ev) {
  ev.preventDefault();
  const f = ev.target.elements;
  const ticker = f.ticker.value.trim().toUpperCase();
  const quantity = parseFloat(f.quantity.value.replace(",", "."));
  const price = parseFloat(f.price.value.replace(",", "."));
  const fees = parseFloat((f.fees.value || "0").replace(",", ".")) || 0;
  if (!ticker || !(quantity > 0) || !(price > 0)) return toast("Indica ticker, quantità e prezzo.");
  const meta = metas()[ticker];
  S.pfDraft.positions.push({
    id: newId(), ticker, name: (meta && meta.name) || ticker, quantity, price, fees,
    date: f.date.value || todayIso(), notes: f.notes.value.trim(),
  });
  ev.target.reset();
  f.date.value = todayIso();
  S.pfSelected = ticker;
  renderPortfolio();
  onDraftChange();
  toast(`Acquisto di ${ticker} aggiunto. Ricordati di salvare.`);
}

// Vendita: scala i lotti dal più vecchio (FIFO) e registra la plusvalenza.
function recordSale(ev) {
  ev.preventDefault();
  const f = ev.target.elements;
  const ticker = S.pfSelected;
  const h = aggregate(S.pfDraft.positions)[ticker];
  const qty = parseFloat(f.quantity.value.replace(",", "."));
  const price = parseFloat(f.price.value.replace(",", "."));
  const fees = parseFloat((f.fees.value || "0").replace(",", ".")) || 0;
  if (!h || !(qty > 0) || !(price > 0)) return toast("Indica quantità e prezzo di vendita.");
  if (qty > h.quantity + 1e-9) return toast(`Ne possiedi solo ${num(h.quantity, 0)}.`);
  let left = qty, basis = 0;
  const lots = S.pfDraft.positions.filter((p) => p.ticker === ticker).sort((a, b) => (a.date || "").localeCompare(b.date || ""));
  for (const lot of lots) {
    if (left <= 1e-9) break;
    const take = Math.min(+lot.quantity, left);
    const share = take / +lot.quantity;
    const lotFees = (+lot.fees || 0) * share;
    basis += take * +lot.price + lotFees;
    lot.quantity = +lot.quantity - take;
    lot.fees = (+lot.fees || 0) - lotFees;
    left -= take;
  }
  S.pfDraft.positions = S.pfDraft.positions.filter((p) => +p.quantity > 1e-9);
  const row = reportRow(ticker);
  const realized = qty * price - fees - basis;
  S.pfDraft.sales.push({
    id: newId(), ticker, name: h.name, quantity: qty, price, fees, date: f.date.value || todayIso(),
    cost_basis: +basis.toFixed(4), realized: +realized.toFixed(2), currency: row ? row.currency : "",
    realized_eur: row && row.fx ? +(realized * row.fx).toFixed(2) : null,
  });
  renderPortfolio();
  onDraftChange();
  toast(`Vendita registrata: ${realized >= 0 ? "plusvalenza" : "minusvalenza"} di ${num(realized)} ${row ? row.currency : ""}. Ricordati di salvare.`);
}

const reportRow = (t) => (S.report && S.report.holdings ? S.report.holdings.find((r) => r.ticker === t) : null);

function verdictChip(v) {
  if (!v) return `<span class="verdict none">in attesa</span>`;
  const text = { vendi: "Vendere in parte", valuta: "Da tenere d'occhio", mantieni: "Nessun segnale" }[v.code];
  return `<span class="verdict ${v.code}">${text}</span>`;
}

function portfolioRows() {
  const agg = aggregate(S.pfDraft ? S.pfDraft.positions : []);
  const quotes = {};
  ((S.data.snapshot || {}).quotes || []).forEach((q) => (quotes[q.ticker] = q));
  return Object.values(agg).map((h) => {
    const r = reportRow(h.ticker);
    // i dati del resoconto valgono solo se le quantità coincidono con quelle attuali
    const fresh = r && Math.abs(r.quantity - h.quantity) < 1e-9 && Math.abs(r.avg_price - h.avg_price) < 1e-6;
    const price = r ? r.price : quotes[h.ticker] ? quotes[h.ticker].price : null;
    const fx = r ? r.fx : null;
    const value = price != null ? h.quantity * price : null;
    return {
      ...h,
      name: (r && r.name) || h.name,
      currency: r ? r.currency : ((metas()[h.ticker] || {}).currency || ""),
      price,
      day_pct: r ? r.day_pct : quotes[h.ticker] ? quotes[h.ticker].pct : null,
      value_eur: value != null && fx ? value * fx : null,
      pnl_pct: price != null ? (price / h.avg_price - 1) * 100 : null,
      pnl_eur: value != null && fx ? (value - h.cost) * fx : null,
      weight_pct: fresh ? r.weight_pct : null,
      verdict: fresh ? r.verdict : null,
      report: r,
      fresh,
    };
  });
}

function renderPortfolio() {
  const el = $("#tab-portfolio");
  if (!el || !S.pfDraft) return;
  const rows = portfolioRows();
  const rep = S.report;
  const t = rep ? rep.totals : null;
  const eur = (x) => (x == null ? "—" : `${x < 0 ? "−" : ""}${num(Math.abs(x), 0)} €`);
  const eurS = (x) => (x == null ? "—" : `${x < 0 ? "−" : "+"}${num(Math.abs(x), 0)} €`);

  // stato del resoconto
  const status = $("#pf-status");
  let msg = "";
  if (!S.pfExists) msg = "La password non è ancora salvata: registra i tuoi acquisti (o salva anche il portafoglio vuoto) con <b>Salva su GitHub</b>.";
  else if (S.reportError) msg = S.reportError;
  else if (!rep) msg = "Consigli non ancora calcolati. Imposta il secret <code>PORTFOLIO_PASSWORD</code> su GitHub (la stessa password della dashboard) e attendi il prossimo giro dello <b>Scanner</b>, o avvialo a mano da Actions.";
  else if (rows.some((r) => !r.fresh)) msg = "Hai modifiche non ancora analizzate: i consigli si aggiornano al prossimo giro dello Scanner dopo il salvataggio.";
  status.hidden = !msg;
  status.innerHTML = msg;

  const realized = (S.pfDraft.sales || []).reduce((a, s) => a + (s.realized_eur || 0), 0);
  $("#pf-kpis").innerHTML = [
    kpi("Valore attuale", t ? eur(t.value_eur) : "—", t ? `investito ${eur(t.cost_eur)}` : `${rows.length} titoli`),
    kpi("Guadagno / perdita", t ? eurS(t.pnl_eur) : "—", t ? `${pct(t.pnl_pct, 2)} · netto tasse ≈ ${eurS(t.net_pnl_eur)}` : "", t ? cls(t.pnl_eur) : ""),
    kpi("Oggi", t && t.day_pnl_eur != null ? eurS(t.day_pnl_eur) : "—", rep ? `aggiornato ${dateIt(rep.day)} ${time(rep.generated)}` : "", t ? cls(t.day_pnl_eur) : ""),
    kpi("Segnali di vendita", t ? `${t.to_sell} · ${t.to_watch}` : "—", "da vendere in parte · da tenere d'occhio"),
  ].join("") + (realized ? kpi("Già realizzato", eurS(realized), "dalle vendite registrate", cls(realized)) : "");

  const attention = rows.filter((r) => r.verdict && r.verdict.code !== "mantieni")
    .sort((a, b) => b.verdict.score - a.verdict.score);
  const att = $("#pf-attention");
  att.hidden = !attention.length;
  att.innerHTML = `<div class="card-head"><h2>Da guardare adesso</h2><span class="muted small">segnali tecnici, la decisione è tua</span></div>` +
    attention.map((r) => `<button class="attn" data-pick="${esc(r.ticker)}">${verdictChip(r.verdict)}
      <span><b>${esc(r.name)}</b> <span class="tk muted">${esc(r.ticker)}</span></span>
      <span class="muted small">${esc(r.report.signals.filter((s) => s.level !== "info").map((s) => s.text.split(":")[0].split(".")[0]).join(" · "))}</span>
      <span class="num ${cls(r.pnl_pct)}"><b>${pct(r.pnl_pct)}</b></span></button>`).join("");

  table($("#pf-table"), "portfolio", [
    { key: "ticker", label: "Titolo", fmt: (r) => `<b>${esc(r.name)}</b><br><span class="tk muted">${esc(r.ticker)}</span>`, sort: (r) => r.name },
    { key: "quantity", label: "Quantità", num: true, fmt: (r) => num(r.quantity, Number.isInteger(r.quantity) ? 0 : 3) },
    { key: "avg_price", label: "Prezzo medio", num: true, cls: "hide-sm", fmt: (r) => `${num(r.avg_price)} <span class="muted small">${esc(r.currency)}</span>` },
    { key: "price", label: "Prezzo", num: true, fmt: (r) => num(r.price) },
    { key: "day_pct", label: "Oggi", num: true, cls: "hide-sm", fmt: (r) => `<span class="${cls(r.day_pct)}">${pct(r.day_pct, 2)}</span>` },
    { key: "value_eur", label: "Valore", num: true, fmt: (r) => eur(r.value_eur) },
    { key: "pnl_pct", label: "Risultato", num: true, fmt: (r) => `<b class="${cls(r.pnl_pct)}">${pct(r.pnl_pct)}</b><br><span class="small ${cls(r.pnl_eur)}">${eurS(r.pnl_eur)}</span>` },
    { key: "weight_pct", label: "Peso", num: true, cls: "hide-sm", fmt: (r) => (r.weight_pct == null ? "—" : `${num(r.weight_pct, 1)}%`) },
    { key: "verdict", label: "Valutazione", sort: (r) => (r.verdict ? -r.verdict.score : 99), fmt: (r) => verdictChip(r.verdict) },
  ], rows, { sortKey: "verdict", rowClass: (r) => `clickable${r.ticker === S.pfSelected ? " selected" : ""}` });
  $("#pf-table").querySelectorAll("tbody tr").forEach((tr, i) => {
    tr.dataset.pick = tr.querySelector(".tk") ? tr.querySelector(".tk").textContent : "";
  });
  if (!rows.length) $("#pf-table").innerHTML = `<tbody><tr><td class="empty">Nessuna azione: registra il tuo primo acquisto qui sotto.</td></tr></tbody>`;

  renderPortfolioDetail(rows.find((r) => r.ticker === S.pfSelected));
  renderPortfolioSettings();
  renderSales();

  const dl = $("#pf-tickers");
  if (dl && !dl.childElementCount) {
    dl.innerHTML = ((S.data.universe || {}).items || []).map((i) => `<option value="${esc(i.ticker)}">${esc(i.name)}</option>`).join("");
  }
}

function renderPortfolioDetail(r) {
  const box = $("#pf-detail");
  if (!r) {
    box.innerHTML = `<p class="muted small">Tocca un titolo per vedere segnali, lotti e registrare una vendita.</p>`;
    return;
  }
  const rep = r.fresh ? r.report : null;
  const ind = (label, value) => `<div class="ind"><span class="muted small">${label}</span><b>${value}</b></div>`;
  const sig = rep
    ? [...rep.signals.map((s) => `<li class="lvl-${s.level}"><span class="lvl">${{ strong: "Forte", warn: "Attenzione", info: "Info" }[s.level]}</span>${esc(s.text)}</li>`),
       ...rep.holds.map((h) => `<li class="lvl-hold"><span class="lvl">Per aspettare</span>${esc(h.text)}</li>`)].join("")
    : "";
  box.innerHTML = `
    <div class="detail-head">
      <div><h3>${esc(r.name)} <span class="tk muted">${esc(r.ticker)}</span></h3>
        <div class="muted small">${num(r.quantity, Number.isInteger(r.quantity) ? 0 : 3)} azioni · prezzo medio ${num(r.avg_price)} ${esc(r.currency)} · dal ${dateIt(r.first_date)}
        · <a href="${yahoo(r.ticker)}" target="_blank" rel="noopener">Yahoo Finance</a></div></div>
      ${verdictChip(r.verdict)}
    </div>
    ${rep ? `<ul class="signals">${sig || `<li class="lvl-hold"><span class="lvl">OK</span>Nessuna regola di vendita scattata.</li>`}</ul>
    <div class="inds">
      ${ind("RSI 14", rep.rsi == null ? "—" : num(rep.rsi, 0))}
      ${ind("vs media 200 gg", pct(rep.vs_sma200_pct))}
      ${ind("Dal massimo da quando lo hai", pct(rep.from_max_pct))}
      ${ind("Massimo 52 sett.", num(rep.high_52w))}
      ${ind("Obiettivo analisti", rep.target_price ? `${num(rep.target_price)} (${pct((rep.target_price / rep.price - 1) * 100)})` : "—")}
      ${ind("P/E", rep.pe ? num(rep.pe, 1) : "—")}
    </div>` : `<p class="muted small">Segnali disponibili dopo il prossimo giro dello Scanner.</p>`}
    <div class="grid2 tight">
      <div>
        <h4>Acquisti (lotti)</h4>
        <table class="data compact"><thead><tr><th>Data</th><th class="num">Qtà</th><th class="num">Prezzo</th><th class="num">Comm.</th><th></th></tr></thead><tbody>
        ${r.lots.map((l) => `<tr><td>${dateIt(l.date)}${l.notes ? `<br><span class="muted small">${esc(l.notes)}</span>` : ""}</td><td class="num">${num(+l.quantity, Number.isInteger(+l.quantity) ? 0 : 3)}</td>
          <td class="num">${num(+l.price)}</td><td class="num">${num(+l.fees || 0)}</td>
          <td><button class="btn small danger" data-del-lot="${esc(l.id)}" title="Elimina questo acquisto">×</button></td></tr>`).join("")}
        </tbody></table>
      </div>
      <form id="pf-sell" class="form-grid sell">
        <h4 class="span2">Registra una vendita</h4>
        <label>Quantità <input name="quantity" inputmode="decimal" value="${r.quantity}"></label>
        <label>Prezzo (${esc(r.currency || "valuta")}) <input name="price" inputmode="decimal" value="${r.price != null ? +(+r.price).toFixed(4) : ""}"></label>
        <label>Data <input name="date" type="date" value="${todayIso()}"></label>
        <label>Commissioni <input name="fees" inputmode="decimal" placeholder="0"></label>
        <button class="btn span2" type="submit">Registra vendita</button>
      </form>
    </div>`;
  $("#pf-sell").addEventListener("submit", recordSale);
}

function renderPortfolioSettings() {
  const form = $("#pf-settings");
  const s = S.pfDraft.settings;
  Object.entries(s).forEach(([k, v]) => {
    const el = form.elements[k];
    if (!el || document.activeElement === el) return;
    if (el.type === "checkbox") el.checked = !!v;
    else el.value = v;
  });
}

function renderSales() {
  const sales = (S.pfDraft.sales || []).slice().reverse();
  $("#pf-sales-card").hidden = !sales.length;
  table($("#pf-sales"), "sales", [
    { key: "date", label: "Data", fmt: (s) => dateIt(s.date) },
    { key: "ticker", label: "Titolo", fmt: (s) => `${esc(s.name)} <span class="tk muted">${esc(s.ticker)}</span>` },
    { key: "quantity", label: "Qtà", num: true, fmt: (s) => num(s.quantity, Number.isInteger(s.quantity) ? 0 : 3) },
    { key: "price", label: "Prezzo", num: true, fmt: (s) => `${num(s.price)} <span class="muted small">${esc(s.currency || "")}</span>` },
    { key: "realized", label: "Plus/minusvalenza", num: true, fmt: (s) => `<b class="${cls(s.realized)}">${num(s.realized)}</b>` + (s.realized_eur != null ? `<br><span class="small muted">${num(s.realized_eur, 0)} €</span>` : "") },
    { key: "del", label: "", nosort: true, fmt: (s) => `<button class="btn small danger" data-del-sale="${esc(s.id)}" title="Elimina dalla lista (non ripristina i lotti)">×</button>` },
  ], sales, { sortKey: "date", sortDir: -1 });
}

function bindPortfolio() {
  $("#lock-form").addEventListener("submit", submitLock);
  $("#logout").addEventListener("click", logout);
  $("#pw-form").addEventListener("submit", changePassword);
  $("#pf-buy").addEventListener("submit", addPurchase);
  $("#pf-buy").elements.date.value = todayIso();
  $("#pf-settings").addEventListener("input", (ev) => {
    const el = ev.target;
    if (!el.name) return;
    const v = el.type === "checkbox" ? el.checked : parseFloat(el.value);
    if (el.type !== "checkbox" && Number.isNaN(v)) return;
    S.pfDraft.settings[el.name] = v;
    onDraftChange();
  });
  $("#tab-portfolio").addEventListener("click", (ev) => {
    const pick = ev.target.closest("[data-pick]");
    const delLot = ev.target.closest("[data-del-lot]");
    const delSale = ev.target.closest("[data-del-sale]");
    if (delLot) {
      if (!confirm("Eliminare questo acquisto?")) return;
      S.pfDraft.positions = S.pfDraft.positions.filter((p) => p.id !== delLot.dataset.delLot);
    } else if (delSale) {
      if (!confirm("Eliminare questa vendita dallo storico?")) return;
      S.pfDraft.sales = S.pfDraft.sales.filter((s) => s.id !== delSale.dataset.delSale);
    } else if (pick && pick.dataset.pick) {
      S.pfSelected = pick.dataset.pick;
      renderPortfolio();
      $("#pf-detail").scrollIntoView({ behavior: "smooth", block: "nearest" });
      return;
    } else return;
    renderPortfolio();
    onDraftChange();
  });
}

async function loadPortfolioReport() {
  S.reportError = "";
  const env = await fetchFile(PF_REPORT, "data").catch(() => null);
  if (!env) {
    S.report = null;
    return;
  }
  try {
    S.report = await decryptJSON(env, S.password);
  } catch (_) {
    S.report = null;
    S.reportError = "I consigli sono cifrati con una password diversa: aggiorna il secret <code>PORTFOLIO_PASSWORD</code> su GitHub con la password attuale.";
  }
}
