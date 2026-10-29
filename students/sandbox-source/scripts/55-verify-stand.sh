#!/usr/bin/env bash
# Проверяет, что стенд жив и что очистка сработала.
#
#   scripts/55-verify-stand.sh                  # только здоровье стенда
#   scripts/55-verify-stand.sh <url>           # ещё и что ссылка недоступна
#
# Что проверяется:
#   1. все контейнеры на месте и работают;
#   2. HTTPS на :443 отвечает 200 (стенд открывается в браузере);
#   3. изоляция цела (13 проверок из 50-verify-isolation.sh);
#   4. сессий OpenCode не осталось (старые ссылки на результат мертвы);
#   5. переданный URL не отдаётся (404/403 вместо файла).
set -uo pipefail
cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
[ -f .env ] && { set -a; . ./.env; set +a; }

FAILED=0
ok()  { printf '  \033[32m✓\033[0m %s\n' "$*"; }
no()  { printf '  \033[31m✗\033[0m %s\n' "$*"; FAILED=1; }
hdr() { printf '\n\033[1m%s\033[0m\n' "$*"; }

hdr "1. Контейнеры"
for c in sandbox egress upload-handler edge; do
  name="opencode-student-${c}"
  [ "${c}" = "upload-handler" ] && name="opencode-upload-handler"
  state=$(docker inspect -f '{{.State.Status}}' "${name}" 2>/dev/null || echo "нет")
  if [ "${state}" = "running" ]; then ok "${name}: ${state}"; else no "${name}: ${state}"; fi
done

hdr "2. Стенд отвечает по HTTPS"
code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "https://127.0.0.1:${EDGE_HTTPS_PORT:-443}/" || echo 000)
if printf '%s' "${code}" | grep -qE '^[23]'; then
  ok "https://:${EDGE_HTTPS_PORT:-443}/ → ${code}"
else
  no "https://:${EDGE_HTTPS_PORT:-443}/ → ${code}"
fi

hdr "3. Изоляция"
if bash scripts/50-verify-isolation.sh >/tmp/verify-isolation.$$ 2>&1; then
  ok "все проверки изоляции пройдены ($(grep -c '✓' /tmp/verify-isolation.$$) шт.)"
else
  no "проверки изоляции провалены — подробности:"
  sed 's/^/     /' /tmp/verify-isolation.$$
fi
rm -f /tmp/verify-isolation.$$

hdr "4. Сессии OpenCode"
sessions=$(docker exec -u 1000:1000 opencode-student-sandbox \
  sh -c 'cd /work && opencode session list 2>/dev/null | grep -c "^ses_" || true' 2>/dev/null | tr -d '[:space:]')
if [ -z "${sessions}" ] || [ "${sessions}" = "0" ]; then
  ok "сессий не осталось — старые результаты и переписки недоступны"
else
  no "осталось сессий: ${sessions} (нужно: 0)"
fi

if [ -n "${1:-}" ]; then
  hdr "5. Ссылка ${1}"
  code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "${1}" || echo 000)
  case "${code}" in
    404|403|410) ok "${code} — файл недоступен (как и должно быть)" ;;
    000)          no "не отвечает" ;;
    *)            no "${code} — файл всё ещё отдаётся!" ;;
  esac
fi

hdr "Итог"
if [ "${FAILED}" -eq 0 ]; then
  echo "  Стенд работоспособен."
else
  echo "  Есть проблемы — см. строки с крестиком выше."
fi
exit "${FAILED}"
