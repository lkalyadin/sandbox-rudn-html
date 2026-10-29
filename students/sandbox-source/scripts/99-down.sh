#!/usr/bin/env bash
# Останавливает стенд. Данные по умолчанию сохраняются.
#
#   scripts/99-down.sh              # остановить, данные оставить
#   scripts/99-down.sh --volumes    # остановить и стереть состояние OpenCode
#   scripts/99-down.sh --purge      # всё, включая рабочую папку
set -euo pipefail
cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
[ -f .env ] && { set -a; . ./.env; set +a; }

# Настоящая рабочая папка (та, что в /work у песочницы). Раньше был
# относительный путь "workspace" — в дереве исходников, а не в /srv.
# Сейчас — соседний с sandbox каталог, переопределяется переменной WORKSPACE.
WORKSPACE="${WORKSPACE:-$(cd .. && pwd)/workspace}"

mode="${1:-}"

case "${mode}" in
  --volumes)
    echo "==> Останавливаю и удаляю тома"
    docker compose down --volumes
    ;;
  --purge)
    echo "==> Чищу рабочую папку"
    # Рабочая папка принадлежит uid 1000 — чистим из контейнера песочницы.
    # Это делается ДО `down`, иначе образ и контейнер уже удалены.
    docker compose run --rm --no-deps --entrypoint sh sandbox -c '
      find /work -mindepth 1 -maxdepth 1 ! -name lost+found -exec rm -rf {} +
    ' </dev/null || true
    echo "==> Полная очистка"
    docker compose down --volumes --rmi local
    echo "    рабочая папка очищена: ${WORKSPACE}"
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
