/* Actionzz – laboratorio delle strategie.
 * Legge strategies.json (calcolato in Python sui prezzi reali dell'universo) e applica nel browser
 * costi e tasse del broker scelto. Usa simCommission/brokerSettings/SIM_BASE di simulator.js. */
"use strict";

const ST = { data: null, capital: 10000, broker: "scalable_free", sel: ["etf_hold", "dip_5_10", "momentum", "low_vol"] };
const ST_TAX = 0.26;
const ST_STAMP = 0.002; // imposta di bollo annua sul dossier titoli
const ST_COLORS = ["s1", "s2", "s3", "s4"];
const ST_END_TAX = new Set(["buy_hold", "etf_hold"]); // guadagni tassati solo alla vendita finale
const ST_ETF = new Set(["etf_hold", "halloween", "etf_trend", "turn_of_month"]); // redditi di capitale: niente compensazione

/* ------------------------------------------------------------ descrizioni */

const ST_INFO = {
  etf_hold: {
    fam: "Riferimento",
    how: "Compri una volta un ETF che replica tutti i titoli dell'universo con lo stesso peso e non fai più nulla.",
    lit: "È il termine di paragone di ogni strategia: in media gli investitori attivi, dopo i costi, fanno peggio del mercato (Sharpe, «The Arithmetic of Active Management», 1991).",
    risk: "Subisci per intero i ribassi del mercato. Qui l'ETF è ipotetico: uno reale ha anche un costo annuo (TER).",
  },
  buy_hold: {
    fam: "Riferimento",
    how: "Compri 20 titoli dell'universo in parti uguali e li tieni, senza più toccarli.",
    lit: "È quello che fa la maggior parte dei risparmiatori: pochi titoli, nessuna operazione. Il paniere è quello «tipico» fra 41 estratti a caso (rendimento mediano), per non dipendere dalla fortuna.",
    risk: "Con 20 titoli sei meno diversificato di un ETF: un paniere sfortunato può restare molto indietro (vedi il consiglio sulla diversificazione).",
  },
  rebalance: {
    fam: "Riferimento",
    how: "Gli stessi 20 titoli, riportati a pesi uguali ogni trimestre (vendi un po' di chi è salito, compri chi è sceso).",
    lit: "Il ribilanciamento tiene sotto controllo il rischio; il vantaggio di rendimento è discusso e dipende dai costi.",
    risk: "Circa 80 piccoli ordini l'anno: con poco capitale le commissioni minime pesano, e si pagano tasse sulle plusvalenze realizzate.",
  },
  momentum: {
    fam: "Tendenza",
    how: "Ogni mese tieni i 10 titoli saliti di più negli ultimi 12 mesi (escluso l'ultimo mese): vendi solo chi esce dalla classifica e compri chi entra.",
    lit: "Uno dei risultati più solidi della finanza: i titoli migliori degli ultimi 3–12 mesi continuano a fare meglio per alcuni mesi (Jegadeesh e Titman, 1993; Asness, Moskowitz e Pedersen, 2013 su molti mercati).",
    risk: "Crolli improvvisi quando il mercato inverte (Daniel e Moskowitz, «Momentum crashes», 2016) e molti ordini.",
  },
  high52: {
    fam: "Tendenza",
    how: "Ogni mese tieni i 10 titoli più vicini al loro massimo delle ultime 52 settimane, cambiando solo chi esce dalla classifica.",
    lit: "George e Hwang (2004): la vicinanza al massimo annuale spiega buona parte del momentum; gli investitori «ancorati» al massimo reagiscono in ritardo alle buone notizie.",
    risk: "Come il momentum: soffre nelle inversioni brusche.",
  },
  trend: {
    fam: "Tendenza",
    how: "Sui 20 titoli del paniere, ogni mese tieni solo quelli sopra la loro media dei prezzi degli ultimi 200 giorni; il resto è liquidità.",
    lit: "Le regole di trend following riducono le perdite nei mercati ribassisti lunghi (Faber, «A Quantitative Approach to Tactical Asset Allocation», 2007).",
    risk: "Nei mercati che salgono resti spesso fuori: rendi meno e paghi più ordini. Brilla solo nei grandi ribassi, assenti nel periodo analizzato.",
  },
  etf_trend: {
    fam: "Tendenza",
    how: "Tieni l'ETF solo quando l'indice è sopra la sua media a 200 giorni, altrimenti liquidità (pochi ordini l'anno).",
    lit: "Versione «da indice» della regola di Faber (2007): stessa logica, pochissimi ordini.",
    risk: "Falsi segnali nei mercati laterali; l'effetto utile è limitare i crolli, non aumentare il rendimento.",
  },
  low_vol: {
    fam: "Stabilità",
    how: "Ogni trimestre tieni i 10 titoli meno volatili dell'ultimo anno, cambiando solo chi esce dalla classifica.",
    lit: "L'«anomalia della bassa volatilità»: i titoli meno rischiosi hanno reso quanto o più di quelli rischiosi, con meno oscillazioni (Blitz e van Vliet, 2007; Baker, Bradley e Wurgler, 2011; Frazzini e Pedersen, «Betting Against Beta», 2014).",
    risk: "Resta indietro quando il mercato corre; è concentrata in settori difensivi (utility, telecomunicazioni).",
  },
  reversal: {
    fam: "Ritorno alla media",
    how: "Ogni settimana tieni i 10 titoli scesi di più negli ultimi 5 giorni, cambiando quelli che non sono più tra i peggiori.",
    lit: "Inversione di breve periodo: chi perde di più in una settimana o un mese tende a recuperare un po' (Jegadeesh, 1990; Lehmann, 1990).",
    risk: "Il guadagno lordo esiste, ma con migliaia di ordini l'anno i costi se lo mangiano quasi sempre: è il caso di scuola.",
  },
  dip_5_10: {
    fam: "Ritorno alla media",
    how: "Compri in chiusura un titolo sceso almeno del 5% in un giorno e lo rivendi quando guadagna il 10% (al massimo dopo 6 mesi). Fino a 10 posizioni insieme.",
    lit: "È la strategia di Actionzz: sfrutta l'eccesso di reazione alle cattive notizie (De Bondt e Thaler, 1985, sul lungo periodo; Jegadeesh, 1990, sul breve) su titoli stabili.",
    risk: "Non c'è stop: se il calo era giustificato (utili, scandali) resti bloccato a lungo. Sensibile alla distorsione di sopravvivenza.",
  },
  dip_7_5_s10: {
    fam: "Ritorno alla media",
    how: "Compri dopo un calo del 7% e rivendi a +5%, con uno stop a −10% e al massimo 3 mesi.",
    lit: "Variante «rapida» con stop: più operazioni, obiettivo vicino. Mostra come obiettivi piccoli rendano i costi decisivi.",
    risk: "Gli stop in chiusura vendono spesso proprio sul minimo; tanti ordini e tasse.",
  },
  rsi2: {
    fam: "Ritorno alla media",
    how: "Compri quando l'RSI a 2 giorni scende sotto 10 in un titolo in tendenza positiva (sopra la media a 200 giorni), vendi quando torna sopra la media a 5 giorni.",
    lit: "Regola molto diffusa tra i trader (Connors e Alvarez, «Short Term Trading Strategies That Work», 2008): è letteratura di pratica, non accademica.",
    risk: "Operazioni brevi con guadagni piccoli: i costi pesano molto, e nel periodo analizzato ha reso poco.",
  },
  halloween: {
    fam: "Calendario",
    how: "Tieni l'ETF da novembre ad aprile e stai in liquidità da maggio a ottobre («Sell in May and go away»).",
    lit: "Bouman e Jacobsen (2002) trovano l'effetto in 36 mercati su 37; resta uno dei fenomeni di calendario più studiati.",
    risk: "Stai fuori metà anno: se l'estate sale, perdi. L'effetto varia molto da un anno all'altro.",
  },
  turn_of_month: {
    fam: "Calendario",
    how: "Tieni l'ETF solo dall'ultimo giorno del mese ai primi 3 del mese successivo.",
    lit: "Gran parte dei rendimenti azionari si è concentrata a cavallo dei mesi (Ariel, 1987; McConnell e Xu, 2008), forse per i flussi di stipendi e fondi pensione.",
    risk: "Sei investito solo pochi giorni al mese: basta che l'effetto si attenui per rendere meno della liquidità.",
  },
};

/* ------------------------------------------------------------ caricamento */

async function loadStrategies() {
  await loadBrokers();
  if (ST.data) return;
  let d = null;
  try {
    d = await fetchFile("strategies.json", "data");
  } catch (_) { /* uso la copia del sito */ }
  if (!d) {
    try {
      const res = await fetch("strategies.json", { cache: "no-store" });
      d = res.ok ? await res.json() : null;
    } catch (_) { /* nessun dato */ }
  }
  ST.data = d;
  try {
    Object.assign(ST, JSON.parse(localStorage.getItem("actionzz.strategie") || "{}"));
  } catch (_) { /* ignora */ }
}

function stSave() {
  try {
    localStorage.setItem("actionzz.strategie", JSON.stringify({ capital: ST.capital, broker: ST.broker, sel: ST.sel }));
  } catch (_) { /* ignora */ }
}

function stBroker() {
  const list = (S.brokers && S.brokers.brokers) || [];
  const b = list.find((x) => x.id === ST.broker) || list[0];
  return b ? { b, s: brokerSettings(b, SIM_BASE) } : null;
}

const eur0 = (x) => (x == null || !isFinite(x) ? "—" : `${x < 0 ? "−" : ""}${num(Math.abs(x), 0)} €`);
const eurS0 = (x) => (x == null || !isFinite(x) ? "—" : `${x < 0 ? "−" : "+"}${num(Math.abs(x), 0)} €`);

/* ------------------------------------------- calcolatrice compro/rivendo */

function perTradeCosts(amount, dipInfo, s) {
  const comm = (m) => simCommission(amount, s, m);
  const oneSide = dipInfo.it_share * comm("it") + (1 - dipInfo.it_share) * comm("eu");
  const commission = oneSide * 2;
  const ftt = s.transaction_taxes ? amount * dipInfo.ftt_pct / 100 : 0;
  const fx = amount * dipInfo.noneur * s.fx_spread_pct / 100 * 2;
  const slip = amount * s.slippage_pct / 100 * 2;
  return { commission, ftt, fx, slip, total: commission + ftt + fx + slip };
}

function sampleQuantile(q, u) {
  const pos = u * (q.length - 1);
  const i = Math.floor(pos);
  return i >= q.length - 1 ? q[q.length - 1] : q[i] + (q[i + 1] - q[i]) * (pos - i);
}

function monteCarlo(combo, amount, n, costs, plan = 0, sims = 3000) {
  const totals = new Float64Array(sims);
  let losses = 0;
  for (let k = 0; k < sims; k++) {
    let sum = -plan;
    for (let j = 0; j < n; j++) sum += amount * sampleQuantile(combo.q, Math.random()) / 100 - costs.total;
    const tax = sum > 0 ? sum * ST_TAX : 0;
    totals[k] = sum - tax;
    if (totals[k] < 0) losses++;
  }
  totals.sort();
  const pick = (p) => totals[Math.min(sims - 1, Math.floor(p * sims))];
  let mean = 0;
  for (const v of totals) mean += v;
  return { p5: pick(0.05), p25: pick(0.25), p50: pick(0.5), p75: pick(0.75), p95: pick(0.95), mean: mean / sims, loss: losses / sims * 100, all: totals };
}

function comboFor(dip, target, stop, hold) {
  return ST.data.dip.combos.find((c) => c.dip === dip && c.target === target && c.stop === stop && c.hold === hold);
}

function renderCalculator() {
  const f = $("#st-calc").elements;
  const dip = +f.dip.value, target = +f.target.value, stop = +f.stop.value, hold = +f.hold.value;
  const amount = Math.max(50, parseFloat(f.amount.value) || 1000);
  const n = Math.max(1, Math.min(1000, parseInt(f.n.value, 10) || 20));
  const years = Math.max(0.25, parseFloat(f.years.value) || 1);
  const br = stBroker();
  const out = $("#st-calc-out");
  const combo = comboFor(dip, target, stop, hold);
  if (!br || !combo) {
    out.innerHTML = `<p class="muted">Combinazione non disponibile.</p>`;
    return;
  }
  const info = ST.data.dip.per_dip[dip];
  const c = perTradeCosts(amount, info, br.s);
  const costPct = c.total / amount * 100;
  // scenario "ideale": ogni operazione chiude all'obiettivo
  const plan = (br.s.monthly_fee || 0) * 12 * years; // canone per tutto il periodo
  const idealGross = n * (amount * target / 100 - c.total) - plan;
  const ideal = idealGross - Math.max(0, idealGross) * ST_TAX;
  const mc = monteCarlo(combo, amount, n, c, plan);
  const expectedTrade = amount * combo.mean / 100 - c.total;
  const concurrent = n * combo.days / (252 * years);
  const capital = Math.max(1, Math.ceil(concurrent)) * amount;
  const breakeven = costPct;
  const feasible = info.per_year * years;

  out.innerHTML = `
    <div class="kpis">
      ${kpi("Se ogni operazione andasse a segno", eurS0(ideal), `${n} × +${target}% su ${eur0(amount)}, al netto di costi e tasse`, "pos")}
      ${kpi("Risultato tipico (storico)", eurS0(mc.p50), `metà dei casi fa meglio, metà peggio`, cls(mc.p50))}
      ${kpi("Forchetta realistica", `${eurS0(mc.p5)} … ${eurS0(mc.p95)}`, "9 casi su 10 cadono qui dentro")}
      ${kpi("Probabilità di chiudere in perdita", `${num(mc.loss, 0)}%`, `dopo ${n} operazioni, costi e tasse compresi`, mc.loss > 30 ? "neg" : "")}
    </div>
    <div class="grid2 tight">
      <div>
        <h4>Com'è andata davvero, operazione per operazione</h4>
        <div class="bars3" role="img" aria-label="Esiti delle operazioni">
          <span class="b-win" style="flex:${combo.win}">${num(combo.win, 0)}%</span>
          <span class="b-time" style="flex:${combo.timeout}">${combo.timeout >= 8 ? num(combo.timeout, 0) + "%" : ""}</span>
          <span class="b-stop" style="flex:${combo.stopped}">${combo.stopped >= 8 ? num(combo.stopped, 0) + "%" : ""}</span>
        </div>
        <div class="legend small"><span><i class="b-win"></i>obiettivo +${target}% raggiunto</span><span><i class="b-time"></i>venduto a tempo (${hold} sedute)</span>${stop ? `<span><i class="b-stop"></i>stop −${stop}%</span>` : ""}</div>
        <ul class="facts">
          <li>${num(combo.n, 0)} operazioni simulate in ${num(ST.data.dip.years, 1)} anni sui ${ST.data.tickers} titoli dell'universo.</li>
          <li>Rendimento medio lordo per operazione: <b class="${cls(combo.mean)}">${pct(combo.mean, 2)}</b> in ${num(combo.days, 0)} sedute; nello stesso periodo il mercato ha fatto ${pct(combo.market, 2)}.</li>
          <li>Guadagno atteso netto per operazione (prima delle tasse): <b class="${cls(expectedTrade)}">${eurS0(expectedTrade)}</b>.</li>
          <li>Un quarto delle operazioni ha fatto peggio di <b class="neg">${pct(combo.q[5], 1)}</b>; la peggiore ${pct(combo.q[0], 1)}.</li>
        </ul>
      </div>
      <div>
        <h4>Costi di un giro completo (acquisto + vendita) con ${esc(br.b.name)}</h4>
        <div class="est">
          <div><span>Commissioni (2 ordini)</span><b>${num(c.commission)} €</b></div>
          ${c.ftt ? `<div><span>Tasse sulle transazioni (media dei titoli segnalati)</span><b>${num(c.ftt)} €</b></div>` : ""}
          ${c.fx ? `<div><span>Cambio valuta (${num(info.noneur * 100, 0)}% dei titoli non in euro)</span><b>${num(c.fx)} €</b></div>` : ""}
          <div><span>Scostamento dal prezzo</span><b>${num(c.slip)} €</b></div>
          <div class="tot"><span>Totale: ${num(costPct, 2)}% dell'importo</span><b>${num(c.total)} €</b></div>
        </div>
        ${plan ? `<div class="est"><div><span>Canone ${esc(br.b.name)} per ${num(years, 1)} ${years === 1 ? "anno" : "anni"}</span><b>${num(plan)} €</b></div></div>` : ""}
        <ul class="facts">
          <li>Il titolo deve salire di almeno <b>${num(breakeven, 2)}%</b> solo per ripagare i costi; poi il 26% dei guadagni va in tasse.</li>
          <li>Occasioni storiche con un calo del ${dip}%: circa <b>${num(info.per_year, 0)} l'anno</b> (tra tutti i titoli): ${n} operazioni in ${num(years, 1)} ${years === 1 ? "anno" : "anni"} ${n <= feasible ? "sono realistiche" : "sono più di quelle disponibili"}.</li>
          <li>Capitale che serve: circa <b>${eur0(capital)}</b> (in media ${num(concurrent, 1)} posizioni aperte insieme).</li>
        </ul>
      </div>
    </div>
    <h4>Distribuzione del risultato dopo ${n} operazioni</h4>
    <div id="st-hist" class="chart"></div>
    <p class="muted small">Simulazione Monte Carlo: ${num(3000, 0)} sequenze di ${n} operazioni pescate a caso dagli esiti storici reali, con i costi di ${esc(br.b.name)} e il 26% sui guadagni netti (le perdite compensano i guadagni, come nello zainetto fiscale).</p>`;
  histogram($("#st-hist"), mc.all);
  renderHeatmap(dip, hold, amount, br.s, info, target, stop);
}

function histogram(el, values) {
  const W = Math.max(el.clientWidth, 280), H = 170, m = { t: 8, r: 8, b: 26, l: 8 };
  const lo = values[Math.floor(values.length * 0.005)], hi = values[Math.floor(values.length * 0.995)];
  const bins = 30, step = (hi - lo) / bins || 1;
  const counts = new Array(bins).fill(0);
  for (const v of values) counts[Math.max(0, Math.min(bins - 1, Math.floor((v - lo) / step)))]++;
  const max = Math.max(...counts);
  const bw = (W - m.l - m.r) / bins;
  let svg = "";
  counts.forEach((cnt, i) => {
    const x = m.l + i * bw, h = cnt / max * (H - m.t - m.b);
    const mid = lo + (i + 0.5) * step;
    svg += `<rect class="${mid < 0 ? "bar-neg" : "bar-pos"}" x="${x + 1}" y="${H - m.b - h}" width="${Math.max(bw - 2, 1)}" height="${h}" rx="2"><title>${eurS0(lo + i * step)} … ${eurS0(lo + (i + 1) * step)}: ${num(cnt / values.length * 100, 1)}% dei casi</title></rect>`;
  });
  if (lo < 0 && hi > 0) {
    const zx = m.l + (-lo / (hi - lo)) * (W - m.l - m.r);
    svg += `<line class="baseline" x1="${zx}" x2="${zx}" y1="${m.t}" y2="${H - m.b}"/><text x="${zx}" y="${H - 8}" text-anchor="middle">0 €</text>`;
  }
  svg += `<text x="${m.l}" y="${H - 8}">${eurS0(lo)}</text><text x="${W - m.r}" y="${H - 8}" text-anchor="end">${eurS0(hi)}</text>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Distribuzione del risultato">${svg}</svg>`;
}

function renderHeatmap(dip, hold, amount, s, info, curT, curS) {
  const g = ST.data.dip;
  const c = perTradeCosts(amount, info, s);
  const cells = [];
  let maxAbs = 0.01;
  g.targets.forEach((t) => g.stops.forEach((st) => {
    const combo = comboFor(dip, t, st, hold);
    const v = combo ? combo.mean - c.total / amount * 100 : null;
    if (v != null) maxAbs = Math.max(maxAbs, Math.abs(v));
    cells.push({ t, st, v, combo });
  }));
  const color = (v) => {
    if (v == null) return "transparent";
    const a = Math.min(0.85, Math.abs(v) / maxAbs * 0.85);
    return v < 0 ? `rgba(208,59,59,${a})` : `rgba(42,120,214,${a})`;
  };
  const dec = document.body.classList.contains("mobile") ? 1 : 2;
  let html = `<table class="heat"><thead><tr><th>Obiettivo · stop</th>${g.stops.map((st) => `<th>${st ? "−" + st + "%" : "nessuno"}</th>`).join("")}</tr></thead><tbody>`;
  g.targets.forEach((t) => {
    html += `<tr><th>+${t}%</th>`;
    g.stops.forEach((st) => {
      const cell = cells.find((x) => x.t === t && x.st === st);
      const sel = t === curT && st === curS ? " sel" : "";
      html += cell.v == null ? `<td>—</td>` : `<td class="pick${sel}" style="background:${color(cell.v)}" data-t="${t}" data-s="${st}" title="Obiettivo raggiunto nel ${num(cell.combo.win, 0)}% dei casi">${pct(cell.v, dec)}</td>`;
    });
    html += "</tr>";
  });
  $("#st-heat").innerHTML = html + "</tbody></table>";
  $("#st-heat-note").textContent = `Rendimento medio netto dei costi per operazione, comprando dopo un calo del ${dip}% e vendendo entro ${hold} sedute. Blu = in guadagno, rosso = in perdita. Tocca una casella per provarla.`;
}

/* ------------------------------------------------------- confronto strategie */

function netStrategy(id, st, capital, br) {
  const s = br.s;
  const etf = ST_ETF.has(id);
  const endTax = ST_END_TAX.has(id);
  let eq = capital, costs = 0, taxes = 0, carry = [];
  const yearEnds = [];
  let grossEq = 1;
  for (const y of st.yearly) {
    const start = eq;
    const r = y.ret / 100;
    const avg = start * (1 + r / 2);
    let comm = 0;
    if (y.orders) {
      const amt = (y.buy + y.sell) * avg / y.orders;
      const market = etf ? "it" : "eu";
      comm = y.orders * (y.it_share * simCommission(amt, s, "it") + (1 - y.it_share) * simCommission(amt, s, market));
    }
    const ftt = s.transaction_taxes ? y.ftt * avg : 0;
    const fx = y.noneur * avg * s.fx_spread_pct / 100;
    const slip = (y.buy + y.sell) * avg * s.slippage_pct / 100;
    const stamp = avg * y.invested * ST_STAMP * (y.days / 252);
    const plan = (s.monthly_fee || 0) * 12 * (y.days / 252); // canone dell'abbonamento
    const c = comm + ftt + fx + slip + stamp + plan;
    let pnl = start * r - c;
    let tax = 0;
    if (!endTax) {
      if (pnl > 0) {
        let taxable = pnl;
        if (!etf) {
          carry = carry.filter((l) => l.year >= y.year - 4);
          for (const l of carry) {
            const use = Math.min(l.amount, taxable);
            l.amount -= use;
            taxable -= use;
          }
        }
        tax = taxable * ST_TAX;
      } else if (!etf) {
        carry.push({ year: y.year, amount: -pnl });
      }
    }
    eq = Math.max(0, start + pnl - tax); // i costi possono azzerare il capitale
    costs += c;
    taxes += tax;
    grossEq *= 1 + r;
    yearEnds.push({ year: y.year, net: eq / capital, gross: grossEq });
  }
  if (endTax && eq > capital) {
    // alla fine si vende tutto: tasse sulla plusvalenza e ultima commissione
    const tax = (eq - capital) * ST_TAX;
    eq -= tax;
    taxes += tax;
    yearEnds[yearEnds.length - 1].net = eq / capital;
  }
  const years = st.yearly.reduce((a, y) => a + y.days, 0) / 252;
  const nOrders = st.yearly.reduce((a, y) => a + y.orders, 0);
  const order = nOrders ? st.yearly.reduce((a, y) => a + y.buy + y.sell, 0) * capital / nOrders : null; // importo medio di un ordine
  const cagr = eq > 0 ? (Math.pow(eq / capital, 1 / years) - 1) * 100 : -100;
  // curva netta: la curva lorda riscalata in modo da coincidere con il netto a ogni fine anno
  const ratio = {};
  let prevRatio = 1;
  yearEnds.forEach((ye) => (ratio[ye.year] = { from: prevRatio, to: (prevRatio = ye.net / ye.gross) }));
  const curve = st.curve.d.map((d, i) => {
    const y = +d.slice(0, 4);
    const rr = ratio[y] || { from: 1, to: 1 };
    const frac = (new Date(d) - new Date(`${y}-01-01`)) / (365 * 864e5);
    return { day: d, v: st.curve.v[i] * (rr.from + (rr.to - rr.from) * Math.min(1, frac)) * capital };
  });
  return { final: eq, cagr, costs, taxes, curve, grossCagr: st.cagr, order, wiped: eq <= 0 };
}

function renderComparison() {
  const br = stBroker();
  if (!br) return;
  const cap = ST.capital;
  const rows = Object.entries(ST.data.strategies).map(([id, st]) => {
    const n = netStrategy(id, st, cap, br);
    return { id, name: st.name, fam: (ST_INFO[id] || {}).fam || "", gross: st.cagr, net: n.cagr, order: n.order, wiped: n.wiped, final: n.final, costs: n.costs, taxes: n.taxes, dd: st.max_dd, vol: st.vol, orders: st.orders_per_year, net_obj: n };
  });
  const ref = rows.find((r) => r.id === "etf_hold");
  table($("#st-table"), "strategie", [
    { key: "sel", label: "", nosort: true, fmt: (r) => `<input type="checkbox" data-st="${r.id}" ${ST.sel.includes(r.id) ? "checked" : ""} aria-label="Mostra nel grafico">` },
    { key: "name", label: "Strategia", fmt: (r) => `<b>${esc(r.name)}</b><br><span class="muted small">${esc(r.fam)}</span>` },
    { key: "net", label: "Rendimento netto/anno", num: true, fmt: (r) => `${r.wiped ? `<b class="neg">capitale azzerato dai costi</b>` : `<b class="${cls(r.net)}">${pct(r.net, 1)}</b>`}<br><span class="muted small">lordo ${pct(r.gross, 1)}</span>` },
    { key: "final", label: `Valore di ${eur0(cap)}`, num: true, fmt: (r) => `${eur0(r.final)}<br><span class="small ${cls(r.final - ref.final)}">${eurS0(r.final - ref.final)} vs ETF</span>` },
    { key: "costs", label: "Costi", num: true, fmt: (r) => eur0(r.costs) },
    { key: "taxes", label: "Tasse", num: true, cls: "hide-sm", fmt: (r) => eur0(r.taxes) },
    { key: "dd", label: "Calo massimo", num: true, fmt: (r) => `<span class="neg">${pct(r.dd, 1)}</span>` },
    { key: "orders", label: "Ordini/anno", num: true, fmt: (r) => `${num(r.orders, 0)}${r.order ? `<br><span class="muted small">da ~${eur0(r.order)}</span>` : ""}` },
  ], rows, { sortKey: "net", sortDir: -1 });
  const selected = rows.filter((r) => ST.sel.includes(r.id)).slice(0, 4);
  stLineChart($("#st-chart"), selected.map((r, i) => ({ name: r.name, cls: ST_COLORS[i], pts: r.net_obj.curve })), cap);
  $("#st-legend").innerHTML = selected.map((r, i) => `<span><i class="sw ${ST_COLORS[i]}"></i>${esc(r.name)}</span>`).join("");
}

function stLineChart(el, series, capital) {
  if (!el.clientWidth || !series.length) {
    if (!series.length) el.innerHTML = `<div class="empty">Scegli fino a 4 strategie nella tabella.</div>`;
    return;
  }
  const W = el.clientWidth, H = 260, m = { t: 10, r: 12, b: 26, l: 64 };
  const all = series.flatMap((s) => s.pts.map((p) => p.v));
  let lo = Math.min(...all, capital), hi = Math.max(...all);
  const step = niceStep((hi - lo) / 4);
  lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step;
  const n = series[0].pts.length;
  const x = (i) => m.l + (i / (n - 1)) * (W - m.l - m.r);
  const y = (v) => m.t + ((hi - v) / (hi - lo)) * (H - m.t - m.b);
  let svg = "";
  for (let v = lo; v <= hi + 1e-9; v += step) svg += `<line class="gridline" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${m.l - 6}" y="${y(v)}" dy="0.32em" text-anchor="end">${num(v, 0)} €</text>`;
  svg += `<line class="baseline" x1="${m.l}" x2="${W - m.r}" y1="${y(capital)}" y2="${y(capital)}" stroke-dasharray="3 3"/>`;
  const pts0 = series[0].pts;
  [0, Math.floor(n / 2), n - 1].forEach((i) => (svg += `<text x="${x(i)}" y="${H - 8}" text-anchor="middle">${dateIt(pts0[i].day).slice(3)}</text>`));
  series.forEach((s) => {
    svg += `<path d="${s.pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join("")}" fill="none" class="${s.cls}" stroke-width="2" stroke-linejoin="round"/>`;
  });
  svg += `<line id="st-cross" class="baseline" y1="${m.t}" y2="${H - m.b}" visibility="hidden"/><rect class="hit" x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}"/>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Valore netto delle strategie nel tempo">${svg}</svg>`;
  const hit = el.querySelector(".hit"), cross = el.querySelector("#st-cross");
  const move = (ev) => {
    const r = hit.getBoundingClientRect();
    const i = Math.max(0, Math.min(n - 1, Math.round((ev.clientX - r.left) / r.width * (n - 1))));
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
    showTip(`<div>${dateIt(pts0[i].day)}</div>` + series.map((s) => `<div><i class="sw ${s.cls}"></i> ${esc(s.name)} <b>${eur0(s.pts[i].v)}</b></div>`).join(""), ev);
  };
  hit.addEventListener("pointermove", move);
  hit.addEventListener("pointerdown", move);
  hit.addEventListener("pointerleave", () => { hideTip(); cross.setAttribute("visibility", "hidden"); });
}

function renderStrategyCards() {
  const fams = {};
  Object.entries(ST.data.strategies).forEach(([id, st]) => {
    const info = ST_INFO[id];
    if (!info) return;
    (fams[info.fam] ||= []).push({ id, st, info });
  });
  $("#st-cards").innerHTML = Object.entries(fams).map(([fam, list]) => `<h3 class="fam">${esc(fam)}</h3>` + list.map(({ id, st, info }) => `
    <details class="st-card">
      <summary><b>${esc(st.name)}</b><span class="muted small">lordo ${pct(st.cagr, 1)}/anno · calo massimo ${pct(st.max_dd, 1)} · ${num(st.orders_per_year, 0)} ordini/anno</span></summary>
      <p><b>Come funziona.</b> ${esc(info.how)}</p>
      <p><b>Cosa dice la letteratura.</b> ${esc(info.lit)}</p>
      <p><b>Perché può non funzionare.</b> ${esc(info.risk)}</p>
    </details>`).join("")).join("");
}

/* ------------------------------------------------ Scalable FREE o PRIME+? */

function stPlan(id) {
  const b = ((S.brokers && S.brokers.brokers) || []).find((x) => x.id === id);
  return b ? { b, s: brokerSettings(b, SIM_BASE) } : null;
}

function renderPlans() {
  const free = stPlan("scalable_free"), prime = stPlan("scalable_prime");
  const box = $("#st-plans");
  if (!free || !prime) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const f = $("#st-plans-form").elements;
  const perMonth = +f.orders.value, amount = +f.amount.value;
  $("#st-plans-orders").textContent = perMonth;
  $("#st-plans-amount").textContent = eur0(amount);
  const orders = perMonth * 12;
  const fee = prime.s.monthly_fee * 12;
  const costFree = orders * simCommission(amount, free.s, "eu");
  const costPrime = fee + orders * simCommission(amount, prime.s, "eu");
  const saving = costFree - costPrime;
  const perOrder = simCommission(amount, free.s, "eu") - simCommission(amount, prime.s, "eu");
  const breakEven = perOrder > 0 ? Math.ceil(fee / perOrder) : null;
  const max = Math.max(costFree, costPrime, 1);
  $("#st-plans-out").innerHTML = `
    <div class="plan-bars">
      <div><span>FREE</span><div class="pb"><i style="width:${costFree / max * 100}%"></i></div><b>${eur0(costFree)}/anno</b></div>
      <div><span>PRIME+</span><div class="pb"><i class="p2" style="width:${costPrime / max * 100}%"></i></div><b>${eur0(costPrime)}/anno</b></div>
    </div>
    <p>${amount < prime.b.fees.eu.free_from
      ? `Con ordini sotto i ${num(prime.b.fees.eu.free_from, 0)} € PRIME+ costa 0,99 € a ordine come FREE, più il canone: <b class="neg">non conviene mai</b>.`
      : saving > 0
        ? `Con ${perMonth} ordini al mese PRIME+ ti fa risparmiare <b class="pos">${eur0(saving)} l'anno</b>.`
        : `Con ${perMonth} ordini al mese PRIME+ ti costa <b class="neg">${eur0(-saving)} in più l'anno</b>.`}
      ${breakEven ? ` Conviene da <b>${breakEven} ordini l'anno</b> (circa ${num(breakEven / 12, 0)} al mese) da almeno ${num(prime.b.fees.eu.free_from, 0)} €.` : ""}</p>`;

  const cap = ST.capital;
  const rows = Object.entries(ST.data.strategies).map(([id, st]) => {
    const a = netStrategy(id, st, cap, free), b = netStrategy(id, st, cap, prime);
    return { id, name: st.name, orders: st.orders_per_year, order: a.order, free: a, prime: b, diff: b.final - a.final };
  });
  table($("#st-plans-table"), "piani", [
    { key: "name", label: "Strategia", fmt: (r) => `<b>${esc(r.name)}</b>` },
    { key: "orders", label: "Ordini/anno", num: true, fmt: (r) => `${num(r.orders, 0)}${r.order ? `<br><span class="muted small">da ~${eur0(r.order)}</span>` : ""}` },
    { key: "fnet", label: "Netto con FREE", num: true, sort: (r) => r.free.cagr, fmt: (r) => (r.free.wiped ? `<span class="neg">azzerato</span>` : `<span class="${cls(r.free.cagr)}">${pct(r.free.cagr, 1)}</span>`) },
    { key: "pnet", label: "Netto con PRIME+", num: true, sort: (r) => r.prime.cagr, fmt: (r) => (r.prime.wiped ? `<span class="neg">azzerato</span>` : `<span class="${cls(r.prime.cagr)}">${pct(r.prime.cagr, 1)}</span>`) },
    { key: "diff", label: `Differenza su ${eur0(cap)}`, num: true, fmt: (r) => `<b class="${cls(r.diff)}">${eurS0(r.diff)}</b><br><span class="small ${r.diff > 0 ? "pos" : "muted"}">${r.diff > 0 ? "conviene PRIME+" : "conviene FREE"}</span>` },
  ], rows, { sortKey: "diff", sortDir: -1 });
  const wins = rows.filter((r) => r.diff > 0).length;
  $("#st-plans-note").innerHTML = `Con ${eur0(cap)} di capitale PRIME+ conviene in <b>${wins} strategie su ${rows.length}</b>: quelle con molti ordini da almeno 250 €. Chi compra e tiene o usa un ETF paga ${eur0(fee)} l'anno di canone per niente. Gli interessi del 2,60% sulla liquidità e il PAC gratuito sono uguali nei due piani, quindi non cambiano la scelta. Le tariffe valgono sulla sede European Investor Exchange; su gettex e Xetra si pagano 1,99 € a ordine con entrambi i piani. Tariffe da <a href="https://it.scalable.capital/costi-broker" target="_blank" rel="noopener">it.scalable.capital/costi-broker</a>.`;
}

/* ------------------------------------------------------ consigli interattivi */

function renderTips() {
  const br = stBroker();
  const lab = ST.data.lab;
  const f = $("#st-tips").elements;
  // 1. i costi
  const trades = +f.trades.value, size = +f.size.value, cap = ST.capital;
  const perOrder = br ? simCommission(size, br.s, "eu") : 1;
  const yearly = trades * 12 * 2 * perOrder + trades * 12 * size * 0.0025;
  $("#tip-costs").innerHTML = `${trades} operazioni al mese da ${eur0(size)} costano circa <b>${eur0(yearly)} l'anno</b>, cioè il <b class="${yearly / cap > 0.03 ? "neg" : ""}">${num(yearly / cap * 100, 1)}%</b> di un capitale di ${eur0(cap)} (commissioni ${br ? esc(br.b.name) : ""} + tasse sulle transazioni medie). Quel rendimento va guadagnato ogni anno solo per restare in pari.`;
  // 2. perdite e recupero
  const loss = +f.loss.value;
  $("#tip-loss").innerHTML = `Una perdita del <b class="neg">${loss}%</b> richiede un guadagno del <b>${num(100 / (1 - loss / 100) - 100, 0)}%</b> per tornare in pari.`;
  // 3. i giorni migliori
  const k = +f.best.value;
  const r = lab.index.r.slice();
  const years = r.length / 252;
  const growth = (arr) => arr.reduce((a, x) => a * (1 + x), 1);
  const full = Math.pow(growth(r), 1 / years) - 1;
  const sortedIdx = r.map((v, i) => [v, i]).sort((a, b) => b[0] - a[0]).slice(0, k).map((x) => x[1]);
  const skip = new Set(sortedIdx);
  const missed = Math.pow(growth(r.filter((_, i) => !skip.has(i))), 1 / years) - 1;
  const bestDates = sortedIdx.slice(0, 3).map((i) => dateIt(lab.index.d[i]));
  $("#tip-best").innerHTML = `Restando sempre investito: <b class="pos">${pct(full * 100, 1)}</b> l'anno. Perdendo i ${k} giorni migliori su ${num(r.length, 0)}: <b class="${cls(missed)}">${pct(missed * 100, 1)}</b> l'anno. ${k ? `I migliori sono arrivati spesso a ridosso dei peggiori (es. ${bestDates.join(", ")}): chi esce per paura di solito se li perde.` : ""}`;
  // 4. PAC o tutto subito
  const months = +f.months.value;
  const win = 21 * months;
  let lumpWins = 0, tot = 0;
  for (let s = 0; s + win + 21 < r.length; s += 5) {
    // tutto subito all'inizio vs rate mensili uguali; entrambi valutati alla fine del periodo di rate
    const end = s + win;
    let lump = 1, pac = 0;
    for (let i = s + 1; i <= end; i++) lump *= 1 + r[i];
    for (let mth = 0; mth < months; mth++) {
      let v = 1 / months;
      for (let i = s + mth * 21 + 1; i <= end; i++) v *= 1 + r[i];
      pac += v;
    }
    tot++;
    if (lump > pac) lumpWins++;
  }
  $("#tip-pac").innerHTML = tot ? `Su ${tot} periodi storici, investire tutto subito ha battuto il PAC in ${months} rate nel <b>${num(lumpWins / tot * 100, 0)}%</b> dei casi. Il PAC però riduce il rimpianto se il mercato scende subito dopo: è una scelta anche psicologica.` : "";
  // 5. diversificazione
  const d = lab.diversification;
  const kk = +f.k.value;
  const row = d.reduce((a, x) => (Math.abs(x.k - kk) < Math.abs(a.k - kk) ? x : a), d[0]);
  $("#tip-div").innerHTML = `Con <b>${row.k}</b> ${row.k === 1 ? "titolo" : "titoli"} a caso la volatilità annua è in media <b>${num(row.vol, 1)}%</b> (da ${num(row.p10, 1)}% a ${num(row.p90, 1)}%), contro ${num(d[0].vol, 1)}% di un titolo solo e ${num(d[d.length - 1].vol, 1)}% con ${d[d.length - 1].k}. Solo <b>${lab.stocks.beat_index} titoli su ${lab.stocks.n}</b> hanno battuto l'indice equiponderato e ${lab.stocks.negative} hanno perso: scegliere i pochi vincenti in anticipo è difficile.`;
  // 6. effetto disposizione (dal simulatore)
  const tx = (S.simState && S.simState.transactions || []).filter((t) => t.type === "sell");
  const gains = tx.filter((t) => t.gain > 0).length;
  $("#tip-disp").innerHTML = tx.length
    ? `Nel tuo simulatore hai venduto <b>${gains}</b> volte in guadagno e <b>${tx.length - gains}</b> in perdita. Se vendi quasi sempre i vincenti e tieni i perdenti, stai probabilmente cadendo nell'effetto disposizione.`
    : "Quando userai il simulatore, qui vedrai quante volte hai venduto in guadagno e quante in perdita.";
  // 7. troppe prove
  const tries = +f.tries.value;
  $("#tip-tries").innerHTML = `Provando <b>${tries}</b> combinazioni senza alcun vero vantaggio, circa <b>${num(tries * 0.05, 0)}</b> sembreranno «vincenti» per puro caso (soglia statistica del 5%). La griglia di questa pagina ne ha ${ST.data.dip.combos.length}: la migliore del passato non è per forza la migliore del futuro.`;
  // grafico diversificazione
  barChart($("#tip-div-chart"), d, {
    value: (x) => x.vol, signed: false, height: 150, format: (v) => `${num(v, 0)}%`,
    xLabel: (x) => String(x.k), tooltip: (x) => `<div>${x.k} titoli</div><div>volatilità media <b>${num(x.vol, 1)}%</b></div>`,
  });
}

/* ------------------------------------------------------------------ render */

function renderStrategies() {
  const root = $("#tab-strategies");
  if (!root || root.hidden) return;
  if (!ST.data) {
    $("#st-body").hidden = true;
    $("#st-empty").hidden = false;
    return;
  }
  $("#st-empty").hidden = true;
  $("#st-body").hidden = false;
  const sel = $("#st-broker");
  const list = (S.brokers && S.brokers.brokers) || [];
  if (!sel.childElementCount && list.length) {
    sel.innerHTML = list.map((b) => `<option value="${esc(b.id)}">${esc(b.name)}</option>`).join("");
  }
  sel.value = ST.broker;
  if (document.activeElement !== $("#st-capital")) $("#st-capital").value = ST.capital;
  const p = ST.data.period;
  const first = Object.values(ST.data.strategies)[0];
  $("#st-period").innerHTML = `Prezzi reali di ${ST.data.tickers} titoli dal ${dateIt(p.start)} al ${dateIt(p.end)} (strategie dal ${dateIt(first.curve.d[0])}, dopo un anno per calcolare gli indicatori). <b>Attenzione:</b> sono i titoli stabili di oggi, quindi mancano quelli falliti o crollati (distorsione di sopravvivenza) e in questo periodo il mercato è salito molto: i risultati sono più belli di quanto sarà il futuro.`;
  const f = $("#st-calc").elements;
  const g = ST.data.dip;
  const opts = (arr, fmt, cur) => arr.map((v) => `<option value="${v}"${v === cur ? " selected" : ""}>${fmt(v)}</option>`).join("");
  if (!f.dip.childElementCount) {
    f.dip.innerHTML = opts(g.dips, (v) => `−${v}% in un giorno`, 5);
    f.target.innerHTML = opts(g.targets, (v) => `+${v}%`, 10);
    f.stop.innerHTML = opts(g.stops, (v) => (v ? `−${v}%` : "nessuno"), 0);
    f.hold.innerHTML = opts(g.holds, (v) => ({ 20: "1 mese", 60: "3 mesi", 120: "6 mesi" })[v] || `${v} sedute`, 60);
  }
  renderCalculator();
  renderComparison();
  renderPlans();
  renderStrategyCards();
  renderTips();
}

function bindStrategies() {
  $("#st-calc").addEventListener("input", renderCalculator);
  $("#st-heat").addEventListener("click", (ev) => {
    const td = ev.target.closest("td.pick");
    if (!td) return;
    const f = $("#st-calc").elements;
    f.target.value = td.dataset.t;
    f.stop.value = td.dataset.s;
    renderCalculator();
  });
  $("#st-controls").addEventListener("input", () => {
    ST.capital = Math.max(500, parseFloat($("#st-capital").value) || 10000);
    ST.broker = $("#st-broker").value;
    stSave();
    renderCalculator();
    renderComparison();
    renderPlans();
    renderTips();
  });
  $("#st-plans-form").addEventListener("input", renderPlans);
  $("#st-table").addEventListener("change", (ev) => {
    const id = ev.target.dataset && ev.target.dataset.st;
    if (!id) return;
    ST.sel = ev.target.checked ? [...ST.sel.filter((x) => x !== id), id].slice(-4) : ST.sel.filter((x) => x !== id);
    stSave();
    renderComparison();
  });
  $("#st-tips").addEventListener("input", renderTips);
}
