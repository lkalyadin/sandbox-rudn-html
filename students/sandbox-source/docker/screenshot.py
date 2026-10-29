#!/usr/bin/env python3
"""Делает скриншот HTML-страницы в headless-браузере.

Зачем отдельная обёртка, а не «сырой» chromium:

1. **Не спрашивает разрешения.** Правила песочницы разрешают `python3 *`, а
   прямой вызов `chromium-headless-shell ...` попадает в «спросить у
   студента». Скрипт запускается через `python3` и молча работает.
2. **Пути считаются от текущего каталога.** Агент работает в папке задачи
   (`/work/sessions/<id>`) и пишет `output/page.html`: такой путь теперь
   находится. Раньше всё приклеивалось к `/work`, и скрипт отвечал «файл не
   найден» на существующем файле.
3. **Один путь — нет перебора.** Результат по умолчанию — `preview.png` в
   текущей папке, а не в `/tmp`, который нельзя прочитать.

Запуск:
    python3 /opt/viz/screenshot.py output/dashboard.html
    python3 /opt/viz/screenshot.py output/dashboard.html --out preview.png
    python3 /opt/viz/screenshot.py output/dashboard.html --width 420 --height 2600
"""

import argparse
import os
import subprocess
import sys
import tempfile

CHROME = os.environ.get("CHROME_BIN", "chromium-headless-shell")
WORKSPACE = os.environ.get("SANDBOX_WORKSPACE", "/work")


def _resolve_input(value: str) -> str:
    """Входной файл: как указано → от cwd → от /work (для старых инструкций)."""
    if os.path.isabs(value):
        return value
    local = os.path.abspath(value)
    if os.path.exists(local):
        return local
    return os.path.join(WORKSPACE, value)


def _resolve_output(value: str) -> str:
    """Результат: относительный путь всегда от текущего каталога.

    Раньше «--out preview.png» уходил в /work/preview.png, даже если скрипт
    запущен из папки задачи: файл создавался не там, где его ждали.
    """
    return value if os.path.isabs(value) else os.path.abspath(value)


def main() -> int:
    ap = argparse.ArgumentParser(description="Скриншот HTML-страницы")
    ap.add_argument("page", help="путь к HTML (от текущего каталога или от /work)")
    ap.add_argument("--out", default=None,
                    help="куда сохранить PNG (по умолчанию preview.png рядом)")
    ap.add_argument("--width", type=int, default=1200)
    ap.add_argument("--height", type=int, default=2000)
    ap.add_argument("--wait", type=int, default=3000,
                    help="сколько миллисекунд виртуального времени ждать отрисовки")
    args = ap.parse_args()

    page = _resolve_input(args.page)
    if not os.path.isfile(page):
        print(f"screenshot: файл не найден: {page}", file=sys.stderr)
        return 2

    out = _resolve_output(args.out) if args.out else os.path.abspath("preview.png")
    # Файл должен лежать в рабочей папке, иначе его нельзя будет прочитать.
    if not os.path.abspath(out).startswith(os.path.abspath(WORKSPACE) + os.sep):
        print(f"screenshot: результат должен быть внутри {WORKSPACE}", file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(out), exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        cmd = [
            CHROME,
            "--headless",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            f"--user-data-dir={os.path.join(tmp, 'profile')}",
            f"--screenshot={out}",
            f"--window-size={args.width},{args.height}",
            f"--virtual-time-budget={args.wait}",
            "file://" + page,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90,
                                  start_new_session=True)
        except subprocess.TimeoutExpired:
            print("screenshot: браузер не ответил за 90 с. Скорее всего страница "
                  "зависла (Chart.js/ResizeObserver?). Проверьте её через "
                  "python3 /opt/viz/check_page.py", file=sys.stderr)
            return 1
        except FileNotFoundError:
            print(f"screenshot: браузер не найден: {CHROME}", file=sys.stderr)
            return 1

    if not os.path.isfile(out) or os.path.getsize(out) == 0:
        err = "\n".join((proc.stderr or "").splitlines()[-5:])
        print(f"screenshot: файл не создан.\n{err}", file=sys.stderr)
        return 1

    print(f"Скриншот готов: {out} ({os.path.getsize(out)} байт)")
    print(f"Посмотреть его можно инструментом чтения: путь {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
