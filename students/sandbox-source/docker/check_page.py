#!/usr/bin/env python3
"""Проверяет HTML-страницу настоящим браузером и печатает ошибки консоли.

Зачем это нужно. Агент собирает визуализацию, отдаёт ссылку, а страница
оказывается сломанной: в консоли браузера "Uncaught SyntaxError: Identifier
'top' has already been declared" — и студент видит пустую страницу. Раньше
агент мог только глазами перечитать код ("No browser. Rely on code review.").

Что делает скрипт:
  1. Открывает файл (или URL) в headless-браузере.
  2. Собирает ошибки: Uncaught-исключения и сообщения уровня ERROR.
     console.log/info печатается отдельным списком и проверку НЕ валит.
  3. Проверяет, что страница не тянет внешние скрипты/стили (CDN заблокированы,
     страница у студента будет пустой).
  4. Проверяет, что страница действительно отрисовалась: есть текст или
     графика, а canvas не нулевого размера.
  5. Печатает отчёт и возвращает 0 (всё чисто) или 1 (есть ошибки).

Запуск:
    python3 /opt/viz/check_page.py output/mtcars_dashboard.html
    python3 /opt/viz/check_page.py output/page.html            # путь от cwd
    CHECK_TIMEOUT=60 python3 /opt/viz/check_page.py output/page.html

Важно: код выхода 1 — это не «скрипт сломался», а «в странице есть ошибки».
"""

import os
import re
import signal
import subprocess
import sys
import tempfile
import time

CHROME = os.environ.get("CHROME_BIN", "chromium-headless-shell")
TIMEOUT = int(os.environ.get("CHECK_TIMEOUT", "25"))
# 2.5 с виртуального времени хватает статической странице с локальными
# данными. Прежние 8 с заставляли браузер досчитывать чужие таймеры и анимации,
# а при бесконечном цикле проверка висела все 25–40 секунд.
VIRTUAL_TIME = int(os.environ.get("CHECK_VIRTUAL_TIME", "2500"))
WORKSPACE = os.environ.get("SANDBOX_WORKSPACE", "/work")

# Шум, который не имеет отношения к странице.
NOISE = re.compile(
    r"dbus|UPower|GetAll|PropertiesChanged|gpu_|GPU|vulkan|Fontconfig|"
    r"Failed to connect to the bus|Cannot parse server address|"
    r"bluetooth|udev|Floss|bluez|libva|vaapi|swiftshader|"
    r"ozone|xdg_runtime_dir|Floss manager|GLES|egl|Skia|"
    r"Failed to create|dri3|DRM_|sandbox/policy",
    re.IGNORECASE,
)

# Сообщения консоли: [pid/timestamp:LEVEL:CONSOLE(12) "текст", source: X (line)]
# или [pid/timestamp:LEVEL:CONSOLE:2] "текст", source: X (line)
CONSOLE_RE = re.compile(
    r"(?P<level>INFO|WARNING|ERROR):CONSOLE[^\"]*\"(?P<msg>.*?)\"\s*,?\s*"
    r"(?:source:\s*(?P<source>[^,]+?))?\s*(?:\((?P<line>\d+)\))?\s*$"
)

# Внешние ресурсы в разметке: <script src="https://..."> и <link href="https://...">
EXTERNAL_RE = re.compile(
    r"""<(script|link|img|iframe)\b[^>]*\b(?:src|href)\s*=\s*["'](https?:)?//[^"']+""",
    re.IGNORECASE,
)

CANVAS_RE = re.compile(r"<canvas\b[^>]*>", re.IGNORECASE)
ZERO_CANVAS_RE = re.compile(
    r"""<canvas\b(?=[^>]*\bwidth\s*=\s*["']?0["']?)(?=[^>]*\bheight\s*=\s*["']?0["']?)[^>]*>""",
    re.IGNORECASE,
)
TAG_RE = re.compile(r"<[^>]+>")

HANG_HINTS = """Страница не отрисовалась за {timeout} с. Частые причины:
  1) Chart.js с responsive: true внутри flex/grid-контейнера без фиксированной
     высоты: ResizeObserver зацикливается, и headless Chromium зависает.
     Решение: height у контейнера, animation: false, responsive: false —
     или готовый движок /opt/viz/kit (там SVG, зависать нечему);
  2) бесконечный requestAnimationFrame / setInterval в вашем скрипте;
  3) гигантский DOM: сотни тысяч узлов из сырых строк данных.
  Быстрая проверка одной командой (без check_page):
    timeout 20 chromium-headless-shell --headless --no-sandbox --disable-gpu \\
      --virtual-time-budget=2000 --dump-dom file://<путь> > /dev/null; echo $?
  Поднять общий таймаут, если страница просто тяжёлая: CHECK_TIMEOUT=60 ...
"""


def die(msg, code=2):
    print(f"check_page: {msg}", file=sys.stderr)
    sys.exit(code)


def resolve_target(arg):
    """Путь к файлу: сначала как указано, потом от cwd, потом от /work.

    Раньше скрипт понимал только путь от /work, и агент, работая в своей папке
    задачи, получал «файл не найден» на абсолютно существующем файле.
    """
    if arg.startswith("http://") or arg.startswith("https://"):
        return arg, None
    candidates = []
    if os.path.isabs(arg):
        candidates.append(arg)
    else:
        candidates.append(os.path.abspath(arg))
        candidates.append(os.path.join(WORKSPACE, arg))
    for path in candidates:
        if os.path.isfile(path):
            return "file://" + path, path
    die("файл не найден: %s (искал: %s)" % (arg, ", ".join(candidates)))


def _run(cmd, profile, timeout):
    """Запускает браузер, гарантированно убивая всю группу процессов."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "HOME": profile},
        # Своя группа процессов: если браузер завис, убьём её целиком и не
        # оставим сирот в песочнице.
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
        return out or "", err or "", proc.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            proc.kill()
        try:
            proc.communicate(timeout=5)
        except Exception:
            pass
        return "", "", "timeout"


def run_browser(target, timeout=None):
    """Открывает target в браузере, возвращает (stderr, dom, fatal)."""
    timeout = timeout or TIMEOUT
    with tempfile.TemporaryDirectory() as tmp:
        profile = os.path.join(tmp, "profile")
        base = [
            CHROME,
            "--headless",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--no-first-run",
            # Внутренняя проверка: адрес edge (172.28.0.5) не совпадает с
            # именем в сертификате (сертификат выдан на IP стенда). На внешний
            # вид страницы это не влияет — проверяем код, а не TLS.
            "--ignore-certificate-errors",
            "--disable-features=Translate,MediaRouter",
            f"--user-data-dir={profile}",
            "--enable-logging=stderr",
            f"--virtual-time-budget={VIRTUAL_TIME}",
            "--dump-dom",
        ]

        dom, err, rc = _run(base + [target], profile, timeout)
        if rc == "timeout":
            return "", "", HANG_HINTS.format(timeout=timeout)

        # Под gVisor процессы chromium иногда не стартуют. Пробуем
        # однопроцессный режим — он работает везде, но только как запасной
        # вариант: он же и падает чаще.
        if not dom.strip() and rc != 0:
            dom2, err2, _ = _run(
                base + ["--single-process", "--no-zygote", target], profile, timeout
            )
            err = (err or "") + (err2 or "")
            dom = dom2 or ""

    return err, dom, ""


def collect_messages(stderr):
    """Разбирает лог браузера на ошибки, предупреждения и обычные сообщения."""
    errors, warnings, infos = [], [], []
    seen = set()
    for line in stderr.splitlines():
        if NOISE.search(line):
            continue
        m = CONSOLE_RE.search(line)
        if not m:
            continue
        msg = m.group("msg").strip()
        if not msg or msg in seen:
            continue
        seen.add(msg)
        src = m.group("source") or ""
        ln = m.group("line") or ""
        where = f"{src}:{ln}" if src and ln else (src or "")
        entry = msg + (f"  ({where})" if where else "")
        level = m.group("level")
        if level == "ERROR":
            errors.append(entry)
        elif level == "WARNING":
            warnings.append(entry)
        else:
            infos.append(entry)
    return errors, warnings, infos


def check_rendered(dom, errors, warnings):
    """Проверяет, что страница действительно отрисовалась."""
    text = TAG_RE.sub(" ", dom)
    text = re.sub(r"\s+", " ", text).strip()
    has_graphics = bool(re.search(r"<(svg|canvas|table)\b", dom, re.IGNORECASE))
    if len(text) < 10 and not has_graphics:
        errors.append("страница пустая: в DOM нет ни текста, ни графики")
    zero = ZERO_CANVAS_RE.findall(dom)
    if zero:
        warnings.append(
            f"canvas нулевого размера: {len(zero)} — график, скорее всего, не виден")
    return len(text)


def main():
    if len(sys.argv) < 2:
        die("укажите файл или URL: python3 check_page.py <файл|url>")
    arg = sys.argv[1]
    target, local_path = resolve_target(arg)

    started = time.time()
    err, dom, fatal = run_browser(target)
    elapsed = time.time() - started

    if fatal:
        die(fatal)

    errors, warnings, infos = collect_messages(err)
    text_len = check_rendered(dom, errors, warnings)

    external = []
    if local_path:
        try:
            with open(local_path, encoding="utf-8", errors="replace") as fh:
                html = fh.read()
            for m in EXTERNAL_RE.finditer(html):
                external.append(m.group(0)[:120])
        except OSError:
            pass

    print(f"=== Проверка страницы: {arg} ({elapsed:.1f} с, DOM {len(dom) // 1024} КБ, текста {text_len} символов)")
    if not dom.strip():
        print("!! Браузер не отдал DOM — страница, скорее всего, не отрисовалась.")
        errors.append("пустой DOM: страница не отрисовалась")

    if external:
        print(f"!! Внешние ресурсы ({len(external)}): CDN заблокированы, у студента будет пустая страница")
        for e in external[:10]:
            print(f"   {e}")
        errors.append(f"внешние ресурсы в разметке: {len(external)}")

    if errors:
        print(f"!! Ошибок: {len(errors)}")
        for e in errors:
            print(f"   {e}")
    else:
        print("✓ Ошибок нет")

    if warnings:
        print(f"   Предупреждений: {len(warnings)}")
        for w in warnings[:10]:
            print(f"   ~ {w}")

    if infos:
        print(f"   Сообщений console.log: {len(infos)} (проверку не валят)")
        for i in infos[:5]:
            print(f"   · {i}")

    if errors:
        print()
        print("Исправь файл и запусти проверку заново. Ссылку студенту давай только "
              "после того, как здесь написано «✓». Если страница собрана через "
              "/opt/viz/kit, добавь ещё: python3 /opt/viz/kit/verify_page.py <файл>")
        return 1

    print()
    print("Страница открывается без ошибок. Можно отдавать ссылку.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
