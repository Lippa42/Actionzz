#!/usr/bin/env bash
# Scarica i file di stato dal branch `data` nella cartella stato/ (vuota se il branch non esiste ancora).
set -euo pipefail
rm -rf stato
if ! git clone -q --depth 1 --branch data "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" stato 2>/dev/null; then
  echo "Branch data non ancora presente: parto da zero."
  mkdir -p stato
fi
rm -rf stato/.git
