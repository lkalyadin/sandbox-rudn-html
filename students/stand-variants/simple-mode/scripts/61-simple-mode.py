#!/usr/bin/env python3
"""Переводит стенд из изолированного режима в «простой демо» (одноразовые стенды).

Что меняет (идемпотентно, с бэкапом):

1. `.env`: SANDBOX_RUNTIME=runc (без gVisor), SANDBOX_CPUS/MEMORY — под фактическое
   железо (по умолчанию 1 CPU и ~55 % RAM).
2. `docker-compose.yml`:
   - сеть `sandbox_net` перестаёт быть internal → у песочницы прямой интернет;
   - у сервиса sandbox убираются HTTP_PROXY/HTTPS_PROXY на egress и зависитмость
     от egress;
   - сервисы `egress` и `gateway` уходят в профили (не стартуют по умолчанию).
3. `scripts/31-up-fast.sh`: контейнеры egress/gateway и проверки прокси становятся
   необязательными (иначе чек всегда красный).

Запуск:  python3 scripts/61-simple-mode.py /srv/opencode
"""
import os
import re
import shutil
import sys

DEST = sys.argv[1] if len(sys.argv) > 1 else "/srv/opencode"
SANDBOX = os.path.join(DEST, "sandbox")
ENV = os.path.join(SANDBOX, ".env")
COMPOSE = os.path.join(SANDBOX, "docker-compose.yml")


def log(msg):
    print(" " + msg)


def patch_env():
    s = open(ENV).read()
    orig = s
    ncpu = os.cpu_count() or 1
    total_mb = 0
    for line in open("/proc/meminfo"):
        if line.startswith("MemTotal:"):
            total_mb = int(line.split()[1]) // 1024
    mem = max(768, min(int(total_mb * 0.55), 6144))
    s = re.sub(r"(?m)^SANDBOX_RUNTIME=.*$", "SANDBOX_RUNTIME=runc", s)
    s = re.sub(r"(?m)^SANDBOX_CPUS=.*$", "SANDBOX_CPUS=%d" % ncpu, s)
    s = re.sub(r"(?m)^SANDBOX_MEMORY=.*$", "SANDBOX_MEMORY=%dm" % mem, s)
    if s != orig:
        open(ENV, "w").write(s)
    log(".env: runtime=runc, cpus=%d, memory=%dm (хост: %d CPU / %d МБ)"
        % (ncpu, mem, ncpu, total_mb))


def patch_compose():
    s = open(COMPOSE).read()
    orig = s
    shutil.copyfile(COMPOSE, DEST + "/docker-compose.yml.bak-simple")

    # 1) сеть песочницы — с выходом в интернет
    s = s.replace("  sandbox_net:\n    internal: true\n", "  sandbox_net:\n    internal: false   # простой режим: прямой интернет\n")

    # 2) убрать прокси-переменные и зависимость от egress
    s = re.sub(r"(?m)^[ \t]*HTTP_PROXY: http://egress:8888\n", "", s)
    s = re.sub(r"(?m)^[ \t]*HTTPS_PROXY: http://egress:8888\n", "", s)
    s = re.sub(r"(?m)^[ \t]*NO_PROXY: .*\n", "", s)
    s = s.replace("    depends_on: [egress]\n", "")

    # 3) egress и gateway — в профили (проверяем каждый сервис отдельно:
    # после 59 в файле уже может быть profiles у gateway)
    if 'profiles: ["isolated"]' not in s:
        s = re.sub(r"(?m)^  egress:\n",
                   '  egress:\n    profiles: ["isolated"]   # изолированный режим: --profile isolated\n',
                   s, count=1)
    if 'profiles: ["gateway"]' not in s:
        s = re.sub(r"(?m)^  gateway:\n", '  gateway:\n    profiles: ["gateway"]\n', s, count=1)

    if s != orig:
        open(COMPOSE, "w").write(s)
    log("compose: sandbox_net → не internal, прокси убраны, egress/gateway в профилях")


def patch_check():
    path = os.path.join(SANDBOX, "scripts", "31-up-fast.sh")
    s = open(path).read()
    if 'OPT_RUNNING' in s:
        log("31-up-fast: уже учитывает опциональные сервисы")
        return
    # контейнеры: egress тоже может отсутствовать
    s = s.replace("for svc in sandbox egress edge upload-handler; do",
                  "for svc in sandbox edge upload-handler; do")
    s = s.replace("for svc in sandbox gateway egress edge upload-handler; do",
                  "for svc in sandbox edge upload-handler; do")
    marker = "GW_RUNNING=0\n"
    if marker in s:
        s = s.replace(marker,
                      "EG_RUNNING=0\n"
                      "if docker compose ps --format '{{.Service}}' 2>/dev/null | grep -qx egress; then\n"
                      "  EG_RUNNING=1\n"
                      "  ok \"egress работает (изолированный режим)\"\n"
                      "else\n"
                      "  warn \"egress не запущен — простой режим, у песочницы прямой интернет\"\n"
                      "fi\n"
                      "OPT_RUNNING=1\n" + marker, 1)
    open(path, "w").write(s)
    log("31-up-fast: egress учтён как опциональный")


if __name__ == "__main__":
    patch_env()
    patch_compose()
    patch_check()
    print("\nДальше:")
    print("  cd %s && docker compose up -d --remove-orphans" % SANDBOX)
    print("  docker compose restart sandbox")
