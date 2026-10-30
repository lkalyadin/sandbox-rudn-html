#!/usr/bin/env bash
# Подъём стенда после перезагрузки сервера — быстро и с самопроверкой.
#
# Отличие от scripts/30-up.sh: НЕ пересобирает образы (они уже собраны) и не
# трогает сертификат/htpasswd. Только поднимает контейнеры и проверяет, что
# всё живое. Годится и для «после ребута», и для «что-то упало».
#
# Использование:
#   sg docker -c "bash scripts/31-up-fast.sh"        # поднять и проверить
#   sg docker -c "bash scripts/31-up-fast.sh --check"  # только проверить
#
# После перезагрузки сервера контейнеры обычно поднимаются сами (docker
# включён в автозагрузку, у всех restart: unless-stopped). Этот скрипт
# нужен, чтобы: поднять то, что не поднялось; убедиться, что прокси к платным
# моделям жив; и получить внятный отчёт «всё зелёное / вот это сломано».
set -uo pipefail
cd "$(dirname "$0")/.."

check_only=false
[ "${1:-}" = "--check" ] && check_only=true

FAIL=0
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; FAIL=$((FAIL+1)); }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }

# Считаем, задана ли переменная в окружении контейнера. printenv печатает
# значение, поэтому пропускаем его через wc -l — сам секрет в вывод скрипта
# не попадает. Если переменной нет, printenv молчит и возвращает код 1.
count_env() { # $1 = имя контейнера, $2 = имя переменной
  docker exec "$1" printenv "$2" 2>/dev/null | wc -l | tr -d ' '
}

# ─── 1. Поднять контейнеры ───────────────────────────────────────────────────
if [ "$check_only" != "true" ]; then
  echo "==> Поднимаю контейнеры (без пересборки образов)"
  # shellcheck disable=SC1091
  set -a; . ./.env 2>/dev/null || true; set +a
  docker compose up -d 2>&1 | sed 's/^/  /' || bad "docker compose up -d не отработал"

  echo "==> Жду готовности песочницы (до 90 секунд)"
  deadline=$(( $(date +%s) + 90 ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if docker compose ps --status running --format '{{.Service}}' | grep -qx sandbox; then
      code=$(docker exec opencode-student-sandbox sh -lc \
        'curl -s -o /dev/null -w "%{http_code}" --max-time 5 -u opencode:"$OPENCODE_SERVER_PASSWORD" http://127.0.0.1:4096/api/model' 2>/dev/null || echo 000)
      [ "$code" = "200" ] && break
    fi
    sleep 2
  done

  # Дефолтный проект стенда: /work с именем "work" (после сброса БД имя теряется).
  bash scripts/92-project-work.sh
fi

# ─── 2. Контейнеры ───────────────────────────────────────────────────────────
echo
echo "==> Контейнеры"
for svc in sandbox gateway egress edge upload-handler; do
  if docker compose ps --status running --format '{{.Service}}' | grep -qx "$svc"; then
    ok "$svc работает"
  else
    bad "$svc НЕ РАБОТАЕТ (docker compose logs --tail=40 $svc)"
  fi
done

# ─── 3. Прокси к платным моделям (Vercel / OpenCode Go) ──────────────────────
# Ключи лежат в контейнере gateway, в песочнице их быть не должно.
# Если прокси мёртв, платные модели в UI не отвечают.
echo
echo "==> Прокси к платным моделям"
if [ "$(count_env opencode-student-gateway OPENCODE_GO_API_KEY)" = "1" ]; then
  ok "ключ OpenCode Go на месте (в контейнере gateway)"
else
  bad "в контейнере gateway нет ключа OPENCODE_GO_API_KEY — проверьте .env и docker compose up -d gateway"
fi

allowed=$(docker exec opencode-student-gateway sh -lc 'printenv GO_ALLOWED_MODELS' 2>/dev/null || echo "")
if [ -n "$allowed" ]; then
  ok "Go, белый список: $allowed"
else
  bad "GO_ALLOWED_MODELS пуст — прокси не пропустит ни одну модель Go"
fi

# Ключей в песочнице быть НЕ должно: агент читает /proc/self/environ.
leak=$(count_env opencode-student-sandbox OPENCODE_GO_API_KEY)
leak2=$(count_env opencode-student-sandbox AI_GATEWAY_API_KEY)
if [ "$leak" = "0" ] && [ "$leak2" = "0" ]; then
  ok "в песочнице ключей нет (это правильно)"
else
  bad "в песочнице виден ключ провайдера! Проверьте environment сервиса sandbox в docker-compose.yml"
fi

# ─── 4. Модели в UI ──────────────────────────────────────────────────────────
echo
echo "==> Модели в UI"
models_json=$(docker exec opencode-student-sandbox sh -lc \
  'curl -s -u opencode:"$OPENCODE_SERVER_PASSWORD" http://127.0.0.1:4096/api/model' 2>/dev/null || echo "")
if [ -z "$models_json" ]; then
  bad "не отвечает /api/model внутри песочницы"
else
  summary=$(printf '%s' "$models_json" | python3 -c '
import sys, json
from collections import Counter
d = json.load(sys.stdin)["data"]
c = Counter(m["providerID"] for m in d)
print(len(d), " ".join(f"{k}={v}" for k, v in sorted(c.items())))
' 2>/dev/null || echo "не разобрал")
  ok "$summary"

  # Набор моделей стенда: 3 бесплатных + 1 модель подписки. Посторонних нет.
  extra=$(printf '%s' "$models_json" | python3 -c '
import sys, json
expected = {
    "opencode": {"deepseek-v4.1-flash-free", "glm-5.3-flash-free", "mimo-v2.6-flash-free"},
    "muse-go": {"muse-spark-1.3-contributor"},
}
d = json.load(sys.stdin)["data"]
print(" ".join("%s/%s" % (m["providerID"], m["id"]) for m in d
      if m["id"] not in expected.get(m["providerID"], set())))
' 2>/dev/null || echo "не разобрал")
  if [ -z "$extra" ]; then
    ok "лишних моделей в UI нет (ожидаются 3 бесплатных + muse-spark-1.3-contributor)"
  else
    bad "в UI видны неожиданные модели: $extra"
  fi

  missing=$(printf '%s' "$models_json" | python3 -c '
import sys, json
expected = {
    "opencode": {"deepseek-v4.1-flash-free", "glm-5.3-flash-free", "mimo-v2.6-flash-free"},
    "muse-go": {"muse-spark-1.3-contributor"},
}
d = json.load(sys.stdin)["data"]
have = {(m["providerID"], m["id"]) for m in d}
print(" ".join("%s/%s" % (p, i) for p, ids in expected.items() for i in sorted(ids)
      if (p, i) not in have))
' 2>/dev/null || echo "не разобрал")
  if [ -z "$missing" ]; then
    ok "все ожидаемые модели на месте"
  else
    warn "нет моделей: $missing (проверьте config/opencode.json и провайдеры)"
  fi
fi

# ─── 5. Модели отвечают ──────────────────────────────────────────────────────
echo
echo "==> Проверка ответа моделей"
for m in opencode/deepseek-v4.1-flash-free muse-go/muse-spark-1.3-contributor; do
  ans=$(docker exec opencode-student-sandbox timeout 90 opencode run -m "$m" "say ok" 2>&1 \
    | sed 's/\x1b\[[0-9;]*m//g' | grep -viE "level=INFO" | tail -1)
  if printf '%s' "$ans" | grep -qiE "rate limit|error|не найден|not found"; then
    bad "$m: $ans"
  elif [ -n "$ans" ]; then
    ok "$m отвечает"
  else
    warn "$m: пустой ответ (возможно, прокси ещё не готов)"
  fi
done

# ─── 6. Внешний адрес ────────────────────────────────────────────────────────
echo
echo "==> Внешняя доступность"
if [ "${ENABLE_TLS:-true}" = "true" ]; then
  code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "https://127.0.0.1:${EDGE_HTTPS_PORT:-443}/" || true)
else
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:${EDGE_PORT:-80}/" || true)
fi
if printf '%s' "$code" | grep -qE '^[23]'; then
  ok "стенд отвечает снаружи (HTTP $code)"
else
  bad "стенд не отвечает снаружи (HTTP ${code:-нет})"
fi

# ─── Итог ────────────────────────────────────────────────────────────────────
echo
if [ "$FAIL" -eq 0 ]; then
  echo "==> Всё зелёное. Стенд готов к работе."
  exit 0
fi
echo "==> Проблем: $FAIL. Разбор:"
echo "    docker compose ps"
echo "    docker compose logs --tail=60 sandbox gateway egress"
echo "    bash scripts/50-verify-isolation.sh"
exit 1
