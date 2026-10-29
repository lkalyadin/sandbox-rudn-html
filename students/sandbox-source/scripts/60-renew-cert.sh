#!/usr/bin/env bash
# Продление общего TLS-сертификата Let's Encrypt на IP стенда и раскладка его
# в edge (nginx, :443) и Caddy (:4601).
#
# Почему так: Let's Encrypt выдаёт сертификаты на IP только в профиле
# shortlived (~6 дней) и только при HTTP-01 проверке на порту 80. Порт 80
# держит edge, поэтому проверку обслуживает его webroot (edge/acme), а
# сертификатом пользуются оба стенда — продление в одном месте.
#
# Запускается systemd-таймером opencode-student-cert.timer (пользователь
# deployagent). certbot сам решает по ARI, пора ли продлевать, поэтому
# ежедневный запуск не расходует лимиты Let's Encrypt.
set -euo pipefail
cd "$(dirname "$0")/.."

# Имя сертификата = публичный хост стенда из .env (LE кладёт его в
# /etc/letsencrypt/live/<IP>). Раньше здесь был зашит IP старого стенда.
if [ -f .env ]; then
  # shellcheck disable=SC1091
  set -a; . ./.env; set +a
fi
PUBLIC_HOST="$(printf '%s' "${PUBLIC_URL:-}" | sed -E 's#^[a-z]+://##; s#/.*$##; s#:[0-9]+$##')"
CERT_NAME="${CERT_NAME:-${PUBLIC_HOST}}"
[ -n "$CERT_NAME" ] || { echo "!! не удалось определить имя сертификата (PUBLIC_URL пуст)" >&2; exit 1; }
LE_DIR="$PWD/edge/letsencrypt"
ACME_DIR="$PWD/edge/acme"
CERT_DIR="$PWD/edge/certs"
IMAGE="${CERTBOT_IMAGE:-certbot/certbot}"
EDGE_CT="${EDGE_CONTAINER:-opencode-student-edge}"

mkdir -p "$ACME_DIR" "$CERT_DIR"

echo "==> certbot renew"
docker run --rm \
  -v "$LE_DIR:/etc/letsencrypt" \
  -v "$ACME_DIR:/var/www/.well-known/acme-challenge" \
  "$IMAGE" renew --webroot -w /var/www --quiet

echo "==> раскладываю сертификат в edge/certs"
docker run --rm \
  -v "$LE_DIR:/etc/letsencrypt" \
  -v "$CERT_DIR:/out" \
  --entrypoint sh "$IMAGE" -c "
    set -e
    cp -L /etc/letsencrypt/live/${CERT_NAME}/fullchain.pem /out/fullchain.pem
    cp -L /etc/letsencrypt/live/${CERT_NAME}/privkey.pem  /out/privkey.pem
    chmod 644 /out/fullchain.pem
    chmod 600 /out/privkey.pem
    chown 1001:1001 /out/fullchain.pem /out/privkey.pem
  "

echo "==> перезагружаю edge и caddy"
docker exec "$EDGE_CT" nginx -s reload
# Caddy есть только на хосте разработки (стенд :4601); на VPS его нет.
systemctl --user reload-or-restart caddy 2>/dev/null || true

echo "==> готово, сертификат действует до: $(openssl x509 -noout -enddate -in "$CERT_DIR/fullchain.pem" | cut -d= -f2)"
