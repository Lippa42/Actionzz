#!/usr/bin/env bash
# Se un comando Telegram ha cambiato impostazioni o portafoglio, li salva sul branch principale.
set -euo pipefail
FILES=(config/config.json)
[ -e config/portfolio.enc.json ] && FILES+=(config/portfolio.enc.json)
[ -e config/simulator.enc.json ] && FILES+=(config/simulator.enc.json)
git add -N "${FILES[@]}" 2>/dev/null || true
if git diff --quiet -- "${FILES[@]}"; then
  exit 0
fi
git config user.name "actionzz-bot"
git config user.email "actionzz-bot@users.noreply.github.com"
branch="$(git rev-parse --abbrev-ref HEAD)"
git add "${FILES[@]}"
git commit -q -m "Impostazioni, portafoglio o simulatore aggiornati da Telegram"
for attempt in 1 2 3; do
  if git pull -q --rebase origin "$branch" && git push -q origin "HEAD:$branch"; then
    exit 0
  fi
  git rebase --abort 2>/dev/null || true
  sleep $((attempt * 3))
done
echo "::warning::Impossibile salvare le modifiche fatte da Telegram (conflitto con la dashboard?): ripetile"
