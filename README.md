# Actionzz 📉🤖

Monitora **500 azioni europee tra le più stabili** degli ultimi 5 anni e ti avvisa **su Telegram** quando una di
queste subisce un **calo improvviso** rispetto alla chiusura del giorno prima. Include una **dashboard web** (GitHub
Pages) da cui vedere tutto e modificare le impostazioni.

Tutto gratuito: dati da Yahoo Finance tramite [yfinance](https://github.com/ranaroussi/yfinance), esecuzione su
GitHub Actions, dashboard su GitHub Pages.

> ⚠️ Strumento informativo, non un consiglio d'investimento. I dati gratuiti di Yahoo hanno circa 15 minuti di ritardo
> e ogni tanto contengono errori.

---

## Come funziona

```
            ogni 5 minuti (lun-ven, 9:00-18:00)                     1° del mese
┌───────────────────────────────────────────────┐     ┌──────────────────────────────┐
│ Workflow "Scanner"                            │     │ Workflow "Universo e backtest"│
│ 1. legge i comandi Telegram (/soglia, ...)    │     │ 1. storico 5 anni di ~870    │
│ 2. scarica i prezzi dei 500 titoli (yfinance) │     │    candidati europei         │
│ 3. confronta con la chiusura di ieri          │     │ 2. tiene i 500 meno volatili │
│ 4. invia avvisi e riepilogo su Telegram       │     │ 3. backtest delle soglie     │
└──────────────┬────────────────────────────────┘     └──────────────┬───────────────┘
               │ salva i JSON                                          │
               ▼                                                       ▼
         branch `data`  ◄───────── legge ───────── Dashboard (GitHub Pages)
                                                   modifica ──► config/config.json
```

### Quali titoli
- **Candidati** (`data/candidates.csv`, ~870 titoli): i componenti di FTSE 100/250, DAX, CAC 40, CAC Next 20,
  FTSE MIB, IBEX 35, AEX, AMX, AScX, BEL 20, SMI, SMIM, OMX Stoccolma 30, OMX Copenaghen 25, OMX Helsinki 25, OBX,
  PSI, ISEQ 20, EURO STOXX 50 e STOXX Europe 600, presi da Wikipedia. Sono esclusi fondi, investment trust e veicoli
  di private equity quotati.
- **Universo**: ogni mese si scaricano 5 anni di prezzi e si tengono i **500 titoli con la volatilità annua più
  bassa**, scartando quelli quotati da meno di 4,5 anni o con dati anomali. Puoi forzare l'inclusione o l'esclusione
  di qualsiasi ticker.

### Quando arriva un avviso
1. Il prezzo attuale è sceso di almeno **5%** rispetto alla chiusura di ieri (rettificata per l'eventuale dividendo
   staccato oggi, così uno stacco non sembra un crollo).
2. **Filtro mercato**: il titolo deve fare almeno **3 punti peggio** del mercato, cioè della variazione mediana di tutto
   l'universo. Se scende tutto insieme ricevi **un solo messaggio** "calo generalizzato" (oltre −2,5%), non 500.
3. **Niente spam**: un titolo già segnalato oggi viene risegnalato solo se **scende di altri 2 punti**.

Ogni avviso contiene: prezzo e calo, minimo di giornata, confronto con il mercato, quanto il calo è anomalo rispetto
all'oscillazione tipica del titolo, volume rispetto alla media, distanza da massimo e minimo a 52 settimane,
rendimento a 1 anno, volatilità e massimo calo a 5 anni, P/E, dividendo, P/BV, capitalizzazione, beta, prezzo
obiettivo degli analisti, ultime notizie, link a Yahoo Finance e grafico degli ultimi 6 mesi.

Dopo la chiusura (18:00) arriva il **riepilogo giornaliero**: avvisi del giorno e chiusura dei titoli segnalati,
i 10 peggiori, i 5 migliori e i titoli vicini alla soglia.

Tutte le soglie si cambiano dalla dashboard o da Telegram.

### Il tuo portafoglio e i segnali di vendita
Nella scheda **Portafoglio** della dashboard registri acquisti (anche a più riprese) e vendite. Vedi valore,
guadagno o perdita in euro (con le valute convertite), la stima al netto delle tasse (26%) e le plusvalenze già
realizzate. Per ogni titolo lo scanner calcola dei **segnali di vendita** con regole trasparenti:

| Segnale | Quando scatta |
|---|---|
| 🔴 Obiettivo di guadagno | guadagno oltre il **+25%** (modificabile) |
| 🔴 Stop di perdita | perdita oltre il **−15%** (modificabile) |
| 🔴/🟠 Calo dal massimo | **−12%** dal prezzo più alto toccato da quando possiedi il titolo |
| 🔴/🟠 Ipercomprato | RSI a 14 giorni oltre 70 (oltre 80 è forte) |
| 🟠 Corsa estesa | prezzo oltre il 25% sopra la media a 200 giorni |
| 🟠 Tendenza negativa | sotto la media a 200 giorni, con la media a 50 più bassa |
| 🟠 Obiettivo analisti | prezzo oltre il prezzo obiettivo medio degli analisti, o giudizio medio negativo |
| 🟢 Motivi per aspettare | RSI sotto 30, potenziale residuo per gli analisti oltre il 15%, calo improvviso di oggi |

La somma dei pesi dà una valutazione: **🔴 vendere almeno in parte**, **🟠 da tenere d'occhio** oppure
**🟢 nessun segnale**. Quando un titolo ha un nuovo segnale arriva un messaggio su Telegram (una volta per segnale,
solo in orario di borsa); `/portafoglio` mostra il riepilogo e `/portafoglio TICKER` la scheda di un titolo.
Sono regole tecniche automatiche, non una previsione: la decisione resta tua.

**Dal telefono**: scrivi al bot `/compra TICKER QUANTITÀ PREZZO` appena compri. Il bot registra l'acquisto nel
portafoglio cifrato (lo stesso della dashboard) e risponde con il **piano di vendita**: il prezzo sopra cui
incassare, quello sotto cui uscire, il livello di protezione dal massimo e quanto è realistico l'obiettivo rispetto
alle oscillazioni tipiche del titolo. Poi ti scrive da solo quando uno di quei livelli viene toccato.

### Simulatore: soldi finti, costi veri
Nella scheda **Simulatore** (o con `/simcompra`, `/simvendi`, `/simversa` su Telegram) parti da un budget, puoi
aggiungere denaro quando vuoi e compri/vendi "per finta" per vedere come sarebbe andata. Tutto è calcolato come per
un investitore italiano:

- **ordini** al mercato o con prezzo limite, validi per la seduta o fino a revoca, solo azioni intere; eseguiti
  dallo scanner **a borsa aperta** al prezzo del momento (ritardato di ~15 minuti) più un piccolo scostamento;
- **commissioni** del broker scelto (Italia, Europa e USA separate) e **costo del cambio** per i titoli non in euro;
- **tasse sulle transazioni** all'acquisto: Tobin tax italiana **0,2%** (raddoppiata dal 1/1/2026), Francia 0,4%,
  Spagna 0,2%, stamp duty UK 0,5% e Irlanda 1% (applicate in base alla borsa, senza le esenzioni per le società
  più piccole);
- **26% sulle plusvalenze** calcolate in euro sul costo medio ponderato; le **minusvalenze** finiscono nello
  zainetto fiscale e compensano le plusvalenze dei 4 anni successivi;
- **regime amministrato** (tasse trattenute subito) o **dichiarativo** (DEGIRO, Interactive Brokers: tasse pagate
  con il saldo del 30 giugno dell'anno dopo);
- **dividendi** accreditati allo stacco al netto della ritenuta estera (aliquote indicative) e del 26%;
- **imposta di bollo** 0,2% annuo sul valore dei titoli, addebitata giorno per giorno.

Il **confronto broker** (`site/brokers.json`, verificato a settembre 2026: Trade Republic, Scalable Capital,
DEGIRO, Interactive Brokers, Directa, Fineco) mostra il costo di un ordine da 2.000 € su ogni mercato: un clic su
*Usa* applica quelle tariffe alla simulazione. Si possono anche impostare costi personalizzati.

### Strategie: quanto si guadagna davvero, costi e tasse compresi
La scheda **Strategie** usa i prezzi reali degli ultimi 5 anni dei titoli dell'universo:

- **Compro a −X%, rivendo a +Y%**: scegli il calo d'acquisto, l'obiettivo, lo stop, la durata massima, l'importo e
  quante operazioni pensi di fare. Vedi il risultato "se tutto andasse bene", quello tipico e la forchetta realistica
  (Monte Carlo sugli esiti storici), la probabilità di perdere, i costi di ogni operazione con il tuo broker e il
  capitale che serve. Una tabella colorata mostra quale combinazione di obiettivo e stop ha reso di più.
- **Confronto tra 14 strategie** tratte dalla letteratura: momentum, vicinanza al massimo annuale, trend following,
  bassa volatilità, inversione di breve periodo, acquisto sui cali, RSI(2), Halloween, effetto fine mese, ETF da tenere.
  Il rendimento è mostrato al netto di commissioni, tasse sulle transazioni, cambio, bollo e 26% sulle plusvalenze
  con zainetto fiscale. Ogni strategia ha una scheda che spiega come funziona, cosa dicono gli studi e perché può fallire.
- **Consigli interattivi dalla ricerca**: costo del trading frequente, recupero dalle perdite, i giorni migliori persi,
  PAC o tutto subito, diversificazione, effetto disposizione, falsi positivi nei backtest, tasse italiane.

I calcoli si rifanno da soli una volta al mese, di notte (`python -m actionzz strategies`). Attenzione: l'universo contiene
i titoli stabili *di oggi*, quindi i risultati passati sono più belli di quanto sarà il futuro.

### Password e privacy
La dashboard si apre solo con la **password** scelta al primo accesso. Il repository è pubblico, quindi la
password non è un semplice cancello: **cifra** (AES-256-GCM, chiave PBKDF2 con 310.000 iterazioni) il portafoglio
(`config/portfolio.enc.json`), i relativi consigli sul branch `data` e il token GitHub salvato nel browser. Senza
password nessuno può leggerli. Restano pubblici solo i dati di mercato generici (i 500 titoli, le quotazioni, gli
avvisi sui cali), che non dicono nulla di te.

- Usa una password lunga (almeno 10 caratteri, meglio una frase): chi scarica il file cifrato può provare a
  indovinarla quante volte vuole.
- La password **non si può recuperare**: se la perdi, il portafoglio va reinserito.
- Lo scanner ha bisogno della stessa password nel secret `PORTFOLIO_PASSWORD` per calcolare i consigli.

---

## Installazione (circa 15 minuti)

### 1. Repository pubblico (consigliato)
Con un account GitHub gratuito **GitHub Pages funziona solo sui repository pubblici**, e i minuti di Actions sono
illimitati solo per quelli pubblici. Su un repository privato uno scanner ogni 5 minuti consuma circa 4.000
minuti al mese, oltre i 2.000 gratuiti.

*Settings → General → Danger Zone → Change visibility → Public.*
Token e chat id restano **segreti** (sono in *Secrets*). Diventano visibili a tutti solo il codice, le impostazioni
e i dati di mercato su cui lavora il bot.

### 2. Branch predefinito
I workflow pianificati e la dashboard usano il **branch predefinito** del repository, qualunque sia il suo nome.
Se vuoi chiamarlo `main`: *Settings → General → Default branch* → rinominalo (GitHub aggiorna tutto da solo).

### 3. Crea il bot Telegram
1. Su Telegram apri **@BotFather** → `/newbot` → scegli nome e username.
2. Copia il **token** (tipo `123456:ABC-DEF...`).
3. Apri la chat con il tuo nuovo bot e premi **Avvia** (`/start`).

### 4. Salva i secret su GitHub
*Settings → Secrets and variables → Actions → New repository secret*:

| Nome | Valore |
|---|---|
| `TELEGRAM_TOKEN` | il token di BotFather |
| `TELEGRAM_CHAT_ID` | il tuo chat id (vedi sotto) |
| `PORTFOLIO_PASSWORD` | la password della dashboard (serve per i consigli sul portafoglio) |

**Come trovare il chat id**: salva prima solo `TELEGRAM_TOKEN`, scrivi `/start` al bot e avvia a mano il workflow
**Scanner** (*Actions → Scanner → Run workflow*). Il bot ti risponderà con il tuo chat id. In alternativa apri
`https://api.telegram.org/bot<TOKEN>/getUpdates` e cerca `"chat":{"id":...}`.

Il bot risponde **solo** alla chat indicata in `TELEGRAM_CHAT_ID`.

### 5. Primo calcolo dell'universo
*Actions → Universo e backtest → Run workflow*. Ci mette 3-5 minuti e crea il branch `data`.
(Se lo salti, lo Scanner lo calcola da solo alla prima esecuzione.)

### 6. Attiva la dashboard
1. *Settings → Pages → Build and deployment → Source: **GitHub Actions***.
2. *Actions → Dashboard (GitHub Pages) → Run workflow*.
3. Apri `https://<tuo-utente>.github.io/<repository>/` (per te: https://lippa42.github.io/Actionzz/).

Al primo accesso la dashboard ti chiede di **creare una password** (vedi *Password e privacy*); salvala anche nel
secret `PORTFOLIO_PASSWORD`.

Per **salvare impostazioni e portafoglio** dalla dashboard serve un token personale, salvato solo nel tuo browser
(cifrato con la password):
1. https://github.com/settings/personal-access-tokens/new → *Fine-grained token*.
2. *Repository access: Only select repositories* → questo repository.
3. *Permissions → Repository permissions → Contents: Read and write*.
4. Incollalo nella dashboard in *Impostazioni → Collegamento a GitHub*.

### 7. Prova
Dalla cartella del progetto, sul tuo PC:
```bash
pip install -r requirements.txt
export TELEGRAM_TOKEN=...  TELEGRAM_CHAT_ID=...
python -m actionzz test-telegram   # messaggio di prova + menu dei comandi del bot
```

---

## Comandi Telegram

| Comando | Cosa fa |
|---|---|
| `/stato` | stato del monitor e impostazioni attuali |
| `/oggi [n]` | i titoli peggiori di oggi |
| `/avvisi` | avvisi inviati oggi |
| `/titolo ENEL.MI` | scheda completa di un titolo qualsiasi |
| `/cerca nestle` | cerca un ticker per nome |
| `/riepilogo` | riepilogo della giornata adesso |
| `/universo` | composizione dell'universo |
| `/portafoglio [TICKER]` | il tuo portafoglio e i segnali di vendita |
| `/compra ENEL.MI 100 6,50 [comm.]` | registra un acquisto e risponde con il **piano di vendita** |
| `/vendi ENEL.MI 50 7,20 [comm.]` | registra una vendita (lotti più vecchi per primi) e calcola la plusvalenza |
| `/piano ENEL.MI` | quando vendere un titolo che possiedi |
| `/obiettivo 20` · `/stop 10` | obiettivo di guadagno e stop di perdita (%) |
| `/sim` | stato del conto simulato |
| `/simnuovo 10000` | nuova simulazione con questo budget |
| `/simcompra ENEL.MI 100 [limite]` · `/simcompra ENEL.MI 1000€` | ordine di acquisto simulato |
| `/simvendi ENEL.MI 50\|tutto [limite]` | ordine di vendita simulato |
| `/simversa 1000` | aggiungi denaro al budget |
| `/simbroker [ID]` | confronta i broker e scegli le tariffe da simulare |
| `/soglia 6` | calo minimo in % |
| `/relativa 3` | punti peggio del mercato |
| `/filtro on\|off` | filtro sui cali generalizzati |
| `/passo 2` | ulteriore calo per un nuovo avviso |
| `/aggiungi TICKER` · `/rimuovi TICKER` | forza inclusione/esclusione |
| `/pausa` · `/riprendi` | sospende/riattiva gli avvisi |

Su GitHub Actions i comandi vengono letti a ogni esecuzione: **entro 5-10 minuti durante la borsa**, ogni 2 ore
fuori orario. Con l'esecuzione continua su PC (sotto) la risposta è immediata.

---

## Esecuzione continua su PC o Raspberry Pi (alternativa)

```bash
pip install -r requirements.txt
export TELEGRAM_TOKEN=...  TELEGRAM_CHAT_ID=...
python -m actionzz universe   # la prima volta, poi una volta al mese
python -m actionzz loop       # scansione ogni 5 minuti in orario di borsa, comandi istantanei
```

Altri comandi: `python -m actionzz scan` (un solo ciclo), `backtest`, `summary`, `chat-id`.
I file di stato finiscono in `./stato` (cambiabile con `--data-dir` o `ACTIONZZ_DATA_DIR`).

---

## Backtest: tarare la soglia

La scheda **Backtest** della dashboard (o `python -m actionzz backtest`) simula gli ultimi 5 anni: quanti avvisi
sarebbero arrivati con ogni soglia (−3% … −12%) e come si sono mossi quei titoli dopo 5, 20 e 60 sedute, anche
rispetto al mercato. Approssimazioni: barre giornaliere (scatta se il minimo del giorno supera la soglia, si compra
alla chiusura), universo di oggi (i titoli falliti mancano, quindi i risultati sono ottimistici), esclusi i salti
di prezzo oltre ±40% (scorpori ed errori di Yahoo).

---

## Limiti da conoscere
- **Ritardo dei dati**: Yahoo fornisce le quotazioni europee con circa 15 minuti di ritardo.
- **Orari di GitHub**: i workflow pianificati possono partire con qualche minuto di ritardo nelle ore di punta.
- **yfinance non è un'API ufficiale**: Yahoo può cambiare qualcosa o limitare le richieste. In quel caso l'esecuzione
  fallisce e riprova 5 minuti dopo; aggiorna `yfinance` se il problema persiste.
- **Festività**: non c'è un calendario; nei giorni di chiusura Yahoo non produce una barra con la data di oggi e il
  titolo viene saltato.
- **Uso di Actions come scheduler**: va bene per un progetto personale come questo, ma GitHub può disattivare i
  workflow pianificati di un repository senza attività da 60 giorni (si riattivano da *Actions*).

## Sviluppo
```bash
pip install -r requirements-dev.txt
python -m pytest -q
python scripts/build_candidates.py        # rigenera la lista dei candidati da Wikipedia
```
Per provare la dashboard in locale con dati di esempio: metti i JSON in `site/demo/` e apri
`site/index.html?dati=demo/` con un server locale (`python -m http.server -d site`).

Struttura:
```
actionzz/          codice Python
  detector.py      logica dei cali (pura, testata)
  monitor.py       ciclo: comandi → scansione → avvisi → riepilogo
  universe.py      selezione dei titoli più stabili
  backtest.py      simulazione storica
  portfolio.py     portafoglio personale e segnali di vendita
  crypto.py        cifratura compatibile con la dashboard
  simulator.py     simulatore di compravendita con costi e tasse reali
  commands.py      comandi Telegram
  messages.py      testi dei messaggi
config/config.json impostazioni (modificate da dashboard e Telegram)
data/candidates.csv candidati
site/              dashboard statica (GitHub Pages)
.github/workflows/ scanner, universo, test, pages
```
