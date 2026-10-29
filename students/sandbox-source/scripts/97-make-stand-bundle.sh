#!/usr/bin/env bash
# Собирает «заготовку» стенда: готовые образы + скелет + .env с ключами.
#
# Что это даёт: поднять новый стенд на новом VPS можно за ~2 минуты
# (docker load + compose up), а не за 10 минут сборки. И не зависит от того,
# жив ли старый стенд.
#
# Запускать ТОЛЬКО пока на этой машине работает docker:
#   bash scripts/97-make-stand-bundle.sh
#
# Результат: /srv/opencode-student/bundles/stand-<метка>.tar.gz (~1.5 ГБ)
set -euo pipefail
cd "$(dirname "$0")/.."

BUNDLE_DIR="${BUNDLE_DIR:-$(cd .. && pwd)/bundles}"
STAMP="${STAMP:-$(date +%Y%m%d-%H%M)}"
NAME="stand-${STAMP}"

echo "==> Каталог заготовки: $BUNDLE_DIR/$NAME"
mkdir -p "$BUNDLE_DIR"
# ВАЖНО: рабочий каталог — на диске, а не в /tmp: /tmp здесь tmpfs в RAM
# (821 МБ), туда не влезает архив образов.
WORK="$BUNDLE_DIR/.work-$NAME"
rm -rf "$WORK"; mkdir -p "$WORK"
trap 'rm -rf "$WORK"' EXIT

echo "==> 1/4 Сохраняю образы"
IMAGES=$(docker images --format '{{.Repository}}:{{.Tag}}' \
  | grep -E '^(opencode-student-|opencode-upload-handler|nginx:1\.27-alpine|certbot/certbot|ghcr\.io/anomalyco/opencode)' \
  | sort -u | tr '\n' ' ')
[ -n "$IMAGES" ] || { echo "!! нет образов стенда — соберите стенд хотя бы раз"; exit 1; }
echo "    $(echo $IMAGES | tr ' ' '\n' | wc -l) образов"
# gzip -1: быстрее и достаточно; tar внутри и так сжимается словарём
docker save $IMAGES | gzip -1 > "$WORK/images.tar.gz"
ls -lh "$WORK/images.tar.gz"

echo "==> 2/4 Копирую скелет стенда (без .env, сертификатов и workspace)"
# -C на родителя: в архив кладём каталог sandbox целиком
tar czf "$WORK/skeleton.tar.gz" \
  -C "$(cd .. && pwd)" \
  --exclude='sandbox/workspace' \
  --exclude='sandbox/.env' \
  --exclude='sandbox/edge/certs' \
  --exclude='sandbox/edge/htpasswd' \
  --exclude='sandbox/edge/letsencrypt' \
  --exclude='sandbox/edge/acme' \
  --exclude='sandbox/*.log' \
  sandbox

echo "==> 3/4 Кладу .env (пароль стенда + ключи шлюза)"
cp .env "$WORK/env.template"
chmod 600 "$WORK/env.template"

PUBLIC_HOST="$(printf '%s' "$(sed -n 's/^PUBLIC_URL=//p' .env | head -1)" | sed -E 's#^[a-z]+://##; s#/.*$##')"
DS_DIR="${DATASETS_DIR:-$HOME/datasets}"
DS_N="$(ls "$DS_DIR"/*.csv 2>/dev/null | wc -l | tr -d ' ')"
DS_SIZE="$(du -sh "$DS_DIR" 2>/dev/null | cut -f1)"; DS_SIZE="${DS_SIZE:-?}"
SRC_DIR="$(cd .. && pwd)"

cat > "$WORK/README.txt" <<EOF
Заготовка стенда OpenCode (студенческий, изолированный).
Собрана: $(date -u '+%Y-%m-%d %H:%M UTC')
Источник: ${SRC_DIR}/sandbox (стенд ${PUBLIC_HOST})

Как поднять новый стенд из этой заготовки:
  1) На новом VPS (root): docker + compose + gVisor + пользователь deployagent
     с ключом агента — см. DEPLOY_STAND.md, §1
  2) Скопировать сюда этот .tar.gz и распаковать: tar xzf ${NAME}.tar.gz
  3) Положить датасеты в ${DS_DIR} (${DS_N} CSV, ${DS_SIZE})
  4) cd ${NAME} && bash 98-deploy-from-bundle.sh <НОВЫЙ_IP>
     (распакует скелет, docker load, .env под новый IP, htpasswd + self-signed
      сертификат, compose up, TLS Let's Encrypt, датасеты, каталог,
      user-таймеры deployagent, самопроверка)
  5) Под root на новом VPS: bash /srv/opencode/sandbox/scripts/95-root-setup.sh
     (квота 30 ГБ на workspace + ночная очистка в 03:30 + enable-linger)
  6) Проверка: cd /srv/opencode/sandbox && bash scripts/31-up-fast.sh --check

Внутри:
  images.tar.gz   — собранные образы (docker load)
  skeleton.tar.gz — каркас стенда (compose, скрипты, конфиг, навык,
                    Hallmark в skills/hallmark, хелперы в tools/)
  env.template    — .env: пароль стенда, ключ AI-шлюза (СЕКРЕТ, права 600)
  <файл>.sha256   — контрольная сумма архива (рядом с .tar.gz)

Модели: только бесплатные — пул opencode (8) + vercel-free через прокси-шлюз (3).
EOF

echo "==> 4/4 Складываю заготовку"
cp scripts/98-deploy-from-bundle.sh "$WORK/"
tar czf "$BUNDLE_DIR/${NAME}.tar.gz" -C "$WORK" \
  --transform 's,^\./,'"$NAME"'/,' .

chmod 600 "$BUNDLE_DIR/${NAME}.tar.gz"
ls -lh "$BUNDLE_DIR/${NAME}.tar.gz"
(cd "$BUNDLE_DIR" && sha256sum "${NAME}.tar.gz" > "${NAME}.tar.gz.sha256") && echo "sha256: $BUNDLE_DIR/${NAME}.tar.gz.sha256"
echo
echo "==> Готово: $BUNDLE_DIR/${NAME}.tar.gz"
