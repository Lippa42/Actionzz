/* Actionzz – esperienza da telefono (pensata per iPhone in Safari o aggiunta alla schermata Home).
 * Riconosce il dispositivo, gestisce la barra delle schede in basso, i fogli che salgono dal basso
 * e il "trascina per aggiornare" quando l'app è aperta a schermo intero. */
"use strict";

const PHONE_QUERY = matchMedia("(max-width: 760px), (pointer: coarse) and (max-height: 500px)");
const IS_IOS = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const IS_STANDALONE = navigator.standalone === true || matchMedia("(display-mode: standalone)").matches;
const TAB_TITLES = {
  overview: "Home", portfolio: "Portafoglio", simulator: "Simulatore", today: "Mercato",
  alerts: "Avvisi", universe: "Universo", backtest: "Backtest", settings: "Impostazioni",
};
const MORE_TABS = ["alerts", "universe", "backtest", "settings"];

const isPhone = () => document.body.classList.contains("mobile");

function applyDevice() {
  const c = document.body.classList;
  c.toggle("mobile", PHONE_QUERY.matches);
  c.toggle("ios", IS_IOS);
  c.toggle("standalone", IS_STANDALONE);
  $("#install-hint").hidden = !(IS_IOS && !IS_STANDALONE);
  if (!PHONE_QUERY.matches) closeSheets();
}

// chiamata da selectTab() in app.js
function onTabChange(name) {
  $("#mobile-title").textContent = TAB_TITLES[name] || "Actionzz";
  const more = document.querySelector(".tabbar [data-more]");
  more.setAttribute("aria-selected", String(MORE_TABS.includes(name)));
  if (isPhone()) {
    closeSheets();
    window.scrollTo(0, 0);
  }
}

/* --------------------------------------------------------------- fogli */

function openSheet(el) {
  $("#sheet-backdrop").hidden = false;
  el.hidden = false;
  el.classList.add("open");
  document.body.classList.add("sheet-open");
  el.style.transform = "";
}

function closeSheets() {
  document.querySelectorAll(".sheet.open, .pf-detail.open").forEach((el) => {
    el.classList.remove("open");
    el.style.transform = "";
    if (el.classList.contains("sheet")) el.hidden = true;
  });
  $("#sheet-backdrop").hidden = true;
  document.body.classList.remove("sheet-open");
}

// trascinare in giù un foglio lo chiude
function swipeToClose(el) {
  let startY = null, dy = 0;
  el.addEventListener("touchstart", (ev) => {
    startY = el.scrollTop <= 0 ? ev.touches[0].clientY : null;
    dy = 0;
  }, { passive: true });
  el.addEventListener("touchmove", (ev) => {
    if (startY === null) return;
    dy = Math.max(0, ev.touches[0].clientY - startY);
    if (dy > 0) el.style.transform = `translateY(${dy}px)`;
  }, { passive: true });
  el.addEventListener("touchend", () => {
    if (startY === null) return;
    if (dy > 90) closeSheets();
    else el.style.transform = "";
    startY = null;
  });
}

/* ------------------------------------------------- trascina per aggiornare */

function pullToRefresh() {
  // Safari ha già il suo; serve solo nell'app a schermo intero
  if (!IS_STANDALONE) return;
  const ptr = $("#ptr"), label = $("#ptr-text");
  let startY = null, dy = 0, busy = false;
  const LIMIT = 70;
  addEventListener("touchstart", (ev) => {
    if (busy || window.scrollY > 0 || document.body.classList.contains("sheet-open") || document.body.classList.contains("locked")) return;
    startY = ev.touches[0].clientY;
    dy = 0;
  }, { passive: true });
  addEventListener("touchmove", (ev) => {
    if (startY === null) return;
    dy = Math.max(0, ev.touches[0].clientY - startY);
    if (dy <= 0 || window.scrollY > 0) return;
    ptr.classList.add("visible");
    ptr.style.transform = `translate(-50%, ${Math.min(dy, 110) * 0.6}px)`;
    label.textContent = dy > LIMIT ? "Rilascia per aggiornare" : "Trascina per aggiornare";
  }, { passive: true });
  addEventListener("touchend", async () => {
    if (startY === null) return;
    startY = null;
    if (dy > LIMIT) {
      busy = true;
      ptr.classList.add("loading");
      label.textContent = "Aggiornamento…";
      try {
        await loadAll();
      } finally {
        busy = false;
        ptr.classList.remove("loading");
      }
    }
    ptr.classList.remove("visible");
    ptr.style.transform = "";
  });
}

/* ------------------------------------------------------- colore barra di stato */

function syncThemeColor() {
  const bg = getComputedStyle(document.body).backgroundColor;
  document.querySelectorAll('meta[name="theme-color"]').forEach((m) => {
    if (document.documentElement.dataset.theme) {
      m.setAttribute("content", bg);
      m.removeAttribute("media");
    }
  });
}

/* ----------------------------------------------------------------- avvio */

function bindMobile() {
  applyDevice();
  PHONE_QUERY.addEventListener("change", applyDevice);
  document.querySelectorAll(".tabbar button[data-tab]").forEach((b) => b.addEventListener("click", () => selectTab(b.dataset.tab)));
  document.querySelector(".tabbar [data-more]").addEventListener("click", () => openSheet($("#more-sheet")));
  $("#sheet-backdrop").addEventListener("click", closeSheets);
  $("#more-sheet").addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    if (!b) return;
    if (b.dataset.tab) selectTab(b.dataset.tab);
    if (b.dataset.action === "refresh") {
      closeSheets();
      loadAll();
    }
    if (b.dataset.action === "theme") {
      $("#theme").click();
      syncThemeColor();
    }
    if (b.dataset.action === "logout") logout();
  });
  swipeToClose($("#more-sheet"));
  document.querySelectorAll(".clamp").forEach((el) => el.addEventListener("click", () => el.classList.toggle("expanded")));
  swipeToClose($("#pf-detail"));

  // dettaglio di un titolo del portafoglio: su telefono si apre dal basso
  $("#tab-portfolio").addEventListener("click", (ev) => {
    const pick = ev.target.closest("[data-pick]");
    if (pick && pick.dataset.pick && isPhone()) openSheet($("#pf-detail"));
    if (ev.target.closest("[data-close-sheet]")) closeSheets();
  });
  $("#theme").addEventListener("click", syncThemeColor);
  new MutationObserver(syncThemeColor).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  syncThemeColor();
  pullToRefresh();
  const current = document.querySelector(".tabs button[aria-selected='true']");
  onTabChange(current ? current.dataset.tab : "overview");
}

bindMobile();
