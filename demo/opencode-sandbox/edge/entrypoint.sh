#!/bin/sh
# Готовим конфиг nginx перед стартом образа nginx:1.27-alpine.
#
# Скрипт лежит в /docker-entrypoint.d/, поэтому официальный entrypoint
# выполнит его до запуска nginx.
set -eu

CERT_DIR="/etc/nginx/certs"
SITE_SRC="/etc/nginx/templates/site.http.conf"

# Штатный default.conf нам не нужен: он перехватывает запросы.
rm -f /etc/nginx/conf.d/default.conf

if [ "${ENABLE_TLS:-false}" = "true" ]; then
  SITE_SRC="/etc/nginx/templates/site.tls.conf"

  if [ ! -s "${CERT_DIR}/fullchain.pem" ] || [ ! -s "${CERT_DIR}/privkey.pem" ]; then
    # Каталог с сертификатами смонтирован read-only, поэтому генерируем
    # во внутренний каталог. Для внутреннего стенда self-signed достаточно:
    # браузер один раз покажет предупреждение.
    echo "[edge] сертификат не найден, генерирую self-signed"
    mkdir -p /etc/nginx/selfsigned
    openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
      -keyout /etc/nginx/selfsigned/privkey.pem \
      -out    /etc/nginx/selfsigned/fullchain.pem \
      -subj "/CN=opencode-sandbox" >/dev/null 2>&1
    CERT_DIR="/etc/nginx/selfsigned"
  fi
fi

envsubst '${EDGE_HTTPS_PORT} ${CERT_DIR}' < "${SITE_SRC}" > /etc/nginx/conf.d/site.conf

echo "[edge] TLS=${ENABLE_TLS:-false} certs=${CERT_DIR}"
nginx -t
