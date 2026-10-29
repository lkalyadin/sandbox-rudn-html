#!/usr/bin/env python3
"""Резервный стенд: «режим без ограничений» + без навыка визуализации.

Применяется ТОЛЬКО на конкретном стенде (канонический скелет не трогаем).

1. config/opencode.json:
   - permissions → всё allow (shell без спроса, webfetch/websearch, чтение .env,
     внешние каталоги);
   - из policies убираются запреты tool.use (sudo/ssh/curl/...);
   - instructions чистится (навык визуализации не подключается);
   - policies provider.* остаются: иначе в UI всплывут сотни платных моделей
     каталоговых провайдеров.
2. docker-compose.yml: у песочницы убираются mem_limit и cpus (лимиты CPU/RAM),
   снимается монтирование навыка economist-sandbox и hallmark.
3. /work/opencode.json + workspace.template: из скрытых остаётся только
   big-pickle (реально не работает), остальные 8 бесплатных моделей видны.
"""
import json
import os
import re
import shutil
import subprocess
import sys

DEST = sys.argv[1] if len(sys.argv) > 1 else "/srv/opencode"
SANDBOX = os.path.join(DEST, "sandbox")
CONFIG = os.path.join(SANDBOX, "config/opencode.json")
COMPOSE = os.path.join(SANDBOX, "docker-compose.yml")

OPEN_PERMS = '''  "permissions": [
    { "action": "external_directory", "resource": "*", "effect": "allow" },
    { "action": "webfetch",  "resource": "*", "effect": "allow" },
    { "action": "websearch", "resource": "*", "effect": "allow" },
    { "action": "shell", "resource": "*", "effect": "allow" },
    { "action": "read",  "resource": "*", "effect": "allow" },
    { "action": "edit",  "resource": "*", "effect": "allow" }
  ]
'''


def find_block(s, start_marker, open_ch, close_ch):
    i = s.index(start_marker)
    j = s.index(open_ch, i)
    depth = 0
    for k in range(j, len(s)):
        if s[k] == open_ch:
            depth += 1
        elif s[k] == close_ch:
            depth -= 1
            if depth == 0:
                return i, k + 1
    raise ValueError("не нашёл конец блока " + start_marker)


def patch_config():
    s = open(CONFIG).read()
    shutil.copyfile(CONFIG, CONFIG + ".bak-reserve")

    i, j = find_block(s, '"permissions": [', "[", "]")
    s = s[:i] + OPEN_PERMS.rstrip("\n") + s[j:]

    # tool.use запреты — убрать (политики провайдеров оставить)
    s = re.sub(r'\n[ \t]*\{ "action": "tool\.use"[^\n]*\},?', "", s)

    # инструкции на стенде не нужны (навык визуализации не подключаем)
    i, j = find_block(s, '"instructions": [', "[", "]")
    s = s[:i] + '"instructions": []' + s[j:]

    # после вырезания строк в массивах могли остаться висячие запятые
    # (учитываем и строки комментариев между запятой и закрывающей скобкой)
    s = re.sub(r",(\s*(?://[^\n]*\n\s*)*[\]}])", r"\1", s)
    s = re.sub(r",(\s*[\]}])", r"\1", s)

    plain = "\n".join(l for l in s.splitlines() if not l.strip().startswith("//"))
    json.loads(plain)          # сначала проверяем, потом пишем
    open(CONFIG, "w").write(s)
    print("config: permissions → allow, tool.use запреты сняты, instructions пуст")


def patch_compose():
    s = open(COMPOSE).read()
    shutil.copyfile(COMPOSE, COMPOSE + ".bak-reserve")
    s = re.sub(r"(?m)^[ \t]*mem_limit: .*\n", "", s)
    s = re.sub(r"(?m)^[ \t]*cpus: .*\n", "", s)
    s = re.sub(r"(?m)^[ \t]*- \./skills/economist-sandbox:[^\n]*\n", "", s)
    s = re.sub(r"(?m)^[ \t]*- \./skills/hallmark:[^\n]*\n", "", s)
    open(COMPOSE, "w").write(s)
    print("compose: mem_limit/cpus убраны, навыки visual/hallmark не монтируются")


def patch_project_models():
    data = {
        "$schema": "https://opencode.ai/config.json",
        "providers": {"opencode": {"models": {"big-pickle": {"disabled": True}}}},
    }
    body = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tpl = os.path.join(SANDBOX, "workspace.template", "opencode.json")
    open(tpl, "w").write(body)
    cmd = ["docker", "exec", "-i", "opencode-student-sandbox", "sh", "-c",
           "cat > /work/opencode.json"]
    subprocess.run(cmd, input=body, text=True, check=False)
    print("модели: скрыт только big-pickle (в шаблоне и в /work)")


if __name__ == "__main__":
    patch_config()
    patch_compose()
    patch_project_models()
    print("\nДальше: cd %s && docker compose up -d && docker compose restart sandbox" % SANDBOX)
