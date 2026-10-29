#!/usr/bin/env python3
"""Проверяет интерактив страницы, собранной через /opt/viz/kit.

Зачем. Skill.MD §9 требует проверить фильтры, клик по категории, скрытие
графиков, тёмную тему и отклонение невалидного конфига. Раньше каждая модель
писала для этого свой фреймворк (в одной сессии — 19 КБ и 9 запусков браузера,
12 минут). Здесь проверки универсальные: они дёргают публичный API движка
(window.DASH) и не зависят от датасета.

Запуск:
    python3 /opt/viz/kit/verify_page.py output/dashboard.html
    python3 /opt/viz/kit/verify_page.py output/dashboard.html --timeout 40

Код выхода 0 — всё зелёное, 1 — есть провалы, 2 — не удалось запустить.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import re
import sys
import tempfile

KIT_DIR = pathlib.Path(__file__).resolve().parent
VIZ_DIR = KIT_DIR.parent
sys.path.insert(0, str(VIZ_DIR))

from check_page import run_browser  # noqa: E402

RE_SELFTEST = re.compile(r'<pre id="dash-selftest-result">(.*?)</pre>', re.S)


def _decode(match: str) -> dict:
    raw = re.sub(r"\s+", "", match)
    text = base64.b64decode(raw).decode("utf-8", errors="replace")
    return json.loads(text)


def verify(path: pathlib.Path, timeout: int | None = None) -> int:
    html = path.read_text(encoding="utf-8")
    harness = (KIT_DIR / "selftest.js").read_text(encoding="utf-8")
    if "</body>" not in html:
        print("verify_page: в файле нет </body> — это не HTML-страница", file=sys.stderr)
        return 2

    # Вставляем проверку отдельным <script>, чтобы не трогать разметку страницы.
    page = html.replace("</body>", "<script>\n" + harness + "\n</script>\n</body>", 1)

    with tempfile.TemporaryDirectory() as tmp:
        probe = pathlib.Path(tmp) / ("selftest-" + path.name)
        probe.write_text(page, encoding="utf-8")
        if timeout:
            os.environ["CHECK_TIMEOUT"] = str(timeout)
        err, dom, fatal = run_browser("file://" + str(probe))

    if fatal:
        print(f"verify_page: браузер не смог проверить страницу — {fatal}", file=sys.stderr)
        return 2

    m = RE_SELFTEST.search(dom or "")
    if not m:
        print("verify_page: страница не выполнила автопроверку.", file=sys.stderr)
        print("  Обычно это значит, что движок упал до отрисовки, или страница "
              "собрана не через /opt/viz/kit.", file=sys.stderr)
        tail = "\n".join((err or "").splitlines()[-8:])
        if tail:
            print("  Последние строки лога браузера:\n" + tail, file=sys.stderr)
        return 1

    try:
        payload = _decode(m.group(1))
    except Exception as exc:                      # noqa: BLE001 — диагностика важнее
        print(f"verify_page: не разобрал результат проверки: {exc}", file=sys.stderr)
        return 2

    payload_error = payload.get("error") or ""
    if payload_error and "window.DASH" in payload_error and "dash-root" not in html:
        # Страница собрана вручную, а не конструктором: проверять нечего, и это
        # не повод считать работу красной. Достаточно check_page.py и скриншота.
        print(f"=== Интерактив: {path.name} ===")
        print("  Страница собрана не через /opt/viz/kit — автопроверка интерактива "
              "не применима.")
        print("  Проверьте её через check_page.py и скриншот (SKILL.md §10.3).")
        return 0

    print(f"=== Интерактив: {path.name} ===")
    failed = 0
    for item in payload.get("checks", []):
        mark = "OK  " if item.get("ok") else "ПРОВАЛ"
        print(f"  [{mark}] {item['name']} — {item.get('detail', '')}")
        if not item.get("ok"):
            failed += 1

    if payload.get("error"):
        print(f"  [ПРОВАЛ] {payload['error']}")
        failed += 1

    print()
    if failed:
        print(f"Провалов: {failed}. Поправьте spec/данные и соберите страницу заново.")
        return 1
    print("Интерактив в порядке: отбор, фильтры, скрытие графиков, тема, импорт.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Автопроверка интерактива дашборда")
    ap.add_argument("page", help="путь к собранной странице")
    ap.add_argument("--timeout", type=int, default=None,
                    help="сколько секунд ждать браузер (по умолчанию из check_page)")
    args = ap.parse_args(argv)
    path = pathlib.Path(args.page)
    if not path.is_file():
        print(f"verify_page: файл не найден: {path}", file=sys.stderr)
        return 2
    return verify(path, args.timeout)


if __name__ == "__main__":
    sys.exit(main())
