#!/usr/bin/env bash
# Поднимает стенд целиком.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "!! Нет .env. Выполните: cp .env.example .env && \$EDITOR .env" >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a; . ./.env; set +a

EDGE_PORT="${EDGE_PORT:-80}"

# ─── Пароль на путь /files/ (скачивание результатов) ─────────────────────────
# Тот же SANDBOX_PASSWORD, что и у OpenCode, чтобы студент помнил один пароль.
# Хэш apr1 — единственный формат, который понимает nginx без сторонних утилит.
: "${SANDBOX_PASSWORD:?SANDBOX_PASSWORD не задан в .env}"
if ! command -v openssl >/dev/null 2>&1; then
  echo "!! openssl не найден — не смогу сделать пароль для /files/." >&2
  echo "   Поставьте openssl (apt-get install -y openssl) и запустите снова." >&2
  exit 1
fi
printf 'opencode:%s\n' "$(openssl passwd -apr1 -stdin <<<"${SANDBOX_PASSWORD}")" > edge/htpasswd
chmod 600 edge/htpasswd
echo "==> edge/htpasswd обновлён (логин opencode, пароль как у OpenCode)"

echo "==> Собираю образы"
docker compose build

echo "==> Поднимаю сервисы"
docker compose up -d

echo "==> Жду готовности (до 90 секунд)"
deadline=$(( $(date +%s) + 90 ))
ready=false
while [ "$(date +%s)" -lt "$deadline" ]; do
  if ! docker compose ps --status running --format '{{.Service}}' | grep -qx sandbox; then
    sleep 2
    continue
  fi
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:${EDGE_PORT}/" || true)
  if [ -n "${code}" ] && [ "${code}" != "000" ]; then
    ready=true
    break
  fi
  sleep 2
done

if [ "${ready}" != "true" ]; then
  echo
  echo "!! Стенд не ответил за 90 секунд. Смотрите логи:" >&2
  echo "   docker compose logs --tail=80 sandbox" >&2
  echo "   docker compose logs --tail=40 egress" >&2
  exit 1
fi

echo
echo "==> Стенд поднят"
bash scripts/40-info.sh

echo
echo "Проверьте изоляцию: scripts/50-verify-isolation.sh"
