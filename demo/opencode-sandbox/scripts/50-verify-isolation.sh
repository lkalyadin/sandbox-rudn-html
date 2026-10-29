#!/usr/bin/env bash
# Проверяет ИЗОЛЯЦИЮ, а не работу агента.
#
# Логика такая: правила OpenCode (permissions/policies) можно обойти — это
# не песочница. Поэтому проверяем границы, которые студент обойти не может:
# сеть, привилегии, файловая система, ядро.
#
# Все проверки идут через `docker exec`, то есть в обход агента — именно так
# и надо: мы проверяем ОС, а не вежливость модели.
set -uo pipefail
cd "$(dirname "$0")/.."

CT=sandbox
pass=0; fail=0
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; pass=$((pass+1)); }
no()   { printf '  \033[31m✗\033[0m %s\n' "$*"; fail=$((fail+1)); }
hdr()  { printf '\n\033[1m%s\033[0m\n' "$*"; }

if ! docker inspect "${CT}" >/dev/null 2>&1; then
  echo "Контейнер ${CT} не запущен. Сначала scripts/30-up.sh" >&2
  exit 1
fi

# Служебный контейнер, который не видит сеть песочницы и наоборот,
# поэтому тесты запускаем внутри самой песочницы.
run() { docker exec -i "${CT}" sh -c "$1" 2>&1; }

hdr "1. Ядро: работает ли gVisor"
kernel=$(run 'uname -r')
if [ "${kernel}" = "4.4.0" ]; then
  ok "uname -r = 4.4.0 — это ядро gVisor, а не ядро хоста"
else
  no "uname -r = ${kernel}. Похоже, контейнер работает на обычном runc."
  echo "     Студент с kernel-exploit получит root на хосте."
fi

hdr "2. Прямой выход в интернет"
out=$(run 'python3 - <<PY
import socket
try:
    socket.create_connection(("1.1.1.1", 443), timeout=4).close()
    print("REACHABLE")
except Exception as e:
    print("BLOCKED")
PY')
if [ "${out}" = "BLOCKED" ]; then
  ok "прямое соединение с 1.1.1.1:443 не проходит"
else
  no "песочница имеет прямой выход в интернет (${out})"
fi

hdr "3. Egress-прокси: allowlist"
allowed=$(run 'python3 - <<PY
import urllib.request, urllib.error
o = urllib.request.build_opener(urllib.request.ProxyHandler({"https": "http://egress:8888"}))
try:
    print("OK", o.open("https://opencode.ai/", timeout=10).status)
except urllib.error.HTTPError as e:
    print("HTTP", e.code)
except Exception as e:
    print("ERR", type(e).__name__)
PY')
if printf '%s' "${allowed}" | grep -qE '^(OK|HTTP 2|HTTP 3)'; then
  ok "домен моделей opencode.ai доступен (${allowed})"
else
  no "opencode.ai недоступен через прокси: ${allowed}"
  echo "     Скорее всего не хватает домена в egress/allowlist"
fi

blocked=$(run 'python3 - <<PY
import urllib.request, urllib.error
o = urllib.request.build_opener(urllib.request.ProxyHandler({"https": "http://egress:8888"}))
try:
    print("ALLOWED", o.open("https://example.com/", timeout=10).status)
except urllib.error.HTTPError as e:
    print("HTTP", e.code)
except Exception as e:
    print("ERR", type(e).__name__)
PY')
if printf '%s' "${blocked}" | grep -qE 'HTTP 403|ERR'; then
  ok "посторонний домен example.com заблокирован (${blocked})"
else
  no "посторонний домен не заблокирован: ${blocked}"
fi

hdr "4. Привилегии"
uid=$(run 'id -u')
if [ "${uid}" != "0" ]; then ok "процесс не root (uid=${uid})"; else no "процесс работает от root"; fi

if run 'sudo -n true' | grep -qi 'not found\|permission\|no such'; then
  ok "sudo недоступен"
else
  no "sudo, похоже, работает — проверьте вручную"
fi

caps=$(docker inspect -f '{{.HostConfig.CapDrop}}' "${CT}")
if printf '%s' "${caps}" | grep -qi 'ALL'; then ok "cap_drop: ALL"; else no "capabilities не сброшены (${caps})"; fi

if run 'test ! -e /var/run/docker.sock' >/dev/null; then
  ok "docker.sock не смонтирован"
else
  no "в контейнере есть docker.sock — это побег на хост"
fi

hdr "5. Файловая система"
if run 'touch /etc/hacked 2>/dev/null && echo WROTE'; then
  no "корневая ФС доступна на запись"
else
  ok "корневая ФС read-only"
fi
if run 'touch /work/.probe && rm -f /work/.probe && echo WROTE'; then
  ok "рабочая папка /work доступна на запись (так и должно быть)"
else
  no "в /work нельзя писать — студенты не смогут работать"
fi

hdr "6. Лимиты"
pids=$(docker inspect -f '{{.HostConfig.PidsLimit}}' "${CT}")
[ -n "${pids}" ] && [ "${pids}" != "0" ] && ok "pids_limit = ${pids}" || no "pids_limit не задан"
mem=$(docker inspect -f '{{.HostConfig.Memory}}' "${CT}")
[ "${mem}" != "0" ] && ok "memory limit = $((mem/1024/1024)) MiB" || no "memory limit не задан"
cpu=$(docker inspect -f '{{.HostConfig.NanoCpus}}' "${CT}")
[ "${cpu}" != "0" ] && ok "cpu limit = $(awk -v n="${cpu}" 'BEGIN{printf "%.1f", n/1e9}') ядра" || no "cpu limit не задан"

hdr "Итог"
printf '  пройдено: \033[32m%d\033[0m, провалено: \033[31m%d\033[0m\n' "${pass}" "${fail}"
if [ "${fail}" -gt 0 ]; then
  echo
  echo "  Проваленные проверки — это то, через что студент может выйти из песочницы."
  exit 1
fi
echo "  Изоляция настроена."
