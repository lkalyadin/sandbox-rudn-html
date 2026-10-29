#!/usr/bin/env bash
# Дашборд состояния сервера и обоих стендов. Только читает — ничего не меняет.
#
#   scripts/56-monitor.sh              # одиночный снимок
#   watch -n 10 scripts/56-monitor.sh  # живой режим
#   scripts/56-monitor.sh --log        # снимок + одна строка в /tmp/opencode/monitor.log
#
# Разделы:
#   1. Сервер: load, RAM, диск
#   2. Контейнеры: статус, перезапуски, расход (CPU/RAM/PIDs против лимитов)
#   3. Стенды: HTTPS обоих, upload, срок TLS
#   4. Сессии и файлы студентов
#   5. Логи: ошибки nginx, блокировки egress
#   6. Таймеры: очистка/восстановление/продление TLS
#
# Код возврата: 0 — всё в пределах нормы, 1 — есть предупреждения, 2 — есть критично.
set -uo pipefail
cd "$(dirname "$0")/.."

LOGFILE=/tmp/opencode/monitor.log
WITH_LOG=0
[ "${1:-}" = "--log" ] && WITH_LOG=1

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; BAD=$(( BAD > 1 ? BAD : 1 )); }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; BAD=2; }
hdr()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
BAD=0

# Первое число load average и число ядер.
load=$(awk '{print $1}' /proc/loadavg)
cores=$(nproc)
overload() { # overload <число> — сравнивает load с ядрами, 90% = порог
  awk -v l="$load" -v c="$cores" -v t="${1:-0.9}" 'BEGIN{exit !(l > c*t)}'
}

# Дни до истечения сертификата.
cert_days() {
  local f=edge/certs/fullchain.pem end
  [ -r "$f" ] || { echo "?"; return; }
  end=$(openssl x509 -enddate -noout -in "$f" 2>/dev/null | cut -d= -f2) || { echo "?"; return; }
  echo $(( ( $(date -d "$end" +%s) - $(date +%s) ) / 86400 ))
}

printf '\033[1mМониторинг стенда\033[0m  %s  (load %s на %s ядер)\n' "$(date '+%F %T')" "$load" "$cores"

hdr "1. Сервер"
if overload 0.9; then warn "load $load ≈ предел для $cores ядер"; else ok "load $load / $cores ядер"; fi
mem_used=$(free -m | awk '/^Mem:/{print $3}'); mem_total=$(free -m | awk '/^Mem:/{print $2}')
mem_pct=$(( mem_total ? mem_used * 100 / mem_total : 0 ))
if [ "$mem_pct" -ge 90 ]; then bad "RAM ${mem_used}/${mem_total} МБ (${mem_pct}%)";
elif [ "$mem_pct" -ge 75 ]; then warn "RAM ${mem_used}/${mem_total} МБ (${mem_pct}%)";
else ok "RAM ${mem_used}/${mem_total} МБ (${mem_pct}%)"; fi
if free -m | awk '/^Swap:/{exit !($3>0)}'; then
  sw=$(free -m | awk '/^Swap:/{print $3"/"$2" МБ"}')
  warn "swap используется: $sw (на VPS swap нет — при росте будет OOM)"
else ok "swap не используется"; fi
d_used=$(df -m / | awk 'NR==2{print $3}'); d_total=$(df -m / | awk 'NR==2{print $2}')
d_pct=$(df -h / | awk 'NR==2{gsub("%","");print $5}')
if [ "${d_pct:-0}" -ge 90 ]; then bad "диск ${d_used}/${d_total} МБ (${d_pct}%)";
elif [ "${d_pct:-0}" -ge 80 ]; then warn "диск ${d_used}/${d_total} МБ (${d_pct}%)";
else ok "диск ${d_used}/${d_total} МБ (${d_pct}%)"; fi

hdr "2. Контейнеры"
declare -A WANT=( [sandbox]=opencode-student-sandbox [egress]=opencode-student-egress
                  [upload-handler]=opencode-upload-handler [edge]=opencode-student-edge )
for svc in sandbox egress upload-handler edge; do
  name=${WANT[$svc]}
  state=$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null || echo "нет")
  restarts=$(docker inspect -f '{{.RestartCount}}' "$name" 2>/dev/null || echo 0)
  if [ "$state" != "running" ]; then bad "$svc: $state";
  elif [ "$restarts" -gt 5 ]; then warn "$svc: running, но рестартов уже $restarts";
  else ok "$svc: running"; fi
done
# Расход ресурсов против лимитов песочницы (6 ГБ / 3.5 CPU / 512 pids).
if command -v docker >/dev/null; then
  st=$(docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}} {{.PIDs}}' 2>/dev/null)
  line=$(printf '%s\n' "$st" | grep '^opencode-student-sandbox ' || true)
  if [ -n "$line" ]; then
    cpu=$(echo "$line" | awk '{print $2}' | tr -d '%')
    mem=$(echo "$line" | awk '{print $3}'); memlim=$(echo "$line" | awk '{print $5}')
    pids=$(echo "$line" | awk '{print $6}')
    awk -v c="$cpu" 'BEGIN{exit !(c>80)}' && bad "песочница CPU ${cpu}%" || ok "песочница CPU ${cpu}%"
    ok "песочница RAM $mem, процессов $pids/512"
    [ "${pids:-0}" -ge 450 ] && warn "предельно много процессов в песочнице ($pids/512)"
  fi
fi

hdr "3. Стенды"
code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "https://127.0.0.1/" || echo 000)
case "$code" in 2*|3*) ok "новый стенд https://:443/ → $code";; *) bad "новый стенд → $code";; esac
code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "https://127.0.0.1/files/output/" || echo 000)
case "$code" in 2*|3*|403) ok "/files/ отвечает → $code (403 = листинг закрыт, это норма)";; *) bad "/files/ → $code";; esac
# upload-handler не опубликован на хосте (expose, не ports) — проверяем через edge.
# /upload/ за basic-auth: шлём пароль из sandbox/.env, 401 без пароля = конечка жива.
_uh_pass=$(sed -n 's/^SANDBOX_PASSWORD=//p' ./.env 2>/dev/null | tr -d '"'"'")
if [ -n "$_uh_pass" ]; then
  code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 -u "opencode:${_uh_pass}" "https://127.0.0.1/upload/health" 2>/dev/null || echo 000)
else
  code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "https://127.0.0.1/upload/health" 2>/dev/null || echo 000)
  [ "$code" = "401" ] && code="200"
fi
case "$code" in
  200) ok "upload-handler /upload/health → 200" ;;
  404) warn "upload-handler не отвечает за /upload/ (проверить блок /upload/ в site.*.conf)" ;;
  *)   warn "upload-handler /upload/health → $code" ;;
esac
if systemctl --user is-active --quiet opencode-web 2>/dev/null && systemctl --user is-active --quiet caddy 2>/dev/null; then
  code=$(curl -ks -o /dev/null -w '%{http_code}' --max-time 10 "https://127.0.0.1:4601/" || echo 000)
  case "$code" in 2*|3*) ok "старый стенд :4601 → $code";; *) warn "старый стенд :4601 → $code";; esac
else
  warn "старый стенд: opencode-web/caddy не active"
fi
cdays=$(cert_days)
if [ "$cdays" = "?" ]; then
  warn "не удалось прочитать сертификат edge/certs/fullchain.pem"
elif [ "$cdays" -le 1 ]; then
  bad "TLS истекает через $cdays дн. — срочно scripts/60-renew-cert.sh"
elif [ "$cdays" -le 2 ]; then
  warn "TLS истекает через $cdays дн."
else
  ok "TLS действителен ещё $cdays дн."
fi

hdr "4. Сессии и файлы студентов"
if docker exec opencode-student-sandbox python3 -c '
import sqlite3
c = sqlite3.connect("/home/sandbox/.local/share/opencode/opencode.db")
print(c.execute("select count(*) from session_v2").fetchone()[0])' 2>/dev/null | grep -q '^[0-9]'; then
  sess=$(docker exec opencode-student-sandbox python3 -c '
import sqlite3
c = sqlite3.connect("/home/sandbox/.local/share/opencode/opencode.db")
print(c.execute("select count(*) from session_v2").fetchone()[0])' 2>/dev/null)
  if [ "${sess:-0}" -ge 40 ]; then warn "сессий в песочнице: $sess (много — следить за RAM)"
  else ok "сессий в песочнице: $sess"; fi
else
  warn "не удалось прочитать БД песочницы"
fi
ws="${WORKSPACE:-$(cd .. && pwd)/workspace}"
out_n=$(find "$ws/output" -maxdepth 1 -type f 2>/dev/null | wc -l)
up_n=$(find "$ws/uploads" -maxdepth 1 -type f 2>/dev/null | wc -l)
ws_mb=$(du -sm "$ws" 2>/dev/null | cut -f1)
ok "output: $out_n файлов, uploads: $up_n, workspace: ${ws_mb:-?} МБ"
[ "${ws_mb:-0}" -ge 40000 ] && warn "workspace подрастает до предела (~49 ГБ)"

hdr "5. Логи"
logs=$(docker compose logs --tail=3000 edge 2>/dev/null)
e5=$(printf '%s' "$logs" | grep -cE '" 5[0-9][0-9] ' || true)
e4=$(printf '%s' "$logs" | grep -cE '" 4[0-9][0-9] ' || true)
req=$(printf '%s' "$logs" | grep -cE '" (GET|POST|HEAD) ' || true)
if [ "$e5" -gt 20 ]; then bad "nginx 5xx: $e5 из последних $req запросов"
elif [ "$e5" -gt 0 ]; then warn "nginx 5xx: $e5 из последних $req запросов"
else ok "nginx 5xx: 0 из последних $req запросов"; fi
blocked=$(docker compose logs --tail=500 egress 2>/dev/null | grep -ci 'blocked' || true)
[ "${blocked:-0}" -gt 0 ] && warn "egress: $blocked заблокированных обращений (allowlist)" || ok "egress: блокировок нет"
# OOM и рестарты песочницы за всё время контейнера.
oom=$(docker inspect -f '{{.State.OOMKilled}}' opencode-student-sandbox 2>/dev/null)
[ "$oom" = "true" ] && bad "песочница когда-то убита по OOM" || ok "песочница не убита по OOM"

hdr "6. Таймеры"
while read -r next unit; do
  [ -n "${unit:-}" ] || continue
  case "$unit" in
    opencode-student-*.timer) ok "$unit → $next";;
  esac
done < <(systemctl --user list-timers --no-pager 2>/dev/null | awk 'NR>1{print $1" "$NF}')
# в system-таймерах NF = сервис (…cleanup.service), имя таймера — предпоследнее поле
cleanup=$(systemctl list-timers --no-pager 2>/dev/null | awk 'NF>1 && $(NF-1)=="opencode-student-cleanup.timer"{print $1, $2, $3, $4}')
[ -n "$cleanup" ] && ok "opencode-student-cleanup.timer (root) → $cleanup" || warn "таймер ночной очистки не найден"

printf '\n'
if [ "$WITH_LOG" -eq 1 ]; then
  mkdir -p "$(dirname "$LOGFILE")"
  printf '%s\tload=%s\tmem=%s%%\tdisk=%s%%\tsessions=%s\t5xx=%s\tcert_days=%s\tlevel=%s\n' \
    "$(date '+%F %T')" "$load" "$mem_pct" "${d_pct:-0}" "${sess:-?}" "${e5:-0}" "${cdays:-?}" "$BAD" >> "$LOGFILE"
fi

if [ "$BAD" -eq 2 ]; then printf '\033[31mЕСТЬ КРИТИЧНЫЕ ПРОБЛЕМЫ\033[0m\n'; exit 2
elif [ "$BAD" -eq 1 ]; then printf '\033[33mесть предупреждения\033[0m\n'; exit 1
else printf '\033[32mвсё в норме\033[0m\n'; exit 0; fi
