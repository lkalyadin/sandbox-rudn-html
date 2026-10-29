#!/usr/bin/env bash
#
# export-main-stand.sh — собирает переносимый архив для переезда ОСНОВНОГО стенда
# :4601 на новый VPS. Ничего на хосте не меняет (только читает).
#
# Что попадает в архив (макет повторяет целевые пути, распаковка — от /):
#   home/deployagent/.config/opencode/{opencode.jsonc,package.json,package-lock.json,service.json}
#   home/deployagent/.config/opencode-web.env          (600, секрет)
#   home/deployagent/.config/caddy/{Caddyfile,Caddyfile.known-good,Caddyfile.fallback-internal,backups}
#   home/deployagent/.config/systemd/user/{opencode-web,caddy}.service
#   home/deployagent/bin/oc-fix.sh
#   home/deployagent/web/normal-forms                  (симлинк, цель — в projects)
#   home/deployagent/.ssh/{config,known_hosts,id_ed25519_*}   (600, секрет)
#   home/deployagent/{.gitconfig,.bashrc,.profile,.zshrc}
#   home/deployagent/projects/{students,opencode-settings,datasets,demo,AGENTS.md,*.html,*.md,*.docx}
#   home/deployagent/projects/students/sandbox-source  (исходники студенческого стенда: docker/,
#                                                       config/, skills/, scripts/, edge/*.conf, compose)
#   db/opencode.db                                     (консистентный бэкап через sqlite3 backup API)
#   secrets/student-sandbox.env                        (600, .env студенческого стенда)
#   MANIFEST.txt, sysinfo.txt
#
# НЕ попадает (осознанно): oc-cert-renew.{service,timer} и certbot/venv (на новом хосте сертификатом
# управляет сам Caddy), git-проекты gameconnect/adventuremazes (клонируются из GitHub),
# node_modules, ~/.cache, ~/.npm, ~/sandbox, /srv/opencode-student (бандлы, workspace.img,
# сертификаты, ACME-состояние), ~/.local/share/caddy, ~/.local/venvs/certbot, сессии/логи OpenCode.
#
# Запуск:
#   bash scripts/export-main-stand.sh --dry-run      # план и размеры, ничего не пишет
#   bash scripts/export-main-stand.sh                # собрать в ~/tmp/migration
#   bash scripts/export-main-stand.sh --with-git-projects   # + рабочие копии git-проектов (≈490 МБ)
#   bash scripts/export-main-stand.sh --out /path    # другой каталог (нужен диск, не tmpfs)
#
set -uo pipefail

HOME_DIR=${HOME:-/home/deployagent}
OUT="$HOME_DIR/tmp/migration"
STAMP=$(date -u +%Y%m%d-%H%M)
DRY=0
WITH_GIT=0

while [ $# -gt 0 ]; do
	case "$1" in
		--dry-run) DRY=1 ;;
		--with-git-projects) WITH_GIT=1 ;;
		--out) OUT="${2:-}"; [ -n "$OUT" ] || { echo "нужен путь: --out DIR" >&2; exit 2; }; shift ;;
		-h|--help) sed -n '2,40p' "$0" | sed -E 's/^# ?//'; exit 0 ;;
		*) echo "неизвестный флаг: $1 (--help)" >&2; exit 2 ;;
	esac
	shift
done

say() { printf '\n== %s\n' "$*"; }
ok()  { printf '  ок    %s\n' "$*"; }
info(){ printf '  ·     %s\n' "$*"; }

# ── Список путей (относительно /) ───────────────────────────────────────────
CONFIG_PATHS=(
	home/deployagent/.config/opencode/opencode.jsonc
	home/deployagent/.config/opencode/package.json
	home/deployagent/.config/opencode/package-lock.json
	home/deployagent/.config/opencode/service.json
	home/deployagent/.config/opencode-web.env
	home/deployagent/.config/caddy/Caddyfile
	home/deployagent/.config/caddy/Caddyfile.known-good
	home/deployagent/.config/caddy/Caddyfile.fallback-internal
	home/deployagent/.config/systemd/user/opencode-web.service
	home/deployagent/.config/systemd/user/caddy.service
	home/deployagent/bin/oc-fix.sh
	home/deployagent/web/normal-forms
	home/deployagent/.ssh/config
	home/deployagent/.ssh/known_hosts
	home/deployagent/.ssh/id_ed25519_adventuremazes
	home/deployagent/.ssh/id_ed25519_adventuremazes.pub
	home/deployagent/.ssh/id_ed25519_gameconnect
	home/deployagent/.ssh/id_ed25519_gameconnect.pub
	home/deployagent/.ssh/sandbox_new_ed25519
	home/deployagent/.ssh/sandbox_new_ed25519.pub
	home/deployagent/.gitconfig
	home/deployagent/.bashrc
	home/deployagent/.profile
	home/deployagent/.zshrc
	home/deployagent/.opencode/package.json
	home/deployagent/.config/caddy/backups
)

PROJECTS=(students opencode-settings datasets demo)
PROJECT_FILES_GLOB=(AGENTS.md)

missing=()
for p in "${CONFIG_PATHS[@]}"; do
	[ -e "/$p" ] || missing+=("$p")
done
for d in "${PROJECTS[@]}"; do
	[ -d "/home/deployagent/projects/$d" ] || missing+=("projects/$d")
done

# ── План ────────────────────────────────────────────────────────────────────
say "План переноса (${STAMP})"
info "каталог назначения: $OUT"
for p in "${CONFIG_PATHS[@]}"; do
	[ -e "/$p" ] && printf '  %8s  %s\n' "$(du -sh "/$p" 2>/dev/null | cut -f1)" "/$p"
done
for d in "${PROJECTS[@]}"; do
	[ -d "/home/deployagent/projects/$d" ] && printf '  %8s  %s\n' \
		"$(du -sh "/home/deployagent/projects/$d" | cut -f1)" "/home/deployagent/projects/$d"
done
find /home/deployagent/projects -maxdepth 1 -type f \( -name '*.html' -o -name '*.md' -o -name '*.docx' \) \
	-printf '  %8s  %p\n' 2>/dev/null | sort -k2 || true
printf '  %8s  %s\n' "$(du -sh /srv/opencode-student/sandbox 2>/dev/null | cut -f1)" \
	"/srv/opencode-student/sandbox (только исходники → students/sandbox-source)"
printf '  %8s  %s\n' "$(du -sh /home/deployagent/.local/share/opencode/opencode.db 2>/dev/null | cut -f1)" \
	"~/.local/share/opencode/opencode.db → db/opencode.db (бэкап)"
[ ${#missing[@]} -gt 0 ] && { warn=$(printf '%s\n' "${missing[@]}"); printf '  ВНИМ  нет путей:\n%s\n' "$(echo "$warn" | sed 's/^/        /')"; }

for g in gameconnect adventuremazes; do
	d=/home/deployagent/projects/$g
	[ -d "$d" ] || continue
	branch=$(git -C "$d" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')
	origin=$(git -C "$d" remote get-url origin 2>/dev/null || echo 'нет remote')
	dirty=$(git -C "$d" status --porcelain 2>/dev/null | wc -l)
	printf '  %8s  %s (git %s, незакоммичено: %s)\n' "$(du -sh "$d" | cut -f1)" "$d" "$branch" "$dirty"
	printf '            origin: %s\n' "$origin"
done
if [ "$WITH_GIT" = 1 ]; then
	info "git-проекты ВКЛЮЧЕНЫ в архив (--with-git-projects)"
else
	info "git-проекты НЕ включаются: их место — клон из GitHub (см. runbook, §5)"
fi

if [ "$DRY" = 1 ]; then
	say "Режим --dry-run: ничего не записано"
	exit 0
fi

# ── Сборка ──────────────────────────────────────────────────────────────────
mkdir -p "$OUT" || { echo "не создать $OUT" >&2; exit 1; }
STAGE=$(mktemp -d "$OUT/.stage-XXXXXX") || exit 1
trap 'rm -rf "$STAGE"' EXIT

say "Копирую конфиги"
cd /
for p in "${CONFIG_PATHS[@]}"; do
	[ -e "/$p" ] || continue
	cp -a --parents "$p" "$STAGE/" 2>/dev/null || echo "  не скопировано: /$p" >&2
done
ok "конфиги, юниты, ключи, скрипты"

say "Копирую проекты (без git-проектов)"
mkdir -p "$STAGE/home/deployagent/projects"
for d in "${PROJECTS[@]}"; do
	[ -d "/home/deployagent/projects/$d" ] || continue
	cp -a "/home/deployagent/projects/$d" "$STAGE/home/deployagent/projects/"
done
find /home/deployagent/projects -maxdepth 1 -type f \( -name '*.html' -o -name '*.md' -o -name '*.docx' \) \
	-exec cp -a {} "$STAGE/home/deployagent/projects/" \;
ok "projects: ${PROJECTS[*]} + файлы в корне"

say "Копирую исходники студенческого стенда (без состояния и секретов)"
SRC=/srv/opencode-student/sandbox
DST="$STAGE/home/deployagent/projects/students/sandbox-source"
if [ -d "$SRC" ]; then
	mkdir -p "$DST"
	tar -C "$SRC" -cf - \
		--exclude='./.env' --exclude='./workspace/data' --exclude='./workspace/output' \
		--exclude='./edge/certs' --exclude='./edge/acme' --exclude='./edge/letsencrypt' \
		--exclude='./edge/htpasswd' --exclude='__pycache__' --exclude='*.pyc' \
		--exclude='./catalog/catalog.json' --exclude='./catalog/catalog.md' \
		. | tar -C "$DST" -xf -
	[ -f "$SRC/.env" ] && { mkdir -p "$STAGE/secrets"; cp -a "$SRC/.env" "$STAGE/secrets/student-sandbox.env"; }
	ok "sandbox-source: $(du -sh "$DST" | cut -f1) (+ secrets/student-sandbox.env)"
else
	info "нет $SRC — исходники стенда пропущены"
fi

if [ "$WITH_GIT" = 1 ]; then
	say "Копирую git-проекты (≈490 МБ, с node_modules)"
	for g in gameconnect adventuremazes; do
		[ -d "/home/deployagent/projects/$g" ] || continue
		cp -a "/home/deployagent/projects/$g" "$STAGE/home/deployagent/projects/"
	done
	ok "gameconnect, adventuremazes"
fi

say "Бэкап БД (sqlite3 backup API, без WAL)"
mkdir -p "$STAGE/db"
python3 - "$STAGE/db/opencode.db" <<'PY' || { echo "бэкап БД не удался" >&2; exit 1; }
import os, sqlite3, sys
src = os.path.expanduser("~/.local/share/opencode/opencode.db")
dst = sys.argv[1]
s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
d = sqlite3.connect(dst)
with d:
    s.backup(d)
print("  quick_check:", d.execute("pragma quick_check").fetchone()[0])
for t in ("session_v2", "project", "credential"):
    try:
        print(f"  {t}:", d.execute(f"select count(*) from {t}").fetchone()[0])
    except Exception as e:
        print(f"  {t}: нет ({e})")
d.close(); s.close()
PY
chmod 600 "$STAGE/db/opencode.db"
ok "db/opencode.db ($(du -h "$STAGE/db/opencode.db" | cut -f1))"

say "MANIFEST и sysinfo"
{
	echo "Перенос основного стенда :4601 — архив от $(date -u '+%Y-%m-%d %H:%M UTC')"
	echo "Хост-источник: $(hostname) ($(curl -s -m 5 -4 ifconfig.me 2>/dev/null || echo '?'))"
	echo
	echo "Версии:"
	echo "  $(~/.opencode/bin/opencode --version 2>/dev/null | tail -1)"
	echo "  caddy: $(~/bin/caddy version 2>/dev/null | head -1)"
	echo "  certbot: $(~/.local/venvs/certbot/bin/certbot --version 2>/dev/null)"
	echo "  python: $(python3 -V 2>&1)"
	echo "  $(. /etc/os-release && echo "$PRETTY_NAME")"
	echo
	echo "Разделы архива:"
	echo "  home/…            конфиги OpenCode/Caddy/юниты/скрипт восстановления/ssh/проекты"
	echo "  db/opencode.db    бэкап БД (креды провайдеров, проекты, сессии) — 600"
	echo "  secrets/          *.env (600): opencode-web.env, student-sandbox.env"
	echo "  sysinfo.txt       снимок окружения источника"
	echo
	echo "НЕ включено: gameconnect/, adventuremazes/ (git), node_modules, ~/.cache, ~/.npm,"
	echo "             ~/sandbox, /srv/opencode-student/{bundles,workspace.img,monitoring,certs},"
	echo "             ~/.local/share/caddy (сертификаты), ~/.local/venvs/certbot, логи/сессии."
	echo
	echo "Дальше — docs/migration-runbook-2026-10.md:"
	echo "  tar -xzf <этот архив> -C /        # от root, на новом хосте"
	echo "  затем §4 (OpenCode), §6 (TLS/Caddy), §8 (проверки)"
} > "$STAGE/MANIFEST.txt"

{
	echo "# снимок источника (для сверки с новым хостом)"
	uname -a
	. /etc/os-release && echo "$PRETTY_NAME"
	echo "nproc=$(nproc) mem=$(free -m | awk '/^Mem:/{print $2}')MB"
	echo "sysctl unprivileged_port_start=$(cat /proc/sys/net/ipv4/ip_unprivileged_port_start)"
	echo "vm.swappiness=$(cat /proc/sys/vm/swappiness)"
	echo
	echo "## systemd user units"
	systemctl --user list-unit-files --no-pager 2>/dev/null | grep -E 'opencode|caddy|oc-cert' || true
	echo
	echo "## apt (вручную)"
	apt-mark showmanual 2>/dev/null | tr '\n' ' ' || true
	echo
	echo "## git-проекты"
	for g in gameconnect adventuremazes; do
		d="/home/deployagent/projects/$g"
		[ -d "$d" ] || continue
		echo "$g: $(git -C "$d" rev-parse --abbrev-ref HEAD 2>/dev/null) $(git -C "$d" remote get-url origin 2>/dev/null)"
		git -C "$d" status --porcelain 2>/dev/null | sed 's/^/    /'
	done
} > "$STAGE/sysinfo.txt"

say "Упаковка"
ARCHIVE="$OUT/main-stand-$STAMP.tar.gz"
tar -C "$STAGE" -czf "$ARCHIVE" . || { echo "tar не удался" >&2; exit 1; }
chmod 600 "$ARCHIVE"
(cd "$OUT" && sha256sum "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256")
ok "$ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"
ok "контрольная сумма: $ARCHIVE.sha256"

say "Готово"
cat <<EOF
  Архив:  $ARCHIVE
  Сумма:  $ARCHIVE.sha256
  Секрет: внутри db/opencode.db и secrets/*.env — не пересылать открытым каналом.
  Дальше: docs/migration-runbook-2026-10.md (§3–§8) и перенос на новый хост.
EOF
