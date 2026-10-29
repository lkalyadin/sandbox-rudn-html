#!/usr/bin/env python3
"""Собирает САМОДОСТАТОЧНУЮ HTML-страницу: библиотека вшивается в файл целиком.

Зачем так: в песочнице нет интернета, поэтому ссылки на CDN
(`cdn.jsdelivr.net`, `unpkg.com` и подобные) не загрузятся — студент откроет
пустую страницу без всякой ошибки. Поэтому содержимое библиотеки вставляется
прямо в `<script>`, а данные — прямо в `<script>const DATA = ...</script>`.

Библиотеки лежат в образе, в /opt/viz (Chart.js, Plotly basic, D3 — см. HANDOFF §7).

Как пользоваться из своего скрипта:

    from inline_chart import build_page
    build_page(
        "output/sales.html",
        "Продажи по регионам",
        lib="chart.umd.min.js",
        data={"labels": [...], "values": [...]},
        script=\"\"\"
            new Chart(document.getElementById("chart"), {
              type: "bar",
              data: { labels: DATA.labels,
                      datasets: [{ label: "Выручка", data: DATA.values }] }
            });
        \"\"\",
    )

Или из командной строки:
    python3 inline_chart.py -o output/sales.html --title "Продажи" \
        --lib chart.umd.min.js --script build_chart.js

Про matplotlib и plotly помни отдельно:
  * matplotlib — проще всего: сохранить PNG или SVG и вставить в HTML (base64).
  * plotly     — только `fig.write_html(path, include_plotlyjs=True)`:
                 по умолчанию plotly пишет include_plotlyjs='cdn', и график
                 не появится вовсе.
"""

from __future__ import annotations

import argparse
import html
import json
import pathlib

VIZ_DIR = pathlib.Path("/opt/viz")


def _safe_js(source: str) -> str:
    """Не даёт JS-содержимому закрыть тег <script> раньше времени."""
    return source.replace("</script>", "<\\/script>")


def build_page(
    path: str,
    title: str,
    script: str,
    *,
    lib: str | None = None,
    head: str = "",
    data: object | None = None,
) -> str:
    """Пишет однофайловую страницу и возвращает её путь."""
    parts = [
        "<!doctype html>",
        '<html lang="ru"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{html.escape(title)}</title>",
    ]
    if head:
        parts.append(f"<style>{head}</style>")
    if data is not None:
        parts.append(
            "<script>const DATA = "
            + _safe_js(json.dumps(data, ensure_ascii=False))
            + ";</script>"
        )
    if lib:
        js = (VIZ_DIR / lib).read_text(encoding="utf-8")
        parts.append(f"<script>{_safe_js(js)}</script>")
    parts += [
        "</head><body>",
        f"<h1>{html.escape(title)}</h1>",
        '<div id="chart"></div>',
        f"<script>{_safe_js(script)}</script>",
        "</body></html>",
    ]

    out = pathlib.Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts), encoding="utf-8")
    return str(out)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Собирает самодостаточную HTML-страницу с графиком"
    )
    parser.add_argument("-o", "--out", required=True, help="куда положить HTML")
    parser.add_argument("--title", required=True)
    parser.add_argument("--lib", default=None, help="файл из /opt/viz, напр. chart.umd.min.js")
    parser.add_argument("--script", required=True, help="файл с вашим JS-кодом графика")
    args = parser.parse_args()

    script = pathlib.Path(args.script).read_text(encoding="utf-8")
    print(build_page(args.out, args.title, script, lib=args.lib))


if __name__ == "__main__":
    main()
