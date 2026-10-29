#!/usr/bin/env bash
# Печатает всё, что нужно раздать студентам: адрес, логин, пароль.
#
# Пароль по умолчанию замаскирован: скрипт часто запускают на сервере, где
# вывод попадает в логи сессии. Показать целиком: scripts/40-info.sh --show
set -euo pipefail
cd "$(dirname "$0")/.."

show_secret=false
[ "${1:-}" = "--show" ] && show_secret=true

if [ ! -f .env ]; then
  echo "Нет .env" >&2
  exit 1
fi
# shellcheck disable=SC1091
set -a; . ./.env; set +a
EDGE_PORT="${EDGE_PORT:-80}"

if [ "${ENABLE_TLS:-false}" = "true" ]; then
  scheme=https
  port="${EDGE_HTTPS_PORT:-443}"
else
  scheme=http
  port="${EDGE_PORT}"
fi

# Основной внешний адрес: первый не-loopback IPv4.
host=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -z "${host}" ] && host="<IP-сервера>"

url="${scheme}://${host}"
if { [ "${scheme}" = "http" ] && [ "${port}" != "80" ]; } || { [ "${scheme}" = "https" ] && [ "${port}" != "443" ]; }; then
  url="${url}:${port}"
fi

password="${SANDBOX_PASSWORD:-}"
if [ "${show_secret}" != "true" ]; then
  password="******** (показать: scripts/40-info.sh --show)"
fi

cat <<EOF
────────────────────────────────────────────────────────────────────
 Стенд OpenCode для студентов

   Адрес    ${url}
   Файлы    ${url}/files/
   Логин    opencode
   Пароль   ${password}  (он же для страницы /files/)

 Раздайте студентам три строки выше. Больше им ничего не нужно:
 браузер, адрес, вход.

 Статус:   docker compose ps
 Логи:     docker compose logs -f sandbox
 Модели:   docker compose logs egress | grep -i blocked
 Сброс:    scripts/90-reset.sh
────────────────────────────────────────────────────────────────────
EOF
