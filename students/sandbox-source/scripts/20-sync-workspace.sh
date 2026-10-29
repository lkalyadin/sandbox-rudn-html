#!/usr/bin/env bash
# Кладёт в рабочую папку студентов то, с чем они будут работать:
# датасеты и стартовые файлы демо.
#
# Идемпотентен: датасеты копируются поверх (они большие и неизменные),
# шаблоны — только если их ещё нет.
#
# ВАЖНО (было два бага):
#  1. Рабочая папка — это отдельный loop-ext4, примонтированный в
#     /srv/opencode-student/workspace; в контейнер она приходит как /work.
#     Раньше путь был относительным ("workspace" в дереве исходников), и
#     скрипт раскладывал данные в пустую папку исходников.
#  2. Папка принадлежит uid 1000 (так сможет писать агент), а скрипт идёт от
#     deployagent (uid 1001) — записать туда нельзя. Поэтому копирование
#     делается внутри контейнера песочницы, от того же пользователя, что и
#     агент.
set -euo pipefail
cd "$(dirname "$0")/.."

# Настоящая рабочая папка (та, что в /work у песочницы). Путь не зашит в код:
# это соседний с sandbox каталог (на 45.159.173.8 — /srv/opencode/workspace,
# на хосте разработки — /srv/opencode-student/workspace). Переопределяется
# переменной WORKSPACE.
WORKSPACE="${WORKSPACE:-$(cd .. && pwd)/workspace}"
# Каталог с исходными датасетами. Путь не зашит: сначала DATASETS_DIR из
# окружения/.env, потом $HOME/datasets (так на стенде), потом
# $HOME/projects/datasets (так на хосте разработки).
if [ -n "${DATASETS_DIR:-}" ]; then
  DATASETS_SRC="${1:-$DATASETS_DIR}"
elif [ -d "$HOME/datasets" ]; then
  DATASETS_SRC="${1:-$HOME/datasets}"
else
  DATASETS_SRC="${1:-$HOME/projects/datasets}"
fi
# Стартовые файлы демо — лежат рядом с этим скриптом.
TEMPLATE="${TEMPLATE_DIR:-$PWD/workspace.template}"

if [ ! -d "${WORKSPACE}" ]; then
  echo "!! Рабочая папка не найдена: ${WORKSPACE}" >&2
  echo "   Проверьте, что loop-раздел смонтирован (systemctl status srv-opencode*workspace.mount)." >&2
  exit 1
fi

if [ ! -d "${DATASETS_SRC}" ]; then
  echo "!! Каталог с датасетами не найден: ${DATASETS_SRC}" >&2
  echo "   Укажите путь первым аргументом: scripts/20-sync-workspace.sh /path/to/datasets" >&2
  echo "   или задайте DATASETS_DIR в .env." >&2
  exit 1
fi

if [ ! -d "${TEMPLATE}" ]; then
  echo "!! Каталог с шаблонами не найден: ${TEMPLATE}" >&2
  exit 1
fi

echo "==> Копирую датасеты из ${DATASETS_SRC}"
echo "==> Раскладываю шаблоны (существующие не трогаю)"

# Работаем от пользователя песочницы (uid 1000): он владеет рабочей папкой.
docker compose run --rm --no-deps \
  -v "${DATASETS_SRC}:/src/datasets:ro" \
  -v "${TEMPLATE}:/src/template:ro" \
  --entrypoint sh sandbox -c '
    set -e
    mkdir -p /work/data /work/output /work/uploads
    # Датасеты лежат только для чтения (chmod 555/444 в конце): так агент не
    # может испортить общие данные одного студента для всех. Перед пересборкой
    # возвращаем себе права, иначе rm -rf внутри /work/data не сработает.
    chmod -R u+w /work/data 2>/dev/null || true
    rm -rf /work/data
    mkdir -p /work/data
    # cp -r, а не cp -a: файлы-источники принадлежат deployagent, мы работаем
    # от uid 1000 и не можем сохранять чужого владельца (cp -a на этом ругается).
    cp -r /src/datasets/. /work/data/
    # Только чтение для всех: данные неизменны, результаты — в папке задачи.
    chmod -R a-w /work/data
    cd /src/template
    find . -type f | while read -r f; do
      dest="/work/${f#./}"
      if [ -e "$dest" ]; then
        echo "    пропускаю (уже есть): $dest"
      else
        mkdir -p "$(dirname "$dest")"
        cp -r "/src/template/${f#./}" "$dest"
        echo "    создан: $dest"
      fi
    done
  ' </dev/null

echo "    файлов в data/: $(find "${WORKSPACE}/data" -type f 2>/dev/null | wc -l)"
echo "==> Готово. Рабочая папка: ${WORKSPACE}"
