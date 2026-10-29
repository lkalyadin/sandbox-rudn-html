#!/usr/bin/env bash
# Возвращает стенд в исходное состояние между парами.
#
# Что чистится:
#   * история сессий, база OpenCode, логи — так исчезают и сессии, в которых
#     студент получал ссылки на результат;
#   * файлы, которые студенты наделали в рабочей папке (output/, uploads/ и пр.);
#   * состояние OpenCode внутри контейнера (кэш моделей, конфиг, база).
#
# Что НЕ чистится: сами датасеты в data/ — они неизменны и большие.
# Они всё равно пересобираются из DATASETS_DIR, чтобы после ночной очистки
# студенты снова находили данные.
#
# ВАЖНО (был баг): путь к рабочей папке был относительным ("workspace" в дереве
# исходников), поэтому скрипт чистил пустую папку, а не /work песочницы.
# И он падал на scripts/20-sync-workspace.sh, не успев поднять песочницу:
# студенты оставались без стенда. Теперь путь абсолютный, а песочница
# поднимается в любом случае (trap).
#
#   scripts/90-reset.sh              # сброс, датасеты и стартовые файлы на месте
#   scripts/90-reset.sh --purge      # сброс + полностью убрать data/
set -euo pipefail
cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
[ -f .env ] && { set -a; . ./.env; set +a; }

WORKSPACE="${WORKSPACE:-$(cd .. && pwd)/workspace}"
DATASETS_DIR="${DATASETS_DIR:-/home/deployagent/projects/datasets}"
PURGE_DATA=false
[ "${1:-}" = "--purge" ] && PURGE_DATA=true

echo "==> Останавливаю песочницу"
docker compose stop sandbox >/dev/null 2>&1 || true

# Песочницу поднимаем при любом исходе: даже если чистка упадёт, студенты
# не останутся без стенда.
sandbox_started=false
cleanup() {
  local rc=$?
  if [ "${sandbox_started}" != "true" ]; then
    echo "==> Поднимаю песочницу"
    docker compose start sandbox >/dev/null 2>&1 || true
  fi
  if [ "${rc}" -ne 0 ]; then
    echo
    echo "!! Сброс прервался с кодом ${rc}. Песочницу поднял, но состояние может быть неполным." >&2
    echo "   Разберитесь и повторите: scripts/90-reset.sh" >&2
  fi
  exit "${rc}"
}
trap cleanup EXIT

echo "==> Чищу состояние OpenCode (сессии, БД, логи, кэш)"
docker compose run --rm --no-deps --entrypoint sh sandbox -c '
  rm -rf "${HOME}"/.local/share/opencode/* \
         "${HOME}"/.local/state/opencode/* \
         "${HOME}"/.config/opencode/* \
         "${HOME}"/.cache/opencode/* 2>/dev/null || true
' </dev/null

echo "==> Чищу рабочую папку (${WORKSPACE})"
# Чистим от пользователя песочницы (uid 1000): он владеет рабочей папкой,
# а скрипт идёт от deployagent и записи туда не имеет.
if [ "${PURGE_DATA}" = "true" ]; then
  docker compose run --rm --no-deps --entrypoint sh sandbox -c '
    chmod -R u+w /work/data 2>/dev/null || true
    find /work -mindepth 1 -maxdepth 1 ! -name lost+found -exec rm -rf {} +
  ' </dev/null
  echo "    очищено всё, включая data/"
else
  docker compose run --rm --no-deps --entrypoint sh sandbox -c '
    find /work -mindepth 1 -maxdepth 1 ! -name data ! -name lost+found -exec rm -rf {} +
  ' </dev/null
  echo "    очищено всё, кроме data/ (датасеты пересобираются следующим шагом)"
fi

echo "==> Возвращаю датасеты и стартовые файлы"
bash scripts/20-sync-workspace.sh "${DATASETS_DIR}" >/dev/null

echo "==> Поднимаю песочницу"
docker compose start sandbox >/dev/null
sandbox_started=true

echo "==> Жду готовности (до 90 секунд)"
deadline=$(( $(date +%s) + 90 ))
ready=false
while [ "$(date +%s)" -lt "${deadline}" ]; do
  code=$(curl -s -k -o /dev/null -w '%{http_code}' --max-time 5 "https://127.0.0.1:${EDGE_HTTPS_PORT:-443}/" || true)
  if printf '%s' "${code}" | grep -qE '^[23]'; then
    ready=true
    break
  fi
  sleep 2
done

if [ "${ready}" != "true" ]; then
  echo "!! Стенд не ответил за 90 секунд. Смотрите логи:" >&2
  echo "   docker compose logs --tail=80 sandbox" >&2
  exit 1
fi

# БД песочницы только что очищена → проект /work появится заново и без имени.
# Возвращаем дефолтный проект стенда: /work с именем "work".
echo "==> Возвращаю дефолтный проект (work)"
bash scripts/92-project-work.sh

trap - EXIT

echo
echo "Стенд сброшен. Сессии студентов и их файлы удалены, ссылка на старый"
echo "результат больше не открывается. Данные и стартовые файлы на месте."
bash scripts/40-info.sh
