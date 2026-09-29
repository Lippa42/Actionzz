/* Actionzz – simulatore di compravendita (soldi finti, costi e tasse veri).
 * Gli ordini e i versamenti vanno in config/simulator.enc.json (cifrato); lo scanner li esegue a borsa aperta
 * e pubblica il conto in simulator_state.enc.json sul branch `data`. Deve rispecchiare actionzz/simulator.py. */
"use strict";

const SIM_PATH = "config/simulator.enc.json";
const SIM_STATE = "simulator_state.enc.json";
const EU_SUFFIX = [".L", ".DE", ".PA", ".MI", ".MC", ".AS", ".BR", ".LS", ".IR", ".HE", ".VI", ".SW", ".ST", ".CO", ".OL", ".WA"];
const NON_EUR = { ".L": "GBp", ".SW": "CHF", ".ST": "SEK", ".CO": "DKK", ".OL": "NOK", ".WA": "PLN" };
const TX_TAXES = { ".MI": ["Tobin tax", 0.2], ".PA": ["tassa francese", 0.4], ".MC": ["tassa spagnola", 0.2], ".L": ["stamp duty UK", 0.5], ".IR": ["stamp duty IE", 1.0] };
const TX_LABEL = { buy: "Acquisto", sell: "Vendita", deposit: "Versamento", dividend: "Dividendo", fee: "Costo", tax_payment: "Imposte" };

const sfx = (t) => { const i = t.lastIndexOf("."); return i > 0 ? t.slice(i).toUpperCase() : ""; };
const marketOf = (t) => (sfx(t) === ".MI" ? "it" : EU_SUFFIX.includes(sfx(t)) ? "eu" : "us");
const currencyOf = (t) => NON_EUR[sfx(t)] || (EU_SUFFIX.includes(sfx(t)) ? "EUR" : "USD");

function simCommission(amount, s, market) {
  const f = s.fees[market] || s.fees.it;
  if (f.free_from && amount >= f.free_from) return 0; // gratis sopra una soglia (es. Scalable PRIME+ da 250 €)
  let fee = f.fixed + (amount * f.pct) / 100;
  if (f.min > 0) fee = Math.max(fee, f.min);
  if (f.max > 0) fee = Math.min(fee, f.max);
  return Math.round(fee * 100) / 100;
}

function brokerSettings(b, base) {
  return { ...base, broker: b.id, fees: structuredClone(b.fees), fx_spread_pct: b.fx_spread_pct, slippage_pct: b.slippage_pct,
    connectivity_fee: b.connectivity_fee || 0, monthly_fee: b.monthly_fee || 0, regime: b.regime };
}

const SIM_BASE = { transaction_taxes: true, capital_gains_tax_pct: 26, dividend_tax_pct: 26, stamp_duty_pct: 0.2 };

/* --------------------------------------------------------------- dati */

async function loadBrokers() {
  if (S.brokers) return;
  try {
    const res = await fetch("brokers.json", { cache: "no-store" });
    S.brokers = res.ok ? await res.json() : { brokers: [] };
  } catch (_) {
    S.brokers = { brokers: [] };
  }
}

async function loadSimulator() {
  await loadBrokers();
  S.simError = "";
  try {
    let env = null;
    if (S.token && !LOCAL) {
      const f = await getRepoFile(SIM_PATH);
      S.simSha = f && f.sha;
      env = f && JSON.parse(f.text);
    } else {
      env = LOCAL ? await fetch(LOCAL + "simulator.enc.json", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)) : await fetchFile(SIM_PATH, S.settings.branch);
    }
    S.sim = env ? await decryptJSON(env, S.password) : null;
  } catch (err) {
    S.sim = null;
    S.simError = "Impossibile aprire il simulatore: " + err.message;
  }
  const stEnv = await fetchFile(SIM_STATE, "data").catch(() => null);
  try {
    S.simState = stEnv ? await decryptJSON(stEnv, S.password) : null;
  } catch (_) {
    S.simState = null;
    S.simError = "Il conto simulato è cifrato con un'altra password: aggiorna il secret <code>PORTFOLIO_PASSWORD</code>.";
  }
  if (S.simState && S.sim && S.simState.epoch !== S.sim.epoch) S.simState = null; // simulazione ricominciata
}

async function saveSim(message) {
  if (!S.token) {
    toast("Per usare il simulatore serve il token GitHub: aprilo in Impostazioni → Collegamento.");
    selectTab("settings");
    return false;
  }
  try {
    if (!S.simSha) {
      const f = await getRepoFile(SIM_PATH);
      S.simSha = f && f.sha;
    }
    const env = await encryptJSON(S.sim, S.password);
    S.simSha = await putRepoFile(SIM_PATH, JSON.stringify(env) + "\n", S.simSha, message);
    return true;
  } catch (err) {
    if (err.status === 409 || err.status === 422) {
      toast("Il simulatore è cambiato nel frattempo (forse da Telegram): ricarico, riprova.");
      await loadSimulator();
      renderSimulator();
    } else {
      toast("Salvataggio non riuscito: " + err.message);
    }
    return false;
  }
}

const rid = () => crypto.getRandomValues(new Uint32Array(2)).reduce((a, x) => a + x.toString(16), "");

/* --------------------------------------------------------------- azioni */

async function createSim(ev) {
  ev.preventDefault();
  const budget = parseFloat($("#sim-budget").value.replace(/\./g, "").replace(",", "."));
  if (!(budget >= 100)) return toast("Il budget deve essere almeno 100 €.");
  const broker = (S.brokers.brokers || []).find((b) => b.id === $("#sim-broker-new").value);
  const keep = S.sim ? S.sim.settings : null;
  S.sim = {
    version: 1,
    epoch: rid(),
    deposits: [{ id: rid(), amount: budget, date: todayIso(), note: "budget iniziale" }],
    orders: [],
    settings: broker ? brokerSettings(broker, { ...SIM_BASE, ...(keep || {}) }) : keep,
  };
  S.simState = null;
  if (await saveSim("Simulatore: nuova simulazione")) toast("🧪 Simulazione creata. Il conto si aggiorna al prossimo giro dello scanner.");
  renderSimulator();
}

async function deposit(ev) {
  ev.preventDefault();
  const amount = parseFloat($("#sim-deposit-amount").value.replace(/\./g, "").replace(",", "."));
  if (!(amount > 0)) return toast("Indica un importo.");
  S.sim.deposits.push({ id: rid(), amount, date: todayIso(), note: "versamento" });
  if (await saveSim("Simulatore: versamento")) {
    toast(`Versati ${num(amount, 2)} €: saranno disponibili al prossimo giro dello scanner.`);
    ev.target.reset();
  }
  renderSimulator();
}

function nextSessionIso(validity) {
  const now = new Date();
  const d = new Date(now);
  const hm = romeNow().hm;
  if (hm >= ((S.draft || {}).market_close || "17:30")) d.setDate(d.getDate() + 1);
  while ([0, 6].includes(d.getDay())) d.setDate(d.getDate() + 1);
  if (validity === "gtc") d.setDate(d.getDate() + 90);
  return d.toISOString().slice(0, 10);
}

async function placeOrder(ev) {
  ev.preventDefault();
  const f = ev.target.elements;
  const ticker = f.ticker.value.trim().toUpperCase();
  const side = f.side.value;
  const mode = f.mode.value;
  const size = parseFloat((f.size.value || "").replace(/\./g, "").replace(",", "."));
  const limit = f.kind.value === "limit" ? parseFloat((f.limit.value || "").replace(",", ".")) : null;
  if (!ticker) return toast("Indica il ticker.");
  if (!(size > 0) && !(side === "sell" && mode === "all")) return toast("Indica quantità o importo.");
  if (mode === "qty" && !Number.isInteger(size)) return toast("Si comprano e vendono solo azioni intere.");
  if (f.kind.value === "limit" && !(limit > 0)) return toast("Indica il prezzo limite.");
  const order = {
    id: rid(), created: new Date().toISOString(), ticker, side, validity: f.validity.value,
    valid_until: nextSessionIso(f.validity.value),
    ...(mode === "qty" ? { quantity: size } : mode === "amount" ? { amount: size } : { all: true }),
    ...(limit ? { limit } : {}),
  };
  S.sim.orders.push(order);
  if (await saveSim(`Simulatore: ordine ${side === "buy" ? "acquisto" : "vendita"} ${ticker}`)) {
    toast("Ordine inserito: verrà eseguito al prossimo controllo a borsa aperta (entro pochi minuti in orario di borsa).");
    ev.target.reset();
    f.side.value = side;
    renderOrderPreview();
  } else {
    S.sim.orders.pop();
  }
  renderSimulator();
}

async function cancelOrder(id) {
  const o = S.sim.orders.find((x) => x.id === id);
  if (!o) return;
  o.cancelled = true;
  if (await saveSim("Simulatore: ordine annullato")) toast("Ordine annullato.");
  renderSimulator();
}

async function applyBroker(id) {
  const b = (S.brokers.brokers || []).find((x) => x.id === id);
  if (!b || !S.sim) return;
  S.sim.settings = brokerSettings(b, S.sim.settings);
  if (await saveSim(`Simulatore: tariffe ${b.name}`)) toast(`Ora simuli le tariffe di ${b.name}. Valgono dai prossimi ordini.`);
  renderSimulator();
}

async function saveSimCosts(ev) {
  ev.preventDefault();
  const f = ev.target.elements;
  const s = S.sim.settings;
  const n = (x) => parseFloat(String(x).replace(",", ".")) || 0;
  ["it", "eu", "us"].forEach((m) => {
    s.fees[m] = { ...s.fees[m], fixed: n(f[`${m}_fixed`].value), pct: n(f[`${m}_pct`].value), min: n(f[`${m}_min`].value), max: n(f[`${m}_max`].value) };
  });
  s.fx_spread_pct = n(f.fx_spread_pct.value);
  s.slippage_pct = n(f.slippage_pct.value);
  s.connectivity_fee = n(f.connectivity_fee.value);
  s.regime = f.regime.value;
  s.transaction_taxes = f.transaction_taxes.checked;
  s.broker = "custom";
  if (await saveSim("Simulatore: costi personalizzati")) toast("Costi salvati.");
  renderSimulator();
}

/* --------------------------------------------------------------- calcoli */

function quoteFor(ticker) {
  const st = S.simState;
  if (st && st.prices && st.prices[ticker]) return { price: st.prices[ticker].price, fx: st.prices[ticker].fx };
  const q = ((S.data.snapshot || {}).quotes || []).find((x) => x.ticker === ticker);
  if (!q) return null;
  const cur = currencyOf(ticker);
  const rates = (S.report && S.report.rates) || {};
  const fx = cur === "EUR" ? 1 : rates[cur];
  return fx ? { price: q.price, fx } : { price: q.price, fx: null };
}

function estimate(ticker, side, qty, price, fx, s) {
  const slip = s.slippage_pct / 100;
  const fill = side === "buy" ? price * (1 + slip) : price * (1 - slip);
  const gross = qty * fill * fx;
  const fxCost = currencyOf(ticker) !== "EUR" ? gross * s.fx_spread_pct / 100 : 0;
  const comm = simCommission(gross, s, marketOf(ticker));
  const [taxName, rate] = side === "buy" && s.transaction_taxes && TX_TAXES[sfx(ticker)] ? TX_TAXES[sfx(ticker)] : ["", 0];
  const txTax = gross * rate / 100;
  return { fill, gross, fxCost, comm, taxName, txTax, total: side === "buy" ? gross + fxCost + comm + txTax : gross - fxCost - comm };
}

function renderOrderPreview() {
  const box = $("#sim-preview");
  const f = $("#sim-order").elements;
  const t = f.ticker.value.trim().toUpperCase();
  const side = f.side.value;
  const mode = f.mode.value;
  f.size.disabled = mode === "all";
  f.limit.disabled = f.kind.value !== "limit";
  $("#sim-mode-all").hidden = side !== "sell";
  if (side === "buy" && mode === "all") f.mode.value = "qty";
  if (!S.sim || !t) {
    box.innerHTML = `<span class="muted small">Inserisci un ticker per vedere la stima dei costi.</span>`;
    return;
  }
  const q = quoteFor(t);
  const s = S.sim.settings;
  const size = parseFloat((f.size.value || "").replace(/\./g, "").replace(",", "."));
  const pos = S.simState && S.simState.positions[t];
  let qty = mode === "qty" ? size : mode === "all" ? (pos ? pos.qty : 0) : null;
  if (!q || !q.fx) {
    box.innerHTML = `<span class="muted small">Prezzo non disponibile qui: l'ordine verrà eseguito al prezzo del momento. Commissione con ${esc(brokerName())}: ${
      ["it", "eu", "us"].includes(marketOf(t)) ? describeFee(s.fees[marketOf(t)]) : ""}.</span>`;
    return;
  }
  if (mode === "amount" && size > 0) qty = Math.floor(size / (q.price * q.fx * (1 + s.slippage_pct / 100) * 1.01));
  if (!(qty > 0)) {
    box.innerHTML = `<span class="muted small">Prezzo attuale ${num(q.price)} ${esc(currencyOf(t))}.</span>`;
    return;
  }
  const e = estimate(t, side, qty, q.price, q.fx, s);
  let taxLine = "";
  if (side === "sell" && pos) {
    const gain = e.total - pos.cost_eur * qty / pos.qty;
    taxLine = `<div><span>${gain >= 0 ? "Plusvalenza" : "Minusvalenza"} stimata</span><b class="${cls(gain)}">${num(gain)} €</b></div>` +
      (gain > 0 ? `<div><span>Tasse 26% (prima dello zainetto)</span><b>${num(gain * s.capital_gains_tax_pct / 100)} €</b></div>` : "");
  }
  box.innerHTML = `<div class="est">
    <div><span>${num(qty, 0)} azioni × ${num(e.fill)} ${esc(currencyOf(t))}${q.fx !== 1 ? ` (cambio ${num(q.fx, 4)})` : ""}</span><b>${num(e.gross)} €</b></div>
    <div><span>Commissione ${esc(brokerName())}</span><b>${num(e.comm)} €</b></div>
    ${e.txTax ? `<div><span>${esc(e.taxName)} (${num(TX_TAXES[sfx(t)][1], 1)}%)</span><b>${num(e.txTax)} €</b></div>` : ""}
    ${e.fxCost ? `<div><span>Costo del cambio</span><b>${num(e.fxCost)} €</b></div>` : ""}
    ${taxLine}
    <div class="tot"><span>${side === "buy" ? "Totale da pagare" : "Incasso prima delle tasse"}</span><b>${num(e.total)} €</b></div>
    ${side === "buy" ? `<div class="muted small">Costi di acquisto + vendita: ${num(((e.comm * 2 + e.txTax + e.fxCost * 2) / e.gross) * 100, 2)}% del controvalore: il titolo deve salire almeno così per andare in pari.</div>` : ""}
  </div>`;
}

const brokerName = () => {
  const id = S.sim && S.sim.settings.broker;
  const b = (S.brokers && S.brokers.brokers || []).find((x) => x.id === id);
  return b ? b.name : "personalizzato";
};

function describeFee(f) {
  const parts = [];
  if (f.fixed) parts.push(`${num(f.fixed)} €`);
  if (f.pct) parts.push(`${num(f.pct, 2)}%`);
  let s = parts.join(" + ") || "0 €";
  if (f.min) s += ` (min ${num(f.min)} €`;
  if (f.max) s += `${f.min ? "," : " ("} max ${num(f.max)} €`;
  if (f.min || f.max) s += ")";
  return s;
}

/* --------------------------------------------------------------- render */

function lineChart(el, points, series) {
  if (!el.clientWidth) return; // scheda nascosta: lo disegno quando diventa visibile
  if (!points.length) {
    el.innerHTML = `<div class="empty">Il grafico si riempie giorno dopo giorno.</div>`;
    return;
  }
  const W = Math.max(el.clientWidth, 280), H = 240;
  const m = { t: 12, r: 92, b: 26, l: 60 };
  const vals = points.flatMap((p) => series.map((s) => p[s.key]));
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo) * 0.1 || hi * 0.05 || 1;
  lo -= pad; hi += pad;
  const step = niceStep((hi - lo) / 4);
  lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step;
  const x = (i) => m.l + (points.length === 1 ? (W - m.l - m.r) / 2 : (i / (points.length - 1)) * (W - m.l - m.r));
  const y = (v) => m.t + ((hi - v) / (hi - lo)) * (H - m.t - m.b);
  let svg = "";
  for (let v = lo; v <= hi + 1e-9; v += step) {
    svg += `<line class="gridline" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${m.l - 6}" y="${y(v)}" dy="0.32em" text-anchor="end">${num(v, 0)} €</text>`;
  }
  const labelsIdx = [0, Math.floor((points.length - 1) / 2), points.length - 1].filter((v, i, a) => a.indexOf(v) === i);
  labelsIdx.forEach((i) => (svg += `<text x="${x(i)}" y="${H - 8}" text-anchor="middle">${dateIt(points[i].day).slice(0, 5)}</text>`));
  // etichette dirette a fine linea, distanziate se i valori sono vicini
  const ends = series.map((s) => y(points[points.length - 1][s.key]));
  if (ends.length === 2 && Math.abs(ends[0] - ends[1]) < 16) {
    const mid = (ends[0] + ends[1]) / 2, up = ends[0] <= ends[1] ? 0 : 1;
    ends[up] = mid - 8; ends[1 - up] = mid + 8;
  }
  series.forEach((s, si) => {
    const d = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[s.key]).toFixed(1)}`).join("");
    svg += `<path d="${d}" fill="none" class="${s.cls}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"${s.dash ? ' stroke-dasharray="5 4"' : ""}/>`;
    const last = points[points.length - 1][s.key];
    svg += `<circle cx="${x(points.length - 1)}" cy="${y(last)}" r="4" class="${s.cls}-dot"/>`;
    svg += `<text x="${x(points.length - 1) + 8}" y="${ends[si]}" dy="0.32em" class="dlabel">${esc(s.name)}</text>`;
  });
  svg += `<line id="sim-cross" class="baseline" x1="0" x2="0" y1="${m.t}" y2="${H - m.b}" visibility="hidden"/>`;
  svg += `<rect class="hit" x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}"/>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Valore del conto simulato nel tempo">${svg}</svg>`;
  const cross = el.querySelector("#sim-cross");
  const hit = el.querySelector(".hit");
  const move = (ev) => {
    const r = hit.getBoundingClientRect();
    const i = Math.round(((ev.clientX - r.left) / r.width) * (points.length - 1));
    const p = points[Math.max(0, Math.min(points.length - 1, i))];
    const cx = x(points.indexOf(p));
    cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.setAttribute("visibility", "visible");
    showTip(`<div>${dateIt(p.day)}</div>${series.map((s) => `<div>${esc(s.name)} <b>${num(p[s.key], 0)} €</b></div>`).join("")}
      <div class="muted">Risultato ${num(p.equity - p.deposited, 0)} €</div>`, ev);
  };
  hit.addEventListener("pointermove", move);
  hit.addEventListener("pointerdown", move);
  hit.addEventListener("pointerleave", () => { hideTip(); cross.setAttribute("visibility", "hidden"); });
}

function renderBrokerTable() {
  const list = (S.brokers && S.brokers.brokers) || [];
  const current = S.sim ? S.sim.settings.broker : $("#sim-broker-new").value;
  const rows = list.map((b) => {
    const s = brokerSettings(b, SIM_BASE);
    const it = simCommission(2000, s, "it"), eu = simCommission(2000, s, "eu"), us = simCommission(2000, s, "us") + 2000 * s.fx_spread_pct / 100;
    return { ...b, it, eu, us, avg: (it + eu + us) / 3 };
  }).sort((a, b) => a.avg - b.avg);
  table($("#sim-brokers"), "brokers", [
    { key: "name", label: "Broker", fmt: (b) => `<b>${esc(b.name)}</b>${b.id === current ? ' <span class="tag">in uso</span>' : ""}<br><span class="muted small">${esc(b.summary)}</span>` },
    { key: "it", label: "Italia", num: true, fmt: (b) => `${num(b.it)} €` },
    { key: "eu", label: "Europa", num: true, fmt: (b) => `${num(b.eu)} €` },
    { key: "us", label: "USA (con cambio)", num: true, fmt: (b) => `${num(b.us)} €` },
    { key: "monthly_fee", label: "Canone", num: true, fmt: (b) => (b.monthly_fee ? `${num(b.monthly_fee)} €/mese` : "—") },
    { key: "regime", label: "Fisco", fmt: (b) => `<span class="tag">${b.regime}</span>` },
    { key: "use", label: "", nosort: true, fmt: (b) => (S.sim ? `<button class="btn small" data-broker="${esc(b.id)}"${b.id === current ? " disabled" : ""}>Usa</button>` : "") },
  ], rows, { sortKey: "avg" });
  $("#sim-brokers-note").innerHTML = `Costo di un ordine da 2.000 € (per gli USA incluso il cambio), dal più economico. ${esc((S.brokers || {}).note || "")} Verificato il ${dateIt((S.brokers || {}).checked)}.`;
}

function renderSimulator() {
  const root = $("#tab-simulator");
  if (!root || !S.password) return;
  const sim = S.sim, st = S.simState;
  $("#sim-error").hidden = !S.simError;
  $("#sim-error").innerHTML = S.simError || "";
  $("#sim-setup").hidden = !!sim;
  $("#sim-body").hidden = !sim;
  const sel = $("#sim-broker-new");
  if (!sel.childElementCount && S.brokers) {
    sel.innerHTML = (S.brokers.brokers || []).map((b) => `<option value="${esc(b.id)}">${esc(b.name)}</option>`).join("");
    sel.value = "fineco_trading";
  }
  renderBrokerTable();
  if (!sim) return;

  const t = st && st.totals;
  const eur = (x, d = 0) => (x == null ? "—" : `${x < 0 ? "−" : ""}${num(Math.abs(x), d)} €`);
  const eurS = (x, d = 0) => (x == null ? "—" : `${x < 0 ? "−" : "+"}${num(Math.abs(x), d)} €`);
  const deposited = sim.deposits.reduce((a, d) => a + +d.amount, 0);
  $("#sim-kpis").innerHTML = [
    kpi("Valore del conto", t ? eur(t.equity) : eur(deposited), t ? `versati ${eur(t.deposited)}` : "in attesa del primo aggiornamento"),
    kpi("Risultato", t ? eurS(t.pnl) : "—", t ? pct(t.pnl_pct, 2) : "", t ? cls(t.pnl) : ""),
    kpi("Netto se vendi tutto oggi", t ? eur(t.net_equity) : "—", t ? `${pct(t.net_pnl_pct, 2)} dopo commissioni e tasse` : "", t ? cls(t.net_pnl) : ""),
    kpi("Liquidità", t ? eur(t.cash, 2) : "—", t ? `investiti ${eur(t.positions_value)}` : ""),
  ].join("") + (t ? [
    kpi("Costi e tasse pagati", eur(t.total_costs, 2), costBreakdown(st.costs)),
    kpi("Zainetto fiscale", eur(t.losses_available, 2), "minusvalenze da compensare (4 anni)"),
    t.tax_due ? kpi("Tasse da pagare", eur(t.tax_due, 2), "regime dichiarativo: saldo il 30 giugno") : "",
    kpi("Dividendi netti", eur(t.dividends, 2), `plus/minus realizzate ${eurS(t.realized, 2)}`),
  ].join("") : "");

  lineChart($("#sim-chart"), (st && st.history) || [], [
    { key: "equity", name: "Valore", cls: "s1" },
    { key: "deposited", name: "Versato", cls: "s2", dash: true },
  ]);
  $("#sim-broker-current").innerHTML = `Broker simulato: <b>${esc(brokerName())}</b> · regime ${esc(sim.settings.regime)} · Italia ${describeFee(sim.settings.fees.it)} · Europa ${describeFee(sim.settings.fees.eu)} · USA ${describeFee(sim.settings.fees.us)}`;

  // ordini
  const done = (st && st.orders) || {};
  const pending = sim.orders.filter((o) => !done[o.id] && !o.cancelled);
  const recent = sim.orders.filter((o) => done[o.id]).slice(-15).reverse();
  $("#sim-pending").innerHTML = pending.length
    ? pending.map((o) => `<div class="list-item"><div class="left"><div><b>${o.side === "buy" ? "Compra" : "Vendi"}</b> ${o.all ? "tutto" : o.quantity ? `${o.quantity} az.` : `${num(o.amount, 0)} €`} di <span class="tk">${esc(o.ticker)}</span></div>
        <div class="muted small">${o.limit ? `limite ${num(o.limit)}` : "al mercato"} · valido fino al ${dateIt(o.valid_until)}</div></div>
        <button class="btn small danger" data-cancel="${esc(o.id)}">Annulla</button></div>`).join("")
    : `<div class="empty">Nessun ordine in attesa</div>`;
  const statusText = { filled: "eseguito", rejected: "rifiutato", expired: "scaduto", cancelled: "annullato" };
  $("#sim-recent").innerHTML = recent.map((o) => {
    const r = done[o.id];
    return `<div class="list-item"><div class="left"><div>${o.side === "buy" ? "Compra" : "Vendi"} <span class="tk">${esc(o.ticker)}</span></div>
      <div class="muted small">${r.reason ? esc(r.reason) : dateIt(r.time) + " " + time(r.time)}</div></div><span class="tag">${statusText[r.status] || r.status}</span></div>`;
  }).join("");

  // posizioni
  const s = sim.settings;
  const posRows = st ? Object.entries(st.positions).map(([tk, p]) => {
    const q = st.prices[tk] || {};
    const value = q.price != null ? p.qty * q.price * q.fx : null;
    const e = q.price != null ? estimate(tk, "sell", p.qty, q.price, q.fx, s) : null;
    const gain = e ? e.total - p.cost_eur : null;
    const tax = gain > 0 ? gain * s.capital_gains_tax_pct / 100 : 0;
    return { ticker: tk, name: p.name, qty: p.qty, avg: p.cost_eur / p.qty, price: q.price, currency: p.currency, day_pct: q.day_pct,
      value, pnl: value != null ? value - p.cost_eur : null, pnl_pct: value != null ? (value / p.cost_eur - 1) * 100 : null, net: e ? gain - tax : null };
  }) : [];
  table($("#sim-positions"), "simpos", [
    { key: "ticker", label: "Titolo", fmt: (r) => `<b>${esc(r.name)}</b><br><span class="tk muted">${esc(r.ticker)}</span>` },
    { key: "qty", label: "Qtà", num: true, fmt: (r) => num(r.qty, 0) },
    { key: "avg", label: "Carico €/az.", num: true, cls: "hide-sm", fmt: (r) => num(r.avg) },
    { key: "price", label: "Prezzo", num: true, fmt: (r) => `${num(r.price)} <span class="muted small">${esc(r.currency)}</span>` },
    { key: "day_pct", label: "Oggi", num: true, cls: "hide-sm", fmt: (r) => `<span class="${cls(r.day_pct)}">${pct(r.day_pct, 2)}</span>` },
    { key: "value", label: "Valore", num: true, fmt: (r) => eur(r.value) },
    { key: "pnl", label: "Risultato", num: true, fmt: (r) => `<b class="${cls(r.pnl)}">${eurS(r.pnl)}</b><br><span class="small ${cls(r.pnl_pct)}">${pct(r.pnl_pct)}</span>` },
    { key: "net", label: "Netto se vendi", num: true, fmt: (r) => `<span class="${cls(r.net)}">${eurS(r.net)}</span>` },
    { key: "sell", label: "", nosort: true, fmt: (r) => `<button class="btn small" data-sell="${esc(r.ticker)}">Vendi</button>` },
  ], posRows, { sortKey: "value", sortDir: -1 });
  if (!posRows.length) $("#sim-positions").innerHTML = `<tbody><tr><td class="empty">Nessuna posizione: compra qualcosa con il modulo qui sopra.</td></tr></tbody>`;

  // movimenti
  const txs = st ? st.transactions.slice().reverse() : [];
  table($("#sim-tx"), "simtx", [
    { key: "time", label: "Quando", fmt: (x) => `${dateIt(x.time)} <span class="muted">${time(x.time)}</span>` },
    { key: "type", label: "Tipo", fmt: (x) => `<span class="tag">${TX_LABEL[x.type] || x.type}</span>` },
    { key: "ticker", label: "Dettaglio", fmt: (x) => txDetail(x) },
    { key: "total", label: "Importo", num: true, fmt: (x) => `<b class="${cls(x.total)}">${eurS(x.total, 2)}</b>` },
    { key: "cash_after", label: "Liquidità", num: true, cls: "hide-sm", fmt: (x) => eur(x.cash_after, 2) },
  ], txs, { sortKey: "time", sortDir: -1, limit: 300 });

  // costi personalizzati
  const f = $("#sim-costs").elements;
  ["it", "eu", "us"].forEach((m) => ["fixed", "pct", "min", "max"].forEach((k) => {
    if (document.activeElement !== f[`${m}_${k}`]) f[`${m}_${k}`].value = s.fees[m][k];
  }));
  f.fx_spread_pct.value = s.fx_spread_pct;
  f.slippage_pct.value = s.slippage_pct;
  f.connectivity_fee.value = s.connectivity_fee || 0;
  f.regime.value = s.regime;
  f.transaction_taxes.checked = !!s.transaction_taxes;
  const dl = $("#sim-tickers");
  if (dl && !dl.childElementCount) dl.innerHTML = ((S.data.universe || {}).items || []).map((i) => `<option value="${esc(i.ticker)}">${esc(i.name)}</option>`).join("");
  renderOrderPreview();
}

function costBreakdown(c) {
  if (!c) return "";
  const parts = [["commissioni", c.commissions], ["tasse transazioni", c.transaction_taxes], ["cambio", c.fx], ["bollo", c.stamp_duty],
    ["plusvalenze", c.capital_gains_tax], ["dividendi", c.dividend_tax]].filter(([, v]) => v > 0.005);
  return parts.map(([k, v]) => `${k} ${num(v, 2)}`).join(" · ") || "nessuno finora";
}

function txDetail(x) {
  if (x.type === "buy") return `${num(x.qty, 0)} <span class="tk">${esc(x.ticker)}</span> a ${num(x.price)} ${esc(x.currency)}<br><span class="muted small">comm. ${num(x.commission)} €${x.transaction_tax ? ` · ${esc(x.tax_name)} ${num(x.transaction_tax)} €` : ""}${x.fx_cost ? ` · cambio ${num(x.fx_cost)} €` : ""}</span>`;
  if (x.type === "sell") return `${num(x.qty, 0)} <span class="tk">${esc(x.ticker)}</span> a ${num(x.price)} ${esc(x.currency)}<br><span class="muted small">${x.gain >= 0 ? "plusvalenza" : "minusvalenza"} ${num(x.gain)} € · comm. ${num(x.commission)} €${x.capital_gains_tax ? ` · tasse ${num(x.capital_gains_tax)} €${x.tax_withheld === false ? " (da dichiarare)" : ""}` : ""}${x.losses_used ? ` · zainetto usato ${num(x.losses_used)} €` : ""}</span>`;
  if (x.type === "dividend") return `<span class="tk">${esc(x.ticker)}</span> ${num(x.per_share, 4)} × ${num(x.qty, 0)}<br><span class="muted small">lordo ${num(x.gross)} € · ritenuta estera ${num(x.withholding)} € · tasse ${num(x.italian_tax)} €</span>`;
  return esc(x.note || "");
}

function bindSimulator() {
  $("#sim-create").addEventListener("submit", createSim);
  $("#sim-deposit").addEventListener("submit", deposit);
  $("#sim-order").addEventListener("submit", placeOrder);
  $("#sim-order").addEventListener("input", renderOrderPreview);
  $("#sim-costs").addEventListener("submit", saveSimCosts);
  $("#sim-reset").addEventListener("click", () => {
    if (!confirm("Ricominciare da zero? Posizioni, movimenti e storico della simulazione verranno azzerati.")) return;
    $("#sim-setup").hidden = false;
    $("#sim-setup").scrollIntoView({ behavior: "smooth" });
  });
  $("#tab-simulator").addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    if (!b) return;
    if (b.dataset.cancel) cancelOrder(b.dataset.cancel);
    if (b.dataset.broker) applyBroker(b.dataset.broker);
    if (b.dataset.sell) {
      const f = $("#sim-order").elements;
      f.ticker.value = b.dataset.sell;
      f.side.value = "sell";
      f.mode.value = "all";
      renderOrderPreview();
      $("#sim-order").scrollIntoView({ behavior: "smooth", block: "center" });
    }
  });
  $("#sim-broker-new").addEventListener("change", renderBrokerTable);
}
