#!/usr/bin/env bash
# ROOT-скрипт для стенда: таймеры + (опционально) квота на рабочую папку.
#
# ЗАПУСКАТЬ ПОД ROOT:
#   sudo bash /srv/opencode/sandbox/scripts/95-root-setup.sh              # полный: таймеры + квота
#   sudo bash /srv/opencode/sandbox/scripts/95-root-setup.sh --timers-only # только таймеры, БЕЗ остановки стенда
#
# Что делает (полный режим):
#   1. Образ ext4 30 ГБ → монтируется в /srv/opencode/workspace (квота на
#      рабочую папку студентов; без неё один студент может забить диск).
#   2. Автоподключение через /etc/fstab (после ребута).
#   3. Root-таймер ночной очистки в 03:30 (стирает содержимое workspace).
#   4. loginctl enable-linger для deployagent — чтобы user-таймеры
#      (восстановление датасетов 03:40, продление сертификата 04:17,
#      каталог 05:20) работали без залогиненной сессии.
#
# ВАЖНО: шаги 1–2 требуют остановить контейнеры (bind-mount нельзя накрыть
# работающим контейнером — он продолжит писать в старый каталог). Поэтому
# есть режим --timers-only: только шаги 3–4, без остановки стенда.
set -euo pipefail

TIMERS_ONLY=false
[ "${1:-}" = "--timers-only" ] && TIMERS_ONLY=true

SANDBOX_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE="${WORKSPACE:-$(cd "$(dirname "$0")/../.." && pwd)/workspace}"
IMG="$(dirname "$WORKSPACE")/workspace.img"
SIZE=30G
# uid/gid рабочей папки = uid песочницы из .env стенда (в образе это 1000,
# а не uid пользователя deployagent — папку пишет агент внутри контейнера).
ENV_FILE="$(cd "$(dirname "$0")/.." && pwd)/.env"
sandbox_uid=""; sandbox_gid=""
if [ -f "$ENV_FILE" ]; then
  sandbox_uid="$(sed -n 's/^SANDBOX_UID=//p' "$ENV_FILE" | head -1)"
  sandbox_gid="$(sed -n 's/^SANDBOX_GID=//p' "$ENV_FILE" | head -1)"
fi
UID_GID="${sandbox_uid:-1000}:${sandbox_gid:-1000}"

if [ "$TIMERS_ONLY" != "true" ]; then
  echo "==> Останавливаю контейнеры (нужно для монтирования поверх папки)"
  cd /srv/opencode/sandbox
  docker compose stop >/dev/null 2>&1 || true

  echo "==> Создаю образ-квоту ${IMG} (${SIZE})"
  if [ ! -f "$IMG" ]; then
    truncate -s "$SIZE" "$IMG"
    mkfs.ext4 -q -F "$IMG"
  fi

  echo "==> Монтирую в ${WORKSPACE}"
  mkdir -p "$WORKSPACE"
  mountpoint -q "$WORKSPACE" || mount -o loop "$IMG" "$WORKSPACE"

  if ! grep -q "$IMG $WORKSPACE" /etc/fstab; then
    echo "$IMG $WORKSPACE ext4 loop,defaults,nofail 0 2" >> /etc/fstab
  fi

  echo "==> Права: ${UID_GID}"
  chown -R "$UID_GID" "$WORKSPACE"
  chmod 755 "$WORKSPACE"
fi

echo "==> Ставлю root-таймер ночной очистки (03:30)"
cat > /etc/systemd/system/opencode-student-cleanup.service <<'EOF'
[Unit]
Description=Ночная очистка рабочей папки студенческого стенда OpenCode

[Service]
Type=oneshot
ExecStart=/usr/bin/find /srv/opencode/workspace -mindepth 1 ! -name lost+found -delete
EOF

cat > /etc/systemd/system/opencode-student-cleanup.timer <<'EOF'
[Unit]
Description=Запуск очистки студенческого стенда ночью

[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true
Unit=opencode-student-cleanup.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now opencode-student-cleanup.timer

echo "==> enable-linger для deployagent (чтобы user-таймеры жили без сессии)"
loginctl enable-linger deployagent || true

if [ "$TIMERS_ONLY" != "true" ]; then
  echo "==> Поднимаю контейнеры обратно"
  cd "$SANDBOX_DIR"
  docker compose up -d
  sleep 5
  # Датасеты: после монтирования образа рабочая папка пустая, их надо вернуть.
  if ! bash scripts/20-sync-workspace.sh /home/deployagent/datasets >/dev/null; then
    echo "!! Датасеты не развернулись. Запустите вручную:" >&2
    echo "   cd $SANDBOX_DIR && bash scripts/20-sync-workspace.sh /home/deployagent/datasets" >&2
  fi
fi

echo
echo "==> Готово. Проверка:"
df -h /srv/opencode/workspace | tail -1
systemctl list-timers --all | grep opencode-student || true
loginctl show-user deployagent | grep -i linger
