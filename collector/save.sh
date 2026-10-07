#!/usr/bin/env bash
# Сохраняет ленту в репозиторий. Оба сбора (основной и сайты РК) пишут в одни файлы:
# если другой успел отправить свои изменения, берём свежую ленту и собираем заново поверх неё.
set -euo pipefail
git config user.name "med-news-bot"
git config user.email "med-news-bot@users.noreply.github.com"
for attempt in 1 2 3; do
  git add data docs
  git diff --cached --quiet && exit 0
  git commit -q -m "$1 $(date -u +'%Y-%m-%d %H:%M')"
  git push -q && exit 0
  echo "Лента обновилась параллельно, собираю заново (попытка $attempt)"
  sleep $((attempt * 10))
  git fetch -q origin main
  git reset -q --hard origin/main
  python collector/main.py
done
exit 1
