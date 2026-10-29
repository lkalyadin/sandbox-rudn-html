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
# 644: файл читает воркер nginx (uid nginx внутри контейнера), а не root.
chmod 644 edge/htpasswd
echo "==> edge/htpasswd обновлён (логин opencode, пароль как у OpenCode)"

# ─── Сертификат для edge ─────────────────────────────────────────────────────
# В образе nginx:alpine нет openssl, поэтому сертификат готовим на хосте и
# монтируем каталог в контейнер.
#
# Боевой путь — общий сертификат Let's Encrypt на IP (scripts/60-renew-cert.sh).
# Если он уже лежит в edge/certs, НЕ трогаем его. Самоподписанный генерируем
# только как fallback: когда файлов нет или когда текущий самоподписанный истекает.
CERT_DIR="${TLS_CERT_DIR:-./edge/certs}"
mkdir -p "${CERT_DIR}"
need_selfsigned=false
if [ ! -s "${CERT_DIR}/fullchain.pem" ] || [ ! -s "${CERT_DIR}/privkey.pem" ]; then
  need_selfsigned=true
else
  issuer="$(openssl x509 -noout -issuer  -in "${CERT_DIR}/fullchain.pem" 2>/dev/null || true)"
  subject="$(openssl x509 -noout -subject -in "${CERT_DIR}/fullchain.pem" 2>/dev/null || true)"
  if [ -n "${issuer}" ] && [ "${issuer}" = "${subject}" ] \
     && ! openssl x509 -checkend 604800 -noout -in "${CERT_DIR}/fullchain.pem" >/dev/null 2>&1; then
    need_selfsigned=true
  fi
fi
if [ "${need_selfsigned}" = "true" ]; then
  public_host="$(printf '%s' "${PUBLIC_URL:-}" | sed -E 's#^[a-z]+://##; s#/.*$##; s#:[0-9]+$##')"
  [ -z "${public_host}" ] && public_host="$(hostname -I 2>/dev/null | awk '{print $1}')"
  if printf '%s' "${public_host}" | grep -Eq '^[0-9]+(\.[0-9]+){3}$'; then
    san="IP:${public_host},DNS:localhost"
  else
    san="DNS:${public_host},DNS:localhost"
  fi
  echo "==> Генерирую self-signed сертификат для ${public_host} (fallback без LE)"
  openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
    -keyout "${CERT_DIR}/privkey.pem" \
    -out    "${CERT_DIR}/fullchain.pem" \
    -subj "/CN=${public_host}" \
    -addext "subjectAltName=${san}" >/dev/null 2>&1
  chmod 600 "${CERT_DIR}/privkey.pem"
else
  echo "==> Использую существующий сертификат: $(openssl x509 -noout -issuer -in "${CERT_DIR}/fullchain.pem")"
fi

echo "==> Собираю образы"
docker compose build

echo "==> Поднимаю сервисы"
docker compose up -d

echo "==> Жду готовности (до 90 секунд)"
# Проверяем именно сквозной путь edge -> sandbox, а не редирект на порту 80:
# иначе 301 «зелёный» даже когда песочница не поднялась.
if [ "${ENABLE_TLS:-false}" = "true" ]; then
  probe_url="https://127.0.0.1:${EDGE_HTTPS_PORT:-443}/"
  probe_flags=(-k)
else
  probe_url="http://127.0.0.1:${EDGE_PORT:-80}/"
  probe_flags=()
fi
deadline=$(( $(date +%s) + 90 ))
ready=false
while [ "$(date +%s)" -lt "$deadline" ]; do
  if ! docker compose ps --status running --format '{{.Service}}' | grep -qx sandbox; then
    sleep 2
    continue
  fi
  code=$(curl -s "${probe_flags[@]}" -o /dev/null -w '%{http_code}' --max-time 5 "${probe_url}" || true)
  if printf '%s' "${code}" | grep -qE '^[23]'; then
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

# Дефолтный проект стенда: /work с именем "work" (после сброса БД имя теряется).
bash scripts/92-project-work.sh

echo
echo "==> Стенд поднят"
bash scripts/40-info.sh

echo
echo "Проверьте изоляцию: scripts/50-verify-isolation.sh"
