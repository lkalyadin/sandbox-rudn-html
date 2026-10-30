#!/usr/bin/env bash
# Поднимает стенд из УЖЕ СКОПИРОВАННОГО скелета, без заготовки-бандла.
#
# Отличие от 98-deploy-from-bundle.sh: там скелет и образы берутся из
# stand-*.tar.gz, здесь скелет уже лежит в /srv/opencode/sandbox, а образы
# собираются на месте (docker compose build, ~10 минут на 2 vCPU, ~4 на 4 vCPU).
#
# Запуск на новом VPS от deployagent:
#   cd /srv/opencode/sandbox && bash scripts/99-up-new-stand.sh <IP>
#
# Что делает:
#   1. проверяет, что пути стенда указывают на этот сервер (а не на хост разработки)
#   2. права на рабочую папку (uid образа 1000, а не uid deployagent)
#   3. htpasswd для /files/ + self-signed сертификат как fallback
#   4. собирает и поднимает контейнеры
#   5. выпускает TLS Let's Encrypt на голый IP
#   6. датасеты, каталог, проект work, user-таймеры
#   7. самопроверка 31-up-fast.sh --check
#
# Требует: docker, docker compose, openssl, curl. Root не нужен (квота на диск —
# отдельно, scripts/95-root-setup.sh).
set -euo pipefail
cd "$(dirname "$0")/.."

IP="${1:?укажите IP стенда: bash scripts/99-up-new-stand.sh 45.159.173.129}"
[ -f .env ] || { echo "!! нет .env — скопируйте .env.example и заполните" >&2; exit 1; }
set -a; . ./.env; set +a

IMAGE_UID="${SANDBOX_UID:-1000}"
UID_GID="$(id -u):$(id -g)"

echo "==> Стенд: https://$IP  (каталог $PWD)"

# ─── 1. Пути под этот сервер ─────────────────────────────────────────────────
# Если скелет скопирован с хоста разработки, в compose остались старые пути:
# Docker молча создаст пустой каталог, и /work окажется нерабочим.
if grep -q "/srv/opencode-student/workspace" docker-compose.yml; then
  echo "==> Правлю пути /srv/opencode-student → /srv/opencode"
  grep -rl "/srv/opencode-student/workspace" scripts docker-compose.yml edge egress skills 2>/dev/null | \
    xargs -r sed -i "s#/srv/opencode-student/workspace#/srv/opencode/workspace#g"
fi
if grep -q "/srv/opencode-student/workspace" docker-compose.yml; then
  echo "!! в docker-compose.yml всё ещё /srv/opencode-student/workspace" >&2
  exit 1
fi
mkdir -p ../workspace

# ─── 2. Права на рабочую папку ───────────────────────────────────────────────
# Владелец должен быть uid песочницы из образа (1000), иначе агент не запишет /work.
docker run --rm -v "$PWD/..:/srv/opencode" nginx:1.27-alpine sh -c \
  "chown -R ${IMAGE_UID}:${IMAGE_UID} /srv/opencode/workspace"

# ─── 3. Пароль и fallback-сертификат ─────────────────────────────────────────
# edge монтирует ./edge/htpasswd как файл: если файла нет, Docker создаст КАТАЛОГ,
# nginx упадёт, ACME не отдастся и Let's Encrypt не выпустит сертификат.
if [ -d edge/htpasswd ]; then
  docker run --rm -v "$PWD/edge:/e" nginx:1.27-alpine rmdir /e/htpasswd || true
fi
mkdir -p edge/acme edge/letsencrypt edge/certs
printf 'opencode:%s\n' "$(openssl passwd -apr1 -stdin <<<"${SANDBOX_PASSWORD}")" > edge/htpasswd
chmod 644 edge/htpasswd

openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
  -keyout edge/certs/privkey.pem -out edge/certs/fullchain.pem \
  -subj "/CN=$IP" -addext "subjectAltName=IP:$IP,DNS:localhost" >/dev/null 2>&1
chmod 600 edge/certs/privkey.pem; chmod 644 edge/certs/fullchain.pem

# ─── 4. Сборка и запуск ──────────────────────────────────────────────────────
echo "==> Собираю образы (это самая долгая часть)"
docker compose build
echo "==> Поднимаю контейнеры"
docker compose up -d
sleep 8

# ─── 5. TLS: Let's Encrypt на голый IP ───────────────────────────────────────
# Короткоживущий профиль (~6 дней), продление — user-таймер cert.timer (04:17).
echo "==> TLS: Let's Encrypt на $IP"
docker run --rm \
  -v "$PWD/edge/letsencrypt:/etc/letsencrypt" \
  -v "$PWD/edge/acme:/var/www/.well-known/acme-challenge" \
  certbot/certbot certonly --webroot -w /var/www \
  --ip-address "$IP" --preferred-profile shortlived \
  --agree-tos --register-unsafely-without-email --keep-until-expiring 2>&1 | tail -3 || \
  echo "!! Let's Encrypt не выпустил сертификат — остаётся self-signed (браузер будет ругаться)"
# certbot пишет от root: live/ и archive/ получают 700, и deployagent их не видит.
# Без этого chown проверка -s ниже молча проваливается (так было 30.10.2026:
# LE выпустился, а стенд остался на self-signed), и продление таймером падает
# на правах.
docker run --rm -v "$PWD/edge:/e" nginx:1.27-alpine sh -c \
  "chown -R ${UID_GID} /e/letsencrypt /e/certs" 2>/dev/null || true

if [ -s "edge/letsencrypt/live/$IP/fullchain.pem" ]; then
  docker run --rm -v "$PWD/edge/letsencrypt:/etc/letsencrypt" -v "$PWD/edge/certs:/out" \
    --entrypoint sh certbot/certbot -c "
      cp -L /etc/letsencrypt/live/$IP/fullchain.pem /out/fullchain.pem
      cp -L /etc/letsencrypt/live/$IP/privkey.pem  /out/privkey.pem
      chmod 644 /out/fullchain.pem; chmod 600 /out/privkey.pem
      chown ${UID_GID} /out/fullchain.pem /out/privkey.pem"
  echo "    сертификат Let's Encrypt применён: $(openssl x509 -noout -issuer -in edge/certs/fullchain.pem)"
else
  echo "!! в edge/letsencrypt нет сертификата для $IP — остаётся self-signed"
fi
docker exec opencode-student-edge nginx -s reload || true

# ─── 6. Датасеты, каталог, проект, таймеры ───────────────────────────────────
echo "==> Датасеты и каталог"
if [ -d "$HOME/datasets" ]; then
  bash scripts/20-sync-workspace.sh "$HOME/datasets" >/dev/null 2>&1 || true
else
  echo "!! нет $HOME/datasets — студенты останутся без данных"
fi
bash scripts/70-build-catalog.sh >/dev/null 2>&1 || true
bash scripts/92-project-work.sh >/dev/null 2>&1 || true
bash scripts/96-install-user-timers.sh 2>&1 | tail -6

# ─── 7. Самопроверка ────────────────────────────────────────────────────────
echo
echo "==> Проверка"
bash scripts/31-up-fast.sh --check 2>&1 | tail -25 || true
echo
echo "Осталось под root на этом VPS:"
echo "  bash $PWD/scripts/95-root-setup.sh    # квота на диск + ночная очистка + linger"
echo
echo "Адрес стенда: https://$IP/   (логин opencode, пароль как в .env)"
