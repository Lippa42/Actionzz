#!/usr/bin/env bash
# Sessione di borsa: un solo job che resta attivo durante la giornata e controlla ogni 5 minuti.
# Non dipende dalla puntualità dei cron di GitHub (che nelle ore di punta ritardano o saltano).
# Tra un controllo e l'altro risponde subito ai comandi Telegram.
# Prima del limite di 6 ore dei job di GitHub avvia da sé la sessione successiva.
set -uo pipefail

BUDGET=$((340 * 60))  # 5h40m, sotto il limite di 6 ore
START=$(date +%s)
BRANCH="$(git rev-parse --abbrev-ref HEAD)"

sync_repo() {
  # salva le modifiche fatte da Telegram e prende quelle fatte dalla dashboard
  scripts/push_config.sh || true
  git pull -q --rebase origin "$BRANCH" || git rebase --abort 2>/dev/null || true
}

while true; do
  status="$(python -m actionzz session-status)"
  echo "$(date -u +%H:%M:%S) fase: $status"
  if [ "$status" = "closed" ]; then
    sync_repo
    python -m actionzz scan || true   # ultimo giro: eventuale riepilogo e comandi
    scripts/push_state.sh || true
    scripts/push_config.sh || true
    break
  fi

  sync_repo
  python -m actionzz scan || echo "::warning::scansione fallita, riprovo al prossimo giro"
  scripts/push_state.sh || echo "::warning::stato non salvato"
  scripts/push_config.sh || true

  if (( $(date +%s) - START > BUDGET )); then
    echo "Limite di tempo vicino: avvio la sessione successiva"
    curl -s -X POST -H "Authorization: Bearer ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json" \
      "https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/workflows/session.yml/dispatches" \
      -d "{\"ref\":\"${BRANCH}\"}" || true
    break
  fi

  python -m actionzz listen --minutes 5 || sleep 60
done
