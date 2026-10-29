#!/usr/bin/env bash
#
# new-host-bootstrap.sh — ОДНОРАЗОВЫЕ root-шаги для нового основного хоста стенда `:4601`.
#
# Модель доступа: root нужен ТОЛЬКО для этого скрипта. Всё остальное (OpenCode, Caddy,
# проекты, БД, сертификат) делается под пользователем deployagent БЕЗ sudo. Скрипт
# НЕ добавляет ключ в /root, НЕ выдаёт sudo, НЕ ставит docker и НЕ трогает sshd.
#
# Запуск на новом VPS от root (ключ — публичный ключ того, кто будет разворачивать стенд):
#   bash new-host-bootstrap.sh --ssh-key "ssh-ed25519 AAAA... deployagent@host"
#   bash new-host-bootstrap.sh --ssh-key "..." --dry-run      # только показать план
#   bash new-host-bootstrap.sh --ssh-key "..." --no-swap      # если swap не нужен
#   bash new-host-bootstrap.sh --ssh-key "..." --with-postgres
#   PG_PASSWORD='...' bash new-host-bootstrap.sh --ssh-key "..." --with-postgres
#
# Что делает (идемпотентно, повторный запуск безопасен):
#   1) пользователь deployagent с uid/gid 1001 и вашим публичным ключом;
#   2) linger — user-сервисы живут без SSH-сессии и встают после ребута;
#   3) sysctl net.ipv4.ip_unprivileged_port_start=80 — Caddy на :4601 и ACME на 80/443
#      без root (порты >1024 в этом не нуждаются, 80/443 — нуждаются);
#   4) swap 2 ГБ (если RAM < 4 ГБ и swap ещё нет) + vm.swappiness=10;
#   5) лимит журнала 300 МБ (иначе /var/log растёт незаметно);
#   6) пакеты: git, curl, ca-certificates, jq, openssl, python3;
#   7) по флагу --with-postgres: PostgreSQL + тюнинг под 1 vCPU / 3 ГБ + роль и БД
#      (если задан PG_PASSWORD; без него — только установка и тюнинг).
#
set -uo pipefail

SSH_KEY=""
DRY=0
WITH_PG=0
DO_SWAP=1
SWAP_SIZE=2G
PG_DB=${PG_DB:-stand}
PG_USER=${PG_USER:-stand}
PG_PASS=${PG_PASSWORD:-}

say()  { printf '\n== %s\n' "$*"; }
ok()   { printf '  ок    %s\n' "$*"; }
warn() { printf '  ВНИМ  %s\n' "$*"; }
die()  { printf '  БЕДА  %s\n' "$*"; exit 1; }

usage() { sed -n '2,32p' "$0" | sed -E 's/^# ?//'; }

while [ $# -gt 0 ]; do
	case "$1" in
		--ssh-key) SSH_KEY="${2:-}"; shift ;;
		--dry-run) DRY=1 ;;
		--with-postgres) WITH_PG=1 ;;
		--no-swap) DO_SWAP=0 ;;
		--swap-size) SWAP_SIZE="${2:-2G}"; shift ;;
		--pg-db) PG_DB="${2:-}"; shift ;;
		--pg-user) PG_USER="${2:-}"; shift ;;
		-h|--help) usage; exit 0 ;;
		*) echo "неизвестный флаг: $1 (--help)" >&2; exit 2 ;;
	esac
	shift
done

run() {  # выполнить команду (или только показать в --dry-run)
	if [ "$DRY" = 1 ]; then printf '  [dry] %s\n' "$*"; else "$@"; fi
}
write_file() {  # $1 = путь, stdin = содержимое
	if [ "$DRY" = 1 ]; then
		printf '  [dry] записать %s (%s байт)\n' "$1" "$(wc -c | tr -d ' ')"
		cat >/dev/null
	else
		cat > "$1"
	fi
}

[ "$(id -u)" -eq 0 ] || [ "$DRY" = 1 ] || die "запускать от root (или добавьте --dry-run)"

. /etc/os-release 2>/dev/null || true
say "Хост"
printf '  %s, %s vCPU, %s МБ RAM\n' "${PRETTY_NAME:-unknown}" "$(nproc)" \
	"$(awk '/^MemTotal/{printf "%d", $2/1024}' /proc/meminfo)"
df -h / | tail -1 | sed 's/^/  /'

[ -n "$SSH_KEY" ] || [ "$DRY" = 1 ] || die "нужен публичный ключ: --ssh-key \"ssh-ed25519 AAAA...\""

# ── 1. Пользователь ─────────────────────────────────────────────────────────
say "1. Пользователь deployagent (uid/gid 1001)"
if getent passwd deployagent >/dev/null; then
	uid=$(id -u deployagent)
	[ "$uid" = "1001" ] || die "deployagent уже есть, но uid=$uid (нужен 1001: от него зависят пути/права)"
	ok "пользователь есть, uid=1001"
else
	taken=$(getent passwd 1001 | cut -d: -f1 || true)
	[ -z "$taken" ] || die "uid 1001 занят пользователем '$taken' — нужен другой образ/хост"
	run useradd -u 1001 -U -m -s /bin/bash deployagent || die "useradd не удался"
	ok "пользователь создан"
fi
run chmod 750 /home/deployagent
if [ -n "$SSH_KEY" ]; then
	run install -d -m 700 -o deployagent -g deployagent /home/deployagent/.ssh
	if [ "$DRY" = 0 ] && grep -qxF "$SSH_KEY" /home/deployagent/.ssh/authorized_keys 2>/dev/null; then
		ok "ключ уже в authorized_keys"
	else
		if [ "$DRY" = 1 ]; then
			printf '  [dry] добавить ключ в ~deployagent/.ssh/authorized_keys\n'
		else
			printf '%s\n' "$SSH_KEY" >> /home/deployagent/.ssh/authorized_keys
			ok "ключ добавлен в ~deployagent/.ssh/authorized_keys"
		fi
	fi
	run chown deployagent:deployagent /home/deployagent/.ssh/authorized_keys
	run chmod 600 /home/deployagent/.ssh/authorized_keys
fi

# ── 2. linger ───────────────────────────────────────────────────────────────
say "2. linger (user-сервисы без SSH-сессии)"
run loginctl enable-linger deployagent
if [ "$DRY" = 1 ]; then
	ok "[dry] Linger=yes"
elif [ "$(loginctl show-user deployagent -p Linger --value 2>/dev/null)" = "yes" ]; then
	ok "Linger=yes"
else
	warn "Linger не включился"
fi

# ── 3. Порты 80/443 без root ────────────────────────────────────────────────
say "3. Порты 80/443 без root"
printf 'net.ipv4.ip_unprivileged_port_start=80\n' | write_file /etc/sysctl.d/99-unprivileged-ports.conf
run sysctl -q --system
if [ "$(cat /proc/sys/net/ipv4/ip_unprivileged_port_start 2>/dev/null)" = "80" ]; then
	ok "порог = 80"
else
	warn "порог не применился (проверьте /etc/sysctl.d/99-unprivileged-ports.conf)"
fi

# ── 4. swap ─────────────────────────────────────────────────────────────────
say "4. swap"
mem_mb=$(awk '/^MemTotal/{printf "%d", $2/1024}' /proc/meminfo)
if [ "$DO_SWAP" = 0 ]; then
	ok "пропущено (--no-swap)"
elif [ -n "$(swapon --show=NAME --noheadings 2>/dev/null)" ]; then
	ok "swap уже есть: $(swapon --show=NAME --noheadings | tr '\n' ' ')"
elif [ "$mem_mb" -ge 4096 ]; then
	ok "RAM ${mem_mb} МБ — swap не обязателен, пропускаю"
else
	if [ ! -f /swapfile ]; then
		run fallocate -l "$SWAP_SIZE" /swapfile || run dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
		run chmod 600 /swapfile
		run mkswap /swapfile
	fi
	run swapon /swapfile
	if [ "$DRY" = 0 ]; then
		grep -q '^/swapfile' /etc/fstab || printf '/swapfile none swap sw 0 0\n' >> /etc/fstab
	fi
	printf 'vm.swappiness=10\n' | write_file /etc/sysctl.d/99-swappiness.conf
	run sysctl -q --system
	ok "swap ${SWAP_SIZE} включён, swappiness=10"
fi

# ── 5. журнал ───────────────────────────────────────────────────────────────
say "5. Лимит журнала"
run mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=300M\n' | write_file /etc/systemd/journald.conf.d/99-size.conf
run systemctl restart systemd-journald
ok "SystemMaxUse=300M"

# ── 6. Пакеты ───────────────────────────────────────────────────────────────
say "6. Пакеты"
run env DEBIAN_FRONTEND=noninteractive apt-get update -qq
run env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
	git curl ca-certificates jq openssl python3
for p in git curl openssl python3 jq; do
	command -v "$p" >/dev/null && ok "$p" || warn "$p не найден"
done

# ── 6.1 firewall, если он активен ───────────────────────────────────────────
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q 'Status: active'; then
	say "6.1 ufw активен — открываю порты"
	for p in 22 80 443 4601; do run ufw allow "$p"/tcp >/dev/null; done
	ok "22/80/443/4601/tcp"
fi

# ── 7. PostgreSQL (опционально) ─────────────────────────────────────────────
if [ "$WITH_PG" = 1 ]; then
	say "7. PostgreSQL"
	run env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql
	ver=$(ls /etc/postgresql 2>/dev/null | sort -V | tail -1)
	if [ -z "$ver" ]; then
		[ "$DRY" = 1 ] && ver="18" || die "не удалось определить версию PostgreSQL"
	fi
	run mkdir -p "/etc/postgresql/$ver/main/conf.d"
	printf '%s\n' \
		'# Стенд :4601 — 1 vCPU / 3 ГБ, редкие запросы' \
		'shared_buffers = 384MB' \
		'effective_cache_size = 1536MB' \
		'work_mem = 8MB' \
		'maintenance_work_mem = 64MB' \
		'max_connections = 20' \
		'log_min_duration_statement = 500ms' \
		| write_file "/etc/postgresql/$ver/main/conf.d/99-stand.conf"
	run mkdir -p "/etc/systemd/system/postgresql@$ver-main.service.d"
	printf '[Service]\nMemoryMax=768M\n' | write_file "/etc/systemd/system/postgresql@$ver-main.service.d/99-memory.conf"
	run systemctl daemon-reload
	run systemctl enable --now postgresql
	run systemctl restart "postgresql@$ver-main"
	ok "PostgreSQL $ver установлен и настроен (MemoryMax=768M)"

	if [ -n "$PG_PASS" ]; then
		case "$PG_DB$PG_USER" in *[!a-z0-9_]*|'') die "PG_DB/PG_USER: только [a-z0-9_], непустые" ;; esac
		if [ "$DRY" = 1 ]; then
			printf '  [dry] создать роль %s и БД %s (пароль скрыт)\n' "$PG_USER" "$PG_DB"
		else
			runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$PG_USER'" | grep -q 1 \
				|| runuser -u postgres -- psql -c "CREATE ROLE $PG_USER LOGIN PASSWORD '$PG_PASS'"
			runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='$PG_DB'" | grep -q 1 \
				|| runuser -u postgres -- createdb -O "$PG_USER" "$PG_DB"
			ok "роль '$PG_USER' и БД '$PG_DB' готовы (только локально)"
		fi
	else
		warn "PG_PASSWORD не задан — роль/БД не созданы (можно позже, см. runbook)"
	fi
fi

# ── Итог ────────────────────────────────────────────────────────────────────
say "Готово"
cat <<EOF
  root больше не нужен: ключ в /root не добавлялся, sudo deployagent не выдавался.
  Пользователь: deployagent (uid 1001), linger=$(loginctl show-user deployagent -p Linger --value 2>/dev/null || echo '?')
  Дальше — под deployagent, по runbook: opencode-settings/docs/migration-runbook-2026-10.md
EOF
