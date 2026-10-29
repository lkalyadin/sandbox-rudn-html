#!/usr/bin/env python3
"""Адаптирует стенд под режим «только бесплатные модели opencode».

Применяется на стенде (не в бандле), идемпотентно:

1. config/opencode.json — убирает провайдер `vercel-free` и разрешение
   provider.use для него; дефолтная модель остаётся opencode/deepseek-v4.1-flash-free.
2. /work/opencode.json + workspace.template/opencode.json — скрывает все модели
   opencode, кроме beam-free, deepseek-v4.1-flash-free, glm-5.3-flash-free,
   mimo-v2.6-flash-free (правило 10: скрываем в project-конфиге, чтобы студент
   мог вернуть сам).
3. docker-compose.yml — сервис gateway переводится в профиль `gateway`:
   `docker compose up -d` его больше не поднимает (вернуть:
   `docker compose --profile gateway up -d gateway`).
4. scripts/31-up-fast.sh — проверки шлюза становятся необязательными.
"""
import json
import re
import sys

DEST = sys.argv[1] if len(sys.argv) > 1 else "/srv/opencode"
KEEP = {"beam-free", "deepseek-v4.1-flash-free", "glm-5.3-flash-free", "mimo-v2.6-flash-free"}
HIDE = ["flint-40b-free", "nemotron-3-ultra-free", "nemotron-3.5-lightning-free",
        "nemotron-3.5-super-vl-free", "big-pickle"]


def strip_jsonc(text):
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("//"):
            continue
        out.append(re.sub(r"\s+//.*$", "", line) if '"' not in line else line)
    return "\n".join(out)


def patch_config(path):
    s = open(path).read()
    if '"vercel-free"' not in s:
        return "config: уже без vercel-free"
    # вырезаем объект провайдера целиком
    i = s.index('"vercel-free": {')
    line_start = s.rindex("\n", 0, i) + 1
    j = s.index("{", i)
    depth = 0
    for k in range(j, len(s)):
        if s[k] == "{":
            depth += 1
        elif s[k] == "}":
            depth -= 1
            if depth == 0:
                end = k + 1
                break
    rest = s[end:]
    if rest.lstrip().startswith(","):
        end += len(rest) - len(rest.lstrip()) + 1
    s = s[:line_start] + s[end:]
    # вырезаем разрешение провайдера в policies
    s = re.sub(r'\n[ \t]*\{ "action": "provider\.use", "resource": "vercel-free", "effect": "allow" \},', "", s)
    # устаревший комментарий про «разрешён провайдер vercel-free»
    s = re.sub(r"\n[ \t]*// ВРЕМЕННО \(до 2026-10-22\):[^\n]*\n[ \t]*//[^\n]*\n[ \t]*//[^\n]*\n[ \t]*//[^\n]*\n[ \t]*//[^\n]*\n", "\n", s)
    s = re.sub(r"// ─── ВРЕМЕННО \(до 2026-10-22\): провайдер Vercel AI Gateway [^\n]*\n",
               "// ─── Vercel AI Gateway ОТКЛЮЧЁН 28.10.2026 (стенд только на бесплатных opencode)\n"
               "// Вернуть: блок \"provider\" → \"vercel-free\" + provider.use allow +\n"
               "// docker compose --profile gateway up -d gateway (см. HANDOFF).\n", s)
    open(path, "w").write(s)
    try:
        json.loads(strip_jsonc(s))
    except Exception as e:
        raise SystemExit("config/opencode.json стал невалидным: %s" % e)
    return "config: vercel-free убран"


def patch_project_config(path):
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        "$schema": "https://opencode.ai/config.json",
        "providers": {"opencode": {"models": {m: {"disabled": True} for m in HIDE}}},
    }
    try:
        open(path, "w").write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    except PermissionError:
        return ("project config: нет прав на %s (uid 1000) — запишите через контейнер:\n"
                "    docker exec -i opencode-student-sandbox sh -c 'cat > %s' < файл.json" % (path, path))
    return "project config: скрыто %d моделей" % len(HIDE)


def patch_compose(path):
    s = open(path).read()
    if "profiles:" in s and 'gateway' in s and 'profiles: ["gateway"]' in s:
        return "compose: gateway уже в профиле"
    s2 = re.sub(r"(?m)^  gateway:\n", '  gateway:\n    profiles: ["gateway"]   # не поднимается без --profile gateway\n', s, count=1)
    if s2 == s:
        return "compose: сервис gateway не найден (пропущено)"
    open(path, "w").write(s2)
    return "compose: gateway → профиль gateway"


def patch_check(path):
    s = open(path).read()
    if "GW_RUNNING" in s:
        return "31-up-fast: уже пропатчен"

    # 1) контейнеры: gateway больше не обязателен
    s = s.replace(
        "for svc in sandbox gateway egress edge upload-handler; do",
        "for svc in sandbox egress edge upload-handler; do")
    marker = '    bad "$svc НЕ РАБОТАЕТ (docker compose logs --tail=40 $svc)"\n  fi\ndone\n'
    s = s.replace(marker, marker + '''# gateway опционален: на стендах без провайдера vercel-free он в профиле compose
GW_RUNNING=0
if docker compose ps --format '{{.Service}}' 2>/dev/null | grep -qx gateway; then
  GW_RUNNING=1
  ok "gateway работает (провайдер vercel-free включён)"
else
  warn "gateway не запущен — стенд только на бесплатных opencode (проверки шлюза пропущены)"
fi
''', 1)

    # 2) блок про прокси — только если шлюз работает
    start = 'echo "==> Прокси к Vercel AI Gateway"\n'
    end = "# ─── 4. Модели в UI"
    i, j = s.index(start), s.index(end)
    body = s[i + len(start):j]
    s = s[:i] + start + 'if [ "$GW_RUNNING" = "1" ]; then\n' + body + \
        'else\n  warn "провайдер vercel-free на этом стенде не используется"\nfi\n\n' + s[j:]

    # 3) живой ответ: шлюзовые модели или модель по умолчанию
    start = "for m in vercel-free/zai/glm-5.3-flash vercel-free/reflection/beam-free; do"
    end = "# ─── 6. Внешний адрес"
    i, j = s.index(start), s.index(end)
    body = s[i:j]
    s = s[:i] + 'if [ "$GW_RUNNING" = "1" ]; then\n' + \
        "for m in vercel-free/zai/glm-5.3-flash vercel-free/reflection/beam-free; do" + \
        body[len(start):] + \
        'else\n' \
        "  m=$(sed -n 's/.*\"model\": *\"\\([^\"]*\\)\".*/\\1/p' config/opencode.json | head -1)\n" \
        '  ans=$(docker exec opencode-student-sandbox timeout 90 opencode run -m "$m" "say ok" 2>&1 | sed "s/\\x1b\\[[0-9;]*m//g" | grep -viE "level=INFO" | tail -1)\n' \
        '  if printf "%s" "$ans" | grep -qiE "FreeUsageLimit|rate limit|not found"; then\n' \
        '    bad "$m: $ans"\n' \
        '  elif [ -n "$ans" ]; then\n' \
        '    ok "$m отвечает"\n' \
        '  else\n' \
        '    warn "$m: пустой ответ"\n' \
        '  fi\n' \
        'fi\n\n' + s[j:]
    open(path, "w").write(s)
    return "31-up-fast: проверки шлюза сделаны необязательными"


if __name__ == "__main__":
    sandbox = DEST + "/sandbox"
    print(patch_config(sandbox + "/config/opencode.json"))
    print(patch_compose(sandbox + "/docker-compose.yml"))
    print(patch_check(sandbox + "/scripts/31-up-fast.sh"))
    for p in (DEST + "/workspace/opencode.json", sandbox + "/workspace.template/opencode.json"):
        print(patch_project_config(p), "→", p)
