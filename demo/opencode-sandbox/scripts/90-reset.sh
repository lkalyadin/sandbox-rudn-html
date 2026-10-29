#!/usr/bin/env bash
# Возвращает стенд в исходное состояние между парами.
#
# Что чистится: история сессий, база OpenCode, файлы, которые студенты
# наделали в /work/output и рядом.
# Что НЕ чистится: сами датасеты в /work/data — они неизменны и большие.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Останавливаю песочницу"
docker compose stop sandbox >/dev/null

echo "==> Чищу состояние OpenCode (сессии, БД, логи)"
docker compose run --rm --no-deps --entrypoint sh sandbox -c '
  rm -rf "${HOME}"/.local/share/opencode/* \
         "${HOME}"/.local/state/opencode/* \
         "${HOME}"/.config/opencode/* \
         "${HOME}"/.cache/opencode/* 2>/dev/null || true
' </dev/null

echo "==> Чищу рабочую папку (кроме data/)"
find workspace -mindepth 1 -maxdepth 1 ! -name data -exec rm -rf {} +

echo "==> Возвращаю стартовые файлы"
bash scripts/20-sync-workspace.sh >/dev/null
(cd workspace.template 2>/dev/null && find . -type f -print0) | while IFS= read -r -d '' f; do
  mkdir -p "$(dirname "workspace/${f#./}")"
  cp -a "workspace.template/${f#./}" "workspace/${f#./}"
done

echo "==> Поднимаю песочницу"
docker compose start sandbox >/dev/null

echo
echo "Стенд сброшен. Сессии студентов удалены."
bash scripts/40-info.sh
