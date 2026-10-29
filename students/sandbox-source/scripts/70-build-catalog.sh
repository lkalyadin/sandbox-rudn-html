#!/usr/bin/env bash
# Пересобирает каталог учебных датасетов из GitHub.
#
# Каталог лежит в catalog/ и примонтирован в песочницу как /opt/catalog
# (только на чтение). Агент читает его, когда студент спрашивает, какие
# данные доступны.
#
#   scripts/70-build-catalog.sh              # дерево + колонки (дольше, ~2 мин)
#   scripts/70-build-catalog.sh --quick      # только дерево (секунды)
#
# Файлы обновляются атомарно (запись во временный файл + mv), чтобы песочница
# никогда не увидела наполовину записанный каталог.
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="$PWD/catalog"
EXTRA=()
WITH_HEADERS=1
for a in "$@"; do
  case "$a" in
    --quick) WITH_HEADERS=0 ;;
    *)       EXTRA+=("$a") ;;
  esac
done

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

echo "==> Сканирую репозиторий с датасетами"
if [ "${WITH_HEADERS}" = "1" ]; then
  python3 catalog/scan_catalog.py --out-dir "${TMP}" --headers "${EXTRA[@]}"
else
  echo "    (быстрый режим: без колонок)"
  python3 catalog/scan_catalog.py --out-dir "${TMP}" "${EXTRA[@]}"
fi

echo "==> Обновляю каталог"
install -m 644 "${TMP}/catalog.md"   "${OUT}/catalog.md.new"
install -m 644 "${TMP}/catalog.json" "${OUT}/catalog.json.new"
mv -f "${OUT}/catalog.md.new"   "${OUT}/catalog.md"
mv -f "${OUT}/catalog.json.new" "${OUT}/catalog.json"

echo "==> Готово: $(grep -c '^| ' "${OUT}/catalog.md") строк, $(du -h "${OUT}/catalog.md" | cut -f1)"
echo "    Каталог в песочнице: /opt/catalog/catalog.md"
