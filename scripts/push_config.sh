#!/usr/bin/env bash
# Se un comando Telegram ha cambiato le impostazioni, salva config/config.json sul branch principale.
set -euo pipefail
if git diff --quiet -- config/config.json; then
  exit 0
fi
git config user.name "actionzz-bot"
git config user.email "actionzz-bot@users.noreply.github.com"
branch="$(git rev-parse --abbrev-ref HEAD)"
git add config/config.json
git commit -q -m "Impostazioni aggiornate da Telegram"
for attempt in 1 2 3; do
  if git pull -q --rebase origin "$branch" && git push -q origin "HEAD:$branch"; then
    exit 0
  fi
  sleep $((attempt * 3))
done
echo "::warning::Impossibile salvare le impostazioni modificate da Telegram"
