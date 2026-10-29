#!/usr/bin/env bash
# Проверяем, что сервер вообще готов к установке стенда.
# Скрипт ничего не меняет — только смотрит и рассказывает.
set -euo pipefail
cd "$(dirname "$0")/.."

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
hdr()  { printf '\n\033[1m%s\033[0m\n' "$*"; }

problems=0

hdr "1. Система"
if [ -r /etc/os-release ]; then
  . /etc/os-release
  ok "${PRETTY_NAME:-unknown}"
  case "${ID:-}" in
    ubuntu|debian) ;;
    *) warn "стенд писался под Ubuntu/Debian, здесь ${ID}. Возможны отличия в пакетах." ;;
  esac
else
  warn "не удалось определить дистрибутив"
fi
ok "kernel $(uname -r)"
ok "cpu: $(nproc) ядер, ram: $(free -h | awk '/^Mem:/{print $2}')"

hdr "2. Учётная запись"
if [ "$(id -u)" -eq 0 ]; then
  ok "запущено от root"
else
  if sudo -n true 2>/dev/null; then
    ok "есть passwordless sudo"
  else
    warn "нет root и нет passwordless sudo — установка gVisor потребует пароль"
  fi
fi

hdr "3. Docker"
if ! command -v docker >/dev/null 2>&1; then
  bad "docker не установлен. Поставьте: curl -fsSL https://get.docker.com | sh"
  exit 1
fi
ok "$(docker --version)"
if docker compose version >/dev/null 2>&1; then
  ok "compose: $(docker compose version --short 2>/dev/null || echo v2)"
else
  bad "нет плагина docker compose (v2). Установите docker-compose-plugin."
  problems=$((problems+1))
fi
if docker info >/dev/null 2>&1; then
  ok "демон docker доступен"
else
  bad "демон docker недоступен для текущего пользователя"
  problems=$((problems+1))
fi

hdr "4. Изоляция (gVisor)"
if docker info >/dev/null 2>&1; then
  if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q 'runsc'; then
    ok "runtime runsc зарегистрирован — gVisor готов"
  else
    warn "runsc не найден. Запустите scripts/10-install-gvisor.sh"
    warn "или поставьте SANDBOX_RUNTIME=runc в .env (слабее)"
  fi
fi
if [ -e /proc/self/ns/user ]; then ok "user namespaces доступны"; fi

hdr "5. Конфигурация стенда"
if [ -f .env ]; then
  ok ".env есть"
  if grep -q '^SANDBOX_PASSWORD=please-change-me' .env 2>/dev/null; then
    bad "в .env остался пароль-заглушка. Поменяйте SANDBOX_PASSWORD."
    problems=$((problems+1))
  else
    ok "пароль в .env изменён"
  fi

  # Самая частая причина «студенты не могут писать в /work»: uid в контейнере
  # не совпадает с владельцем bind-mount'а на хосте.
  want_uid=$(grep -E '^SANDBOX_UID=' .env | cut -d= -f2 || echo 1000)
  want_gid=$(grep -E '^SANDBOX_GID=' .env | cut -d= -f2 || echo 1000)
  want_uid=${want_uid:-1000}; want_gid=${want_gid:-1000}
  have=$(stat -c '%u:%g' workspace 2>/dev/null || echo "unknown")
  if [ "${have}" = "${want_uid}:${want_gid}" ]; then
    ok "владелец workspace/ = ${have}, совпадает с SANDBOX_UID/GID"
  else
    bad "workspace/ принадлежит ${have}, а SANDBOX_UID/GID = ${want_uid}:${want_gid}"
    echo "     Исправьте одно из двух:"
    echo "       chown -R ${want_uid}:${want_gid} workspace"
    echo "       либо поставьте в .env SANDBOX_UID=${have%%:*} SANDBOX_GID=${have##*:}"
  fi
else
  warn ".env нет — создайте из .env.example"
fi

hdr "6. Порты"
for port in $( [ -f .env ] && grep -E '^(EDGE_PORT|EDGE_HTTPS_PORT)=' .env | cut -d= -f2 ); do
  if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}$"; then
    warn "порт ${port} уже занят: $(ss -ltnp 2>/dev/null | grep -E "[:.]${port}$" | head -1)"
  else
    ok "порт ${port} свободен"
  fi
done

hdr "7. Датасеты для студентов"
if [ -d ../../datasets ]; then
  ok "нашли ../../datasets ($(find ../../datasets -type f | wc -l) файлов)"
else
  warn "../../datasets не найден — скопируйте данные скриптом 20-sync-workspace.sh с другого пути"
fi

hdr "Итог"
if [ "$problems" -eq 0 ]; then
  ok "критичных блокеров нет"
  echo
  echo "Дальше:"
  echo "  1) cp .env.example .env && \$EDITOR .env     # сменить пароль"
  echo "  2) sudo scripts/10-install-gvisor.sh        # если runsc не найден"
  echo "  3) scripts/20-sync-workspace.sh             # данные и шаблоны"
  echo "  4) scripts/30-up.sh                         # поднять стенд"
  echo "  5) scripts/50-verify-isolation.sh           # проверить защиту"
else
  bad "блокеров: ${problems} — см. выше"
  exit 1
fi
