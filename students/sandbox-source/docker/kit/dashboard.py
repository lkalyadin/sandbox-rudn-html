#!/usr/bin/env python3
"""Сборщик автономной HTML-страницы дашборда (/opt/viz/kit/dashboard.py).

Зачем этот файл. Требования Skill.MD к странице (§2–§7) не зависят от
датасета: две иконки в шапке, панель настроек с двумя вкладками, наследование
настроек, Top N и «Остальные», сохранение автономного HTML, блок Skill.MD.
Раньше агент каждый раз писал эти ~50 КБ JavaScript заново и тратил на отладку
20–30 минут. Здесь движок один раз протестирован, а от модели требуется только
описать задачу в JSON (KPI, фильтры, показатели, графики) и подготовить данные.

Как пользоваться:

    python3 /opt/viz/kit/dashboard.py --spec spec.json --out output/page.html

Или из своего Python-скрипта:

    from dashboard import build
    build(spec, out="output/page.html")

spec.json — см. README.md рядом. Минимально:

    {
      "title": "Безработица по странам",
      "question": "Где безработица выше и как она менялась?",
      "theme": "almanac",
      "data": {"columns": ["country", "year", "unemp"],
               "rows": [["Германия", 2020, 3.4], ...]},
      "kpis": [{"label": "Стран", "agg": {"fn": "count_distinct", "column": "country"}}],
      "filters": [{"id": "year", "label": "Год", "column": "year", "default": "last"}],
      "dimensions": {"country": {"label": "Страна"}, "year": {"label": "Год", "ordered": true}},
      "measures": {"unemp": {"label": "Безработица", "column": "unemp", "unit": "%", "agg": "mean"}},
      "charts": [{"id": "top", "title": "Топ-15", "type": "hbar",
                  "dimension": "country", "measure": "unemp", "topN": 15, "rest": "mean"}]
    }
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import sys
from typing import Any

KIT_DIR = pathlib.Path(__file__).resolve().parent
DEFAULT_SKILL = pathlib.Path("/etc/opencode/skills/economist-sandbox/SKILL.md")
MAX_ROWS = 100_000

AGG_FUNCS = {"mean", "sum", "min", "max", "median", "first", "last",
             "count", "count_distinct", "share"}
CHART_TYPES = {"hbar", "vbar", "line", "table"}
REST_MODES = {"mean", "sum", "min", "max", "median", "first", "last", "count", None}


class SpecError(ValueError):
    """Ошибка в spec: печатаем понятный текст, а не трассировку."""


# ─────────────────────────────── подготовка ─────────────────────────────────

def _clean(value: Any) -> Any:
    """Приводит значение к JSON-виду: NaN → null, numpy/pandas → Python."""
    if value is None:
        return None
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, str)):
        return value
    if hasattr(value, "item"):          # numpy-скаляр, pandas.Timestamp → item()
        try:
            return _clean(value.item())
        except (ValueError, AttributeError):
            return str(value)
    if hasattr(value, "isoformat"):     # datetime/date
        return value.isoformat()
    return str(value)


def _normalise_data(raw: Any) -> dict:
    """Принимает {columns, rows} или список словарей; возвращает {columns, rows}."""
    if isinstance(raw, dict) and "columns" in raw and "rows" in raw:
        columns = [str(c) for c in raw["columns"]]
        rows = [[_clean(v) for v in row] for row in raw["rows"]]
        for i, row in enumerate(rows):
            if len(row) != len(columns):
                raise SpecError(
                    f"данные: строка {i} содержит {len(row)} значений, "
                    f"а колонок {len(columns)}")
        return {"columns": columns, "rows": rows}

    if isinstance(raw, list):
        if not raw:
            raise SpecError("данные: пустой список строк")
        if not isinstance(raw[0], dict):
            raise SpecError("данные: ожидался список словарей (по ключу на колонку)")
        columns: list[str] = []
        for item in raw:
            for key in item:
                if key not in columns:
                    columns.append(str(key))
        rows = [[_clean(item.get(c)) for c in columns] for item in raw]
        return {"columns": columns, "rows": rows}

    raise SpecError("данные: ожидался объект {columns, rows} или список словарей")


def _load_data(spec: dict, spec_path: pathlib.Path | None) -> dict:
    if "data" in spec:
        return _normalise_data(spec["data"])
    if "data_file" in spec:
        path = pathlib.Path(spec["data_file"])
        if not path.is_absolute() and spec_path:
            path = spec_path.parent / path
        if not path.is_file():
            raise SpecError(f"data_file не найден: {path}")
        return _normalise_data(json.loads(path.read_text(encoding="utf-8")))
    raise SpecError("в spec нет данных: добавьте блок \"data\" или \"data_file\"")


def _validate(spec: dict, data: dict) -> None:
    columns = set(data["columns"])
    if len(data["rows"]) > MAX_ROWS:
        raise SpecError(
            f"строк {len(data['rows'])}, а предел {MAX_ROWS}: агрегируйте данные "
            f"в Python (средние/KPI/группы) и оставьте в странице только нужные разрезы")

    for key in ("title", "question"):
        if not isinstance(spec.get(key, ""), str):
            raise SpecError(f"{key}: ожидалась строка")

    dims = spec.get("dimensions")
    if not isinstance(dims, dict) or not dims:
        raise SpecError("dimensions: нужен объект вида {\"country\": {\"label\": \"Страна\"}}")
    for name, meta in dims.items():
        if name not in columns:
            raise SpecError(f"dimensions.{name}: такой колонки нет в данных ({', '.join(data['columns'])})")
        if not isinstance(meta, dict):
            raise SpecError(f"dimensions.{name}: ожидался объект с label")

    measures = spec.get("measures")
    if not isinstance(measures, dict) or not measures:
        raise SpecError("measures: нужен объект вида {\"gini\": {\"label\": ..., \"column\": ...}}")
    for name, meta in measures.items():
        if not isinstance(meta, dict):
            raise SpecError(f"measures.{name}: ожидался объект")
        agg = meta.get("agg", "mean")
        if agg not in AGG_FUNCS:
            raise SpecError(f"measures.{name}.agg: допустимо {sorted(AGG_FUNCS)}")
        column = meta.get("column", name)
        if agg not in ("count",) and column not in columns:
            raise SpecError(f"measures.{name}.column: колонки {column!r} нет в данных")
        if agg == "count" and column not in columns and column != name:
            raise SpecError(f"measures.{name}: для count укажите column или уберите column")
        if agg == "share" and "equals" not in meta:
            raise SpecError(f"measures.{name}: для доли нужен \"equals\" — какое значение считается положительным")

    filters = spec.get("filters", [])
    if not isinstance(filters, list):
        raise SpecError("filters: ожидался массив")
    if len(filters) > 3:
        raise SpecError(f"фильтров {len(filters)}, а Skill.MD §10.4 разрешает не больше 3")
    seen_filters = set()
    for i, f in enumerate(filters):
        if not isinstance(f, dict) or "column" not in f:
            raise SpecError(f"filters[{i}]: нужны id, label, column")
        if f["column"] not in columns:
            raise SpecError(f"filters[{i}].column: колонки {f['column']!r} нет в данных")
        fid = f.get("id") or f["column"]
        if fid in seen_filters:
            raise SpecError(f"filters: повторяется id {fid}")
        seen_filters.add(fid)
        if f.get("default") not in (None, "last"):
            raise SpecError(f"filters[{i}].default: допустимо только \"last\" или отсутствие")

    charts = spec.get("charts")
    if not isinstance(charts, list) or not charts:
        raise SpecError("charts: нужен непустой массив графиков")
    if len(charts) > 6:
        raise SpecError(f"графиков {len(charts)}, а Skill.MD §10.4 разрешает не больше 6")
    seen_charts = set()
    for i, c in enumerate(charts):
        if not isinstance(c, dict):
            raise SpecError(f"charts[{i}]: ожидался объект")
        cid = c.get("id")
        if not cid or not isinstance(cid, str):
            raise SpecError(f"charts[{i}].id: нужен строковый id")
        if cid in seen_charts:
            raise SpecError(f"charts: повторяется id {cid}")
        seen_charts.add(cid)
        if c.get("dimension") not in dims:
            raise SpecError(f"charts[{i}].dimension: должно быть одно из {sorted(dims)}")
        if c.get("measure") not in measures:
            raise SpecError(f"charts[{i}].measure: должно быть одно из {sorted(measures)}")
        ctype = c.get("type", "hbar")
        if ctype not in CHART_TYPES:
            raise SpecError(f"charts[{i}].type: допустимо {sorted(CHART_TYPES)}")
        if c.get("rest") not in REST_MODES:
            raise SpecError(f"charts[{i}].rest: допустимо {sorted(x for x in REST_MODES if x)} или null")

    kpis = spec.get("kpis", [])
    if not isinstance(kpis, list):
        raise SpecError("kpis: ожидался массив")
    if len(kpis) > 4:
        raise SpecError(f"KPI {len(kpis)}, а Skill.MD §2 просит 3–4 показателя")
    for i, k in enumerate(kpis):
        if not isinstance(k, dict) or not k.get("label"):
            raise SpecError(f"kpis[{i}]: нужны label и agg")
        agg = k.get("agg")
        if isinstance(agg, str):
            fn = agg
            column = k.get("column")
        elif isinstance(agg, dict):
            fn = agg.get("fn", "count")
            column = agg.get("column", k.get("column"))
        else:
            raise SpecError(f"kpis[{i}].agg: ожидался объект {{\"fn\": ..., \"column\": ...}}")
        if fn not in AGG_FUNCS:
            raise SpecError(f"kpis[{i}].agg.fn: допустимо {sorted(AGG_FUNCS)}")
        if fn not in ("count",) and column not in columns:
            raise SpecError(f"kpis[{i}]: колонки {column!r} нет в данных")


def _defaults(spec: dict) -> dict:
    """Достраивает то, что можно не писать руками."""
    spec.setdefault("theme", "almanac")
    spec.setdefault("decimals", 1)
    spec.setdefault("filters", [])
    spec.setdefault("kpis", [])
    for fid_filter in spec["filters"]:
        fid_filter.setdefault("id", fid_filter["column"])
        fid_filter.setdefault("label", fid_filter["column"])
    for name, meta in spec["dimensions"].items():
        meta.setdefault("label", name)
    for name, meta in spec["measures"].items():
        meta.setdefault("label", name)
        meta.setdefault("column", name)
        meta.setdefault("agg", "mean")
        meta.setdefault("unit", "")
    for i, chart in enumerate(spec["charts"]):
        chart.setdefault("type", "hbar")
        chart.setdefault("topN", None)
        chart.setdefault("rest", "mean" if chart.get("topN") else None)
        chart.setdefault("sort", None)
        chart.setdefault("note", "")
        chart.setdefault("title", f"График {i + 1}")
    return spec


def _escape_for_script(payload: Any) -> str:
    """JSON, который безопасно вставить внутрь <script>."""
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return (text.replace("</", "<\\/")
                .replace("\u2028", "\\u2028")
                .replace("\u2029", "\\u2029"))


def _read_skill(spec: dict, skill_path: str | os.PathLike | None) -> str:
    inline = spec.get("skill")
    if isinstance(inline, str) and inline.strip():
        return inline
    if skill_path:
        candidates = [pathlib.Path(skill_path)]
    else:
        candidates = []
        if spec.get("skill_path"):
            candidates.append(pathlib.Path(spec["skill_path"]))
        # Смонтированный текст навыка, затем копия в образе (на случай, если
        # навык не смонтирован — например, при сборке страницы вне стенда).
        candidates += [DEFAULT_SKILL, KIT_DIR / "SKILL.md"]
    for path in candidates:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            continue
    # Не валим сборку: страница просто скажет, что текст не встроен.
    return ""


# ────────────────────────────────── сборка ──────────────────────────────────

def build(spec: dict,
          out: str | os.PathLike,
          *,
          data: Any = None,
          skill_path: str | os.PathLike | None = None,
          theme: str | None = None,
          spec_path: pathlib.Path | None = None) -> dict:
    """Собирает страницу. Возвращает сводку {path, bytes, rows, charts}."""
    if not isinstance(spec, dict):
        raise SpecError("spec должен быть объектом (dict)")
    spec = json.loads(json.dumps(spec))  # копия, чтобы не менять вход

    if theme:
        spec["theme"] = theme
    if data is not None:
        spec["data"] = data

    spec = _defaults(spec)
    table = _load_data(spec, spec_path)
    _validate(spec, table)

    from themes import THEMES, css as theme_css  # локальный импорт: kit лежит рядом

    theme_name = spec.get("theme") or "almanac"
    if theme_name not in THEMES:
        raise SpecError(f"theme: допустимо {list(THEMES)}")
    spec["accent"] = spec.get("accent") or THEMES[theme_name]["light"]["accent"]

    skill_text = _read_skill(spec, skill_path)
    spec["skill"] = skill_text

    template = (KIT_DIR / "template.html").read_text(encoding="utf-8")
    engine = (KIT_DIR / "engine.js").read_text(encoding="utf-8")

    noscript_meta = []
    if spec.get("source"):
        noscript_meta.append(f"Источник: {spec['source']}.")
    noscript_meta.append(f"Строк в данных: {len(table['rows'])}.")
    if spec.get("note"):
        noscript_meta.append(spec["note"])

    html = (template
            .replace("/*__THEME_CSS__*/", theme_css(theme_name))
            .replace("__TITLE__", _html_escape(spec.get("title", "Дашборд")))
            .replace("__NOSCRIPT_META__", _html_escape(" ".join(noscript_meta)))
            .replace("/*__SPEC_JSON__*/null", _escape_for_script(spec))
            .replace("/*__DATA_JSON__*/null", _escape_for_script(table))
            .replace("/*__ENGINE_JS__*/", engine))

    target = pathlib.Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")

    return {
        "path": str(target),
        "bytes": target.stat().st_size,
        "rows": len(table["rows"]),
        "columns": table["columns"],
        "charts": [c["id"] for c in spec["charts"]],
        "theme": theme_name,
        "skill_chars": len(skill_text),
    }


def _html_escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ─────────────────────────────────── CLI ────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Собрать автономный HTML-дашборд по spec.json")
    ap.add_argument("--spec", required=True, help="путь к JSON с описанием задачи")
    ap.add_argument("--out", required=True, help="куда положить HTML")
    ap.add_argument("--data", help="отдельный файл данных (перекрывает spec.data)")
    ap.add_argument("--theme", help="almanac | console | coral | furrow")
    ap.add_argument("--skill", help="путь к тексту Skill.MD для встраивания")
    args = ap.parse_args(argv)

    spec_path = pathlib.Path(args.spec)
    if not spec_path.is_file():
        print(f"dashboard: spec не найден: {spec_path}", file=sys.stderr)
        return 2
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"dashboard: spec — некорректный JSON: {exc}", file=sys.stderr)
        return 2

    data = None
    if args.data:
        data = json.loads(pathlib.Path(args.data).read_text(encoding="utf-8"))

    try:
        summary = build(spec, args.out, data=data, skill_path=args.skill,
                        theme=args.theme, spec_path=spec_path)
    except SpecError as exc:
        print(f"dashboard: ошибка в spec — {exc}", file=sys.stderr)
        return 2

    print(f"Готово: {summary['path']} "
          f"({summary['bytes'] / 1024:.0f} КБ, строк {summary['rows']}, "
          f"графиков {len(summary['charts'])}, тема {summary['theme']}, "
          f"Skill.MD {summary['skill_chars']} символов)")
    print("Дальше: python3 /opt/viz/check_page.py <файл> && "
          "python3 /opt/viz/kit/verify_page.py <файл>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
