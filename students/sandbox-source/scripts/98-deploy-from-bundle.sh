#!/usr/bin/env bash
# Поднимает новый стенд OpenCode из заготовки (bundle), без сборки образов.
#
# Запуск на новом VPS (после распаковки заготовки):
#   cd <каталог заготовки> && bash 98-deploy-from-bundle.sh <НОВЫЙ_IP>
#
# Что делает:
#   1. распаковывает скелет в /srv/opencode/sandbox
#   2. docker load из images.tar.gz (1–3 минуты)
#   3. готовит .env под новый IP
#   4. правит пути стенда (workspace, датасеты, таймеры)
#   5. поднимает контейнеры (без build)
#   6. выпускает TLS Let's Encrypt на голый IP
#   7. возвращает датасеты и собирает каталог
#
# Требует: docker, docker compose, openssl; root не нужен (нужен для квоты —
# см. scripts/95-root-setup.sh).
set -euo pipefail

IP="${1:?укажите новый IP: bash 98-deploy-from-bundle.sh 92.246.128.129}"
BUNDLE_DIR="$(cd "$(dirname "$0")" && pwd)"
DEST="${DEST:-/srv/opencode}"
SANDBOX_DIR="$DEST/sandbox"
UID_GID="$(id -u):$(id -g)"

echo "==> Новый стенд: $IP → $SANDBOX_DIR (uid песочницы $UID_GID)"

echo "==> 1/7 Распаковываю скелет"
mkdir -p "$DEST"
tar xzf "$BUNDLE_DIR/skeleton.tar.gz" -C "$DEST"
[ -d "$SANDBOX_DIR" ] || { echo "!! не найден $SANDBOX_DIR"; exit 1; }

echo "==> 2/7 Загружаю образы"
gzip -dc "$BUNDLE_DIR/images.tar.gz" | docker load

echo "==> 3/7 Готовлю .env"
cp "$BUNDLE_DIR/env.template" "$SANDBOX_DIR/.env"
chmod 600 "$SANDBOX_DIR/.env"
sed -i "s#^PUBLIC_URL=.*#PUBLIC_URL=https://$IP#; s#^ENABLE_TLS=.*#ENABLE_TLS=true#" "$SANDBOX_DIR/.env"
# uid песочницы = uid пользователя, зашитый в готовый образ (1000), а НЕ uid
# deployagent (обычно 1001). В образе /home/sandbox и /opt/viz принадлежат 1000:
# если поставить uid deployagent, песочница падает с «permission denied» на
# /home/sandbox и не может писать в /work.
IMAGE_UID=1000
sed -i "s/^SANDBOX_UID=.*/SANDBOX_UID=${IMAGE_UID}/; s/^SANDBOX_GID=.*/SANDBOX_GID=${IMAGE_UID}/" "$SANDBOX_DIR/.env"

# cpu/память — под размер ЭТОГО VPS: на 2 vCPU/3.4 ГБ жёсткие 3.5 CPU/6 ГБ
# не дают контейнеру даже стартовать («range of CPUs is from 0.01 to 2.00»).
NCPU=$(nproc)
MEM_MB=$(awk "/MemTotal/{printf \"%d\", \$2/1024}" /proc/meminfo)
MEM_LIM=$(( MEM_MB * 60 / 100 )); [ "$MEM_LIM" -gt 6144 ] && MEM_LIM=6144
sed -i "s/^SANDBOX_CPUS=.*/SANDBOX_CPUS=${NCPU}/; s/^SANDBOX_MEMORY=.*/SANDBOX_MEMORY=${MEM_LIM}m/" "$SANDBOX_DIR/.env"
echo "    ресурсы: ${NCPU} CPU, ${MEM_LIM} МБ RAM (хост: $(nproc) CPU / ${MEM_MB} МБ)"

echo "==> 4/7 Правлю пути стенда под этот сервер"
cd "$SANDBOX_DIR"
grep -rl "opencode-student/workspace\|projects/datasets" scripts docker-compose.yml edge egress skills 2>/dev/null | \
  xargs -r sed -i "s#/srv/opencode-student/workspace#$DEST/workspace#g; s#/home/deployagent/projects/datasets#/home/deployagent/datasets#g"
# upload-handler пишет в workspace от того же uid, что и песочница
sed -i "s#user: \"1000:1000\"#user: \"\${SANDBOX_UID:-${IMAGE_UID}}:\${SANDBOX_GID:-${IMAGE_UID}}\"#" docker-compose.yml
mkdir -p "$DEST/workspace"

# Проверка: в compose не должно остаться путей хоста разработки. Иначе Docker
# молча создаст пустой каталог, и /work окажется не рабочим каталогом студентов.
if grep -q "/srv/opencode-student/workspace" docker-compose.yml; then
  echo "!! В docker-compose.yml остались пути /srv/opencode-student/workspace" >&2
  echo "   (обычно это значит, что compose перезаписали копией с хоста разработки)" >&2
  exit 1
fi

echo "==> 4b/7 Права: рабочая папка (uid образа), htpasswd, fallback-сертификат"
# Рабочая папка должна принадлежать uid песочницы, иначе агент не запишет /work.
docker run --rm -v "$DEST:/srv/opencode" nginx:1.27-alpine sh -c \
  "chown -R ${IMAGE_UID}:${IMAGE_UID} /srv/opencode/workspace"

# edge монтирует ./edge/htpasswd как файл: если файла нет, Docker создаст
# КАТАЛОГ, nginx упадёт, ACME не отдастся и Let's Encrypt не выпустит сертификат.
set -a; . "$SANDBOX_DIR/.env"; set +a
if [ -d edge/htpasswd ]; then
  docker run --rm -v "$PWD/edge:/e" nginx:1.27-alpine rmdir /e/htpasswd || true
fi
mkdir -p edge/acme edge/letsencrypt edge/certs
printf 'opencode:%s\n' "$(openssl passwd -apr1 -stdin <<<"${SANDBOX_PASSWORD}")" > edge/htpasswd
chmod 644 edge/htpasswd

# Без сертификата edge не стартует: генерируем self-signed, LE заменит его ниже.
openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
  -keyout edge/certs/privkey.pem -out edge/certs/fullchain.pem \
  -subj "/CN=$IP" -addext "subjectAltName=IP:$IP,DNS:localhost" >/dev/null 2>&1
chmod 600 edge/certs/privkey.pem; chmod 644 edge/certs/fullchain.pem

echo "==> 5/7 Поднимаю контейнеры (без сборки)"
docker compose up -d
sleep 8

echo "==> 6/7 TLS: Let's Encrypt на голый IP"
mkdir -p edge/letsencrypt edge/acme edge/certs
docker run --rm \
  -v "$PWD/edge/letsencrypt:/etc/letsencrypt" \
  -v "$PWD/edge/acme:/var/www/.well-known/acme-challenge" \
  certbot/certbot certonly --webroot -w /var/www \
  --ip-address "$IP" --preferred-profile shortlived \
  --agree-tos --register-unsafely-without-email --keep-until-expiring 2>&1 | tail -3
docker run --rm -v "$PWD/edge/letsencrypt:/etc/letsencrypt" -v "$PWD/edge/certs:/out" \
  --entrypoint sh certbot/certbot -c "
    cp -L /etc/letsencrypt/live/$IP/fullchain.pem /out/fullchain.pem
    cp -L /etc/letsencrypt/live/$IP/privkey.pem  /out/privkey.pem
    chmod 644 /out/fullchain.pem; chmod 600 /out/privkey.pem
    chown ${UID_GID} /out/fullchain.pem /out/privkey.pem"
# letsencrypt/certs пишет root в контейнере, а renew запускает deployagent:
# без этого продление сертификата упадёт на правах.
docker run --rm -v "$PWD/edge:/e" nginx:1.27-alpine sh -c \
  "chown -R ${UID_GID} /e/letsencrypt /e/certs"
docker exec opencode-student-edge nginx -s reload || true

echo "==> 7/7 Датасеты и каталог"
if [ -d /home/deployagent/datasets ]; then
  bash scripts/20-sync-workspace.sh /home/deployagent/datasets >/dev/null 2>&1 || true
fi
bash scripts/70-build-catalog.sh >/dev/null 2>&1 || true
bash scripts/92-project-work.sh >/dev/null 2>&1 || true
# User-таймеры deployagent: restore 03:40, cert 04:17, catalog вс 05:20.
# Без них после ночной очистки не вернутся датасеты и не продлится сертификат.
bash scripts/96-install-user-timers.sh 2>&1 | tail -6

echo
echo "==> Готово. Проверка:"
bash scripts/31-up-fast.sh --check 2>&1 | tail -20
echo
echo "Осталось под root на этом VPS:"
echo "  bash $SANDBOX_DIR/scripts/95-root-setup.sh    # квота на диск + ночная очистка"
echo
echo "Адрес стенда: https://$IP/   (логин opencode, пароль как в .env)"
