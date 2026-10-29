#!/usr/bin/env bash
# Где смотреть лимиты моделей студенческого стенда.
#
#   bash scripts/58-limits.sh          # статус по логам (быстро, ничего не тратит)
#   bash scripts/58-limits.sh --ping   # плюс живой запрос 1 токена в бесплатную модель
#
# Что показывает:
#   1. бесплатный пул провайдера `opencode` (apiKey "public"): у него НЕТ панели
#      и НЕТ заголовков x-ratelimit — единственный сигнал это ответ провайдера
#      `429 FreeUsageLimitError` + заголовок `Retry-After` (по факту 28.10.2026 —
#      суточное окно, сброс в 00:00 UTC). Поэтому считаем такие ошибки в логе
#      сервера OpenCode внутри песочницы;
#   2. баланс Vercel AI Gateway (наш ключ, он же запасной провайдер vercel-free):
#      GET /v1/credits → balance / total_used в USD;
#   3. сколько моделей реально видит UI.
set -euo pipefail
cd "$(dirname "$0")/.."

PING=false
[ "${1:-}" = "--ping" ] && PING=true
FREE_MODEL="${FREE_MODEL:-opencode/deepseek-v4.1-flash-free}"
LOG=/home/sandbox/.local/share/opencode/log/opencode.log

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
hdr()  { printf '\n\033[1m%s\033[0m\n' "$*"; }

hdr "1. Бесплатный пул провайдера opencode (панели нет — смотрим по логам)"
hits=$(docker exec opencode-student-sandbox sh -lc \
  "grep -c 'FreeUsageLimit' $LOG 2>/dev/null || true" | tr -d '\r')
hits=${hits:-0}
if [ "$hits" = "0" ]; then
  ok "ошибок лимита в логе нет"
else
  bad "в логе $hits ошибок лимита (FreeUsageLimitError)"
  docker exec opencode-student-sandbox sh -lc \
    "grep 'FreeUsageLimit' $LOG 2>/dev/null | tail -1 | cut -c1-160" || true
  echo "     Окно суточное, сброс ~00:00 UTC. Точное время даёт заголовок"
  echo "     Retry-After в ответе провайдера; альтернатива — переключить"
  echo "     дефолтную модель на другую бесплатную или на vercel-free."
fi

hdr "2. Vercel AI Gateway (верcel-free): баланс нашего ключа"
docker exec -i opencode-student-gateway python3 - <<'EOF' || warn "не смог получить баланс"
import os, json, urllib.request
k = os.environ.get("AI_GATEWAY_API_KEY", "")
try:
    r = urllib.request.urlopen(urllib.request.Request(
        "https://ai-gateway.vercel.sh/v1/credits",
        headers={"Authorization": "Bearer " + k}), timeout=20)
    d = json.load(r)
    print(f"  \033[32m✓\033[0m баланс {float(d['balance']):.2f} USD, "
          f"израсходовано {float(d['total_used']):.2f} USD")
except Exception as e:
    print("  \033[31m✗\033[0m ошибка:", e)
EOF

hdr "3. Модели в UI"
set -a; . ./.env; set +a
docker exec opencode-student-sandbox sh -lc \
  "curl -s -u opencode:'$SANDBOX_PASSWORD' http://127.0.0.1:4096/api/model" 2>/dev/null | \
  python3 -c '
import json,sys,collections
try: d = json.load(sys.stdin)
except Exception: print("  не смог прочитать список моделей"); raise SystemExit(0)
items = d.get("data", d) if isinstance(d, dict) else d
c = collections.Counter(str(m.get("providerID","?")).split("/")[0] for m in items)
print("  всего %d: %s" % (len(items), ", ".join("%s=%d" % (k, v) for k, v in c.items())))
'

if [ "$PING" = "true" ]; then
  hdr "4. Живой запрос (1 токен) в $FREE_MODEL"
  out=$(docker exec opencode-student-sandbox timeout 60 opencode run -m "$FREE_MODEL" \
        "reply with just: ok" 2>&1 | tr '\n' ' ' | tail -c 300)
  case "$out" in
    *FreeUsageLimit*|*limit\ reached*|*429*) bad "лимит: ${out:0:160}" ;;
    *) ok "модель отвечает" ;;
  esac
fi
echo
