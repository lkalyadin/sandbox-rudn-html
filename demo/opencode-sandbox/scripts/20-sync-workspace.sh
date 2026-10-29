#!/usr/bin/env bash
# Кладёт в рабочую папку студентов то, с чем они будут работать:
# датасеты и стартовые файлы демо.
#
# Идемпотентен: датасеты копируются поверх (они большие и неизменные),
# шаблоны — только если их ещё нет.
set -euo pipefail
cd "$(dirname "$0")/.."

DATASETS_SRC="${1:-../../datasets}"
WORKSPACE="workspace"
TEMPLATE="workspace.template"

mkdir -p "${WORKSPACE}/data" "${WORKSPACE}/output"

if [ ! -d "${DATASETS_SRC}" ]; then
  echo "!! Каталог с датасетами не найден: ${DATASETS_SRC}" >&2
  echo "   Укажите путь первым аргументом: scripts/20-sync-workspace.sh /path/to/datasets" >&2
  exit 1
fi

echo "==> Копирую датасеты из ${DATASETS_SRC}"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete "${DATASETS_SRC}/" "${WORKSPACE}/data/"
else
  rm -rf "${WORKSPACE}/data"
  mkdir -p "${WORKSPACE}/data"
  cp -a "${DATASETS_SRC}/." "${WORKSPACE}/data/"
fi
echo "    файлов: $(find "${WORKSPACE}/data" -type f | wc -l)"

echo "==> Раскладываю шаблоны (существующие не трогаю)"
if [ -d "${TEMPLATE}" ]; then
  (cd "${TEMPLATE}" && find . -type f -print0) | while IFS= read -r -d '' f; do
    dest="${WORKSPACE}/${f#./}"
    if [ -e "${dest}" ]; then
      echo "    пропускаю (уже есть): ${dest}"
    else
      mkdir -p "$(dirname "${dest}")"
      cp -a "${TEMPLATE}/${f#./}" "${dest}"
      echo "    создан: ${dest}"
    fi
  done
fi

echo "==> Готово. Рабочая папка: $(pwd)/${WORKSPACE}"
