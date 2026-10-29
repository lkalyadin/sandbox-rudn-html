#!/usr/bin/env bash
# Ставит user-таймеры стенда (от deployagent, root не нужен) и включает их.
#
#   restore  03:40        — возвращает датасеты после ночной очистки (root, 03:30)
#   cert     04:17        — certbot renew: сертификат LE на голый IP живёт ~6 суток
#   catalog  вс 05:20     — пересборка каталога датасетов (/opt/catalog)
#
# Пути берутся из расположения этого скрипта, поэтому он годится и для
# /srv/opencode/sandbox, и для старого /srv/opencode-student/sandbox.
#
# Запуск: bash scripts/96-install-user-timers.sh
set -euo pipefail
cd "$(dirname "$0")/.."
SANDBOX_DIR="$PWD"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"

write() { cat > "$UNIT_DIR/$1"; }

write opencode-student-restore.service <<EOF
[Unit]
Description=Восстановление датасетов и стартовых файлов студенческого стенда OpenCode
After=network-online.target

[Service]
Type=oneshot
# Ночная очистка (root, opencode-student-cleanup.timer) в 03:30 удаляет
# содержимое workspace целиком, включая data/. Этот таймер возвращает
# датасеты и стартовые файлы, чтобы утром студенты нашли данные.
ExecStart=${SANDBOX_DIR}/scripts/20-sync-workspace.sh
EOF

write opencode-student-restore.timer <<'EOF'
[Unit]
Description=Восстановление датасетов после ночной очистки стенда OpenCode

[Timer]
OnCalendar=*-*-* 03:40:00
Persistent=true
Unit=opencode-student-restore.service

[Install]
WantedBy=timers.target
EOF

write opencode-student-cert.service <<EOF
[Unit]
Description=Продление TLS-сертификата студенческого стенда OpenCode
After=network-online.target

[Service]
Type=oneshot
ExecStart=${SANDBOX_DIR}/scripts/60-renew-cert.sh
EOF

write opencode-student-cert.timer <<'EOF'
[Unit]
Description=Ежедневная проверка продления TLS-сертификата студенческого стенда

[Timer]
OnCalendar=*-*-* 04:17:00
Persistent=true
RandomizedDelaySec=600

[Install]
WantedBy=timers.target
EOF

write opencode-student-catalog.service <<EOF
[Unit]
Description=Пересборка каталога учебных датасетов (метаинформация GitHub)
After=network-online.target

[Service]
Type=oneshot
ExecStart=${SANDBOX_DIR}/scripts/70-build-catalog.sh
EOF

write opencode-student-catalog.timer <<'EOF'
[Unit]
Description=Еженедельное обновление каталога датасетов стенда OpenCode

[Timer]
OnCalendar=Sun *-*-* 05:20:00
Persistent=true
RandomizedDelaySec=600

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
for n in restore cert catalog; do
  systemctl --user enable --now "opencode-student-$n.timer"
done

echo "==> Таймеры:"
systemctl --user list-timers --all 2>/dev/null | grep opencode-student || true
echo
echo "Проверка linger (нужен, чтобы таймеры жили без залогиненной сессии):"
loginctl show-user "$USER" 2>/dev/null | grep -i linger || true
