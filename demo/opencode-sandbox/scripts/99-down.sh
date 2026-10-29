#!/usr/bin/env bash
# Останавливает стенд. Данные по умолчанию сохраняются.
#
#   scripts/99-down.sh              # остановить, данные оставить
#   scripts/99-down.sh --volumes    # остановить и стереть состояние OpenCode
#   scripts/99-down.sh --purge      # всё, включая рабочую папку
set -euo pipefail
cd "$(dirname "$0")/.."

mode="${1:-}"

case "${mode}" in
  --volumes)
    echo "==> Останавливаю и удаляю тома"
    docker compose down --volumes
    ;;
  --purge)
    echo "==> Полная очистка"
    docker compose down --volumes --rmi local
    find workspace -mindepth 1 -maxdepth 1 -exec rm -rf {} +
    echo "    рабочая папка очищена"
    ;;
  "")
    echo "==> Останавливаю (данные сохраняются)"
    docker compose down
    ;;
  *)
    echo "Неизвестный аргумент: ${mode}" >&2
    echo "Использование: $0 [--volumes|--purge]" >&2
    exit 1
    ;;
esac

echo "Готово."
