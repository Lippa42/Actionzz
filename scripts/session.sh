#!/usr/bin/env bash
# Sessione continua: un job sempre attivo che si passa il testimone ogni ~5h40m (limite GitHub: 6 ore).
# Non dipende dai cron di GitHub, che sui repository nuovi vengono ritardati o saltati.
#  - borsa aperta: controllo ogni 5 minuti;
#  - fuori orario: ascolta i comandi Telegram (risposta immediata) e aggiorna portafoglio,
#    simulatore e riepilogo una volta all'ora.
set -uo pipefail

BUDGET=$((340 * 60))
START=$(date +%s)
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
LAST_FULL=0
STATE_HASH=""

elapsed() { echo $(( $(date +%s) - START )); }

dispatch_next() {
  curl -s -o /dev/null -w "avvio sessione successiva: HTTP %{http_code}\n" -X POST \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/workflows/session.yml/dispatches" \
    -d "{\"ref\":\"${BRANCH}\"}" || true
}

# Qualunque sia il motivo dell'uscita, la catena non si interrompe. Se la sessione è durata pochissimo
# (errore all'avvio) aspetto prima di ripartire, per non creare un ciclo di esecuzioni a vuoto.
on_exit() {
  local e; e=$(elapsed)
  if (( e < 600 )); then sleep $((600 - e)); fi
  dispatch_next
}
trap on_exit EXIT

sync_repo() {
  # salva le modifiche fatte da Telegram e prende quelle fatte dalla dashboard
  scripts/push_config.sh || true
  git pull -q --rebase origin "$BRANCH" || git rebase --abort 2>/dev/null || true
}

save_state_if_changed() {
  local h
  h="$(cat stato/*.json 2>/dev/null | sha1sum | cut -c1-40)"
  if [ "$h" != "$STATE_HASH" ]; then
    scripts/push_state.sh && STATE_HASH="$h" || echo "::warning::stato non salvato"
  fi
}

while (( $(elapsed) < BUDGET )); do
  status="$(python -m actionzz session-status)"
  if [ "$status" = "open" ] || (( $(date +%s) - LAST_FULL >= 3600 )); then
    echo "$(date -u +%H:%M:%S) fase: $status → controllo completo"
    sync_repo
    python -m actionzz scan || echo "::warning::scansione fallita, riprovo al prossimo giro"
    LAST_FULL=$(date +%s)
  fi
  save_state_if_changed
  scripts/push_config.sh || true
  python -m actionzz listen --minutes 5 || sleep 60
  save_state_if_changed
done
echo "Limite di tempo vicino: passo il testimone"
