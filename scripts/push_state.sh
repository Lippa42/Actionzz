#!/usr/bin/env bash
# Pubblica stato/ sul branch `data` come unico commit (niente storico che cresce ogni 5 minuti).
set -euo pipefail
cd stato
git init -q
git checkout -q -b data
git add -A
git -c user.name="actionzz-bot" -c user.email="actionzz-bot@users.noreply.github.com" \
  commit -q --allow-empty -m "Dati aggiornati $(date -u +%Y-%m-%dT%H:%MZ)"
git push -q -f "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" data
rm -rf .git
