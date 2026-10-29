#!/usr/bin/env bash
# Дефолтный проект стенда: папка /work с именем "work".
#
# Зачем отдельный скрипт: в OpenCode «проект» — это рабочая папка. Имя проекта
# лежит в БД (opencode.db), а scripts/90-reset.sh базу чистит → после сброса
# проект /work появляется заново, но уже без имени (в UI видно путь "/work").
# Скрипт возвращает имя "work".
#
# Побочный эффект (нужный): создание сессии в /work поднимает time_active
# проекта. По активности OpenCode выбирает проект по умолчанию — так /work
# снова становится первым в списке.
#
# Идемпотентен и безопасен: если песочница не отвечает — молча выходит с 0,
# подъём стенда не ломается.
#
#   bash scripts/92-project-work.sh
set -uo pipefail
cd "$(dirname "$0")/.."

PROJECT_NAME="${PROJECT_NAME:-work}"

docker compose exec -T -e PROJECT_NAME="$PROJECT_NAME" sandbox python3 - <<'PY' 2>/dev/null || true
import json, os, base64, time, urllib.request, urllib.error

BASE = "http://127.0.0.1:4096"
NAME = os.environ.get("PROJECT_NAME", "work")
TOK = base64.b64encode(("opencode:" + os.environ["OPENCODE_SERVER_PASSWORD"]).encode()).decode()
HEAD = {"Authorization": "Basic " + TOK, "Content-Type": "application/json"}


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, headers=HEAD, method=method)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception:
        return 0, ""


def projects():
    st, d = req("GET", "/api/project")
    return d if st == 200 and isinstance(d, list) else []


# API поднимается не мгновенно после старта контейнера — ждём до минуты.
for _ in range(30):
    if projects():
        break
    time.sleep(2)

target = [p for p in projects() if p.get("canonical") == "/work"]
if not target:
    # Проекта ещё нет (после сброса БД). Сессия в /work создаёт проект.
    st, sess = req("POST", "/api/session?directory=/work", {"title": "stand-project-probe"})
    if st != 200:
        print("   !! проект /work: не удалось создать (API не отвечает)")
        raise SystemExit(0)
    sid = sess["data"]["id"] if isinstance(sess, dict) and "data" in sess else sess["id"]
    target = [p for p in projects() if p.get("canonical") == "/work"]
    if not target:
        print("   !! проект /work не появился")
        raise SystemExit(0)
    req("DELETE", "/api/session/" + sid)

pid = target[0]["id"]
if target[0].get("name") == NAME:
    print(f'   проект /work уже называется «{NAME}»')
else:
    st, res = req("PATCH", "/api/project/" + pid, {"name": NAME})
    if st == 200:
        print(f'   проект /work назван «{NAME}»')
    else:
        print("   !! не удалось переименовать проект /work:", res)
PY
