#!/usr/bin/env python3
"""Пример дашборда по одному показателю World Bank — копируйте и правьте.

Это рабочая заготовка на типовую задачу «рейтинг стран + динамика» по любому
файлу `wb_*.csv`. Обычно достаточно поменять `--csv` и заголовки:

    cd "$TASK"
    python3 /opt/viz/kit/examples/wb_country.py \
        --csv wb_gini.csv \
        --title "Неравенство по странам: индекс Джини" \
        --question "В каких странах неравенство выше и как оно менялось в 2015–2023?" \
        --out output/dashboard.html

Дальше:
    python3 /opt/viz/check_page.py "$TASK/output/dashboard.html"
    python3 /opt/viz/kit/verify_page.py "$TASK/output/dashboard.html"

Что внутри: 4 KPI, три фильтра, четыре графика (топ стран, динамика медианы по
годам, распределение, таблица). Агрегаты World Bank (World, Euro area, OECD…)
отбрасываются автоматически, регион добавляется по коду страны.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, "/opt/viz/kit")

from dashboard import build          # noqa: E402
import wb as wbkit                   # noqa: E402

# Русские подписи показателей: чтобы не выдумывать названия каждый раз.
MEASURE_LABELS = {
    "education_spending_pct_gdp": "Расходы на образование, % ВВП",
    "exports_pct_gdp": "Экспорт, % ВВП",
    "fdi_inflows_pct_gdp": "Прямые иностранные инвестиции, % ВВП",
    "gdp_usd": "ВВП, долл. США",
    "gdp_growth_pct": "Рост ВВП, % в год",
    "gdp_per_capita_usd": "ВВП на душу населения, долл. США",
    "gini_index": "Индекс Джини (0–100)",
    "gni_per_capita_usd": "ВНД на душу населения, долл. США",
    "gov_debt_pct_gdp": "Государственный долг, % ВВП",
    "health_spending_pct_gdp": "Расходы на здравоохранение, % ВВП",
    "imports_pct_gdp": "Импорт, % ВВП",
    "inflation_pct": "Инфляция потребительских цен, % в год",
    "labor_participation_pct": "Участие в рабочей силе, % населения 15+",
    "manufacturing_pct_gdp": "Промышленность, % ВВП",
    "population": "Население, человек",
    "poverty_pct_2usd": "Бедность ниже 2 долл./день, % населения",
    "remittances_pct_gdp": "Денежные переводы, % ВВП",
    "tax_revenue_pct_gdp": "Налоговые доходы, % ВВП",
    "unemployment_pct": "Безработица, % рабочей силы",
    "youth_unemployment_pct": "Безработица молодёжи 15–24, %",
}

UNITS = {
    "population": "чел.",
}


def nice_step(raw: float) -> float:
    """Округляет шаг интервала до «человеческого»: 1, 2, 2.5, 5, 10, 20…"""
    import math
    if raw <= 0:
        return 1.0
    exp = math.floor(math.log10(raw))
    base = raw / (10 ** exp)
    for cand in (1, 2, 2.5, 5, 10):
        if base <= cand:
            return cand * (10 ** exp)
    return 10.0 ** (exp + 1)


def add_bins(df, value_column: str, width: float):
    """Колонка bin: интервалы для распределения («20–25», «25–30», …)."""
    values = df[value_column].dropna()
    if values.empty:
        df["bin"] = "—"
        return df, []
    lo = width * int(values.min() // width)
    hi = width * (int(values.max() // width) + 1)
    edges = []
    edge = lo
    while edge < hi:
        edges.append(edge)
        edge += width
    labels = [f"{a:g}–{a + width:g}" for a in edges]

    def label(v):
        if v is None or v != v:      # NaN
            return None
        idx = int((v - lo) // width)
        idx = max(0, min(len(labels) - 1, idx))
        return labels[idx]

    df["bin"] = [label(v) for v in df[value_column]]
    return df, labels


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Дашборд по показателю World Bank")
    ap.add_argument("--csv", default="wb_gini.csv", help="файл из /work/data")
    ap.add_argument("--out", default="output/dashboard.html")
    ap.add_argument("--title", default=None)
    ap.add_argument("--question", default=None)
    ap.add_argument("--label", default=None, help="подпись показателя")
    ap.add_argument("--theme", default="almanac",
                    choices=["almanac", "console", "coral", "furrow"])
    ap.add_argument("--top", type=int, default=15, help="сколько стран в рейтинге")
    ap.add_argument("--bins", type=float, default=None,
                    help="ширина интервала распределения (по умолчанию 5%% от размаха)")
    ap.add_argument("--skill", default=None, help="путь к тексту Skill.MD")
    args = ap.parse_args(argv)

    df = wbkit.load(args.csv)
    df = wbkit.only_countries(df)
    df = wbkit.add_last_flag(df)

    value_column = df.attrs["value_column"]
    label = args.label or MEASURE_LABELS.get(value_column, value_column)
    unit = UNITS.get(value_column, "")
    title = args.title or f"{label}: страны и динамика"
    question = args.question or (
        f"Как {label.lower()} различается между странами и как менялось в 2015–2023 годах?")

    span = float(df["value"].max() - df["value"].min()) if not df["value"].dropna().empty else 5
    # Шаг интервала округляем до 1/2/2.5/5/10…: иначе подписи вида «25–28.6»
    # не помещаются на оси и наезжают друг на друга.
    width = args.bins or nice_step(span / 10)
    df, bin_labels = add_bins(df, "value", width)

    data = wbkit.rows(df, ["country", "country_code", "region_ru", "year", "last", "value", "bin"])
    n_rows = len(df)

    spec = {
        "title": title,
        "question": question,
        "theme": args.theme,
        "decimals": 1,
        "source": f"{args.csv} (World Bank, 2015–2023; агрегаты банка исключены)",
        "note": (f"Наблюдений: {n_rows}; стран: {df['country_code'].nunique()}. "
                 f"«Последний год страны» — последнее доступное наблюдение; "
                 f"у разных стран это разные годы."),
        "dimensions": {
            "country": {"label": "Страна"},
            "region_ru": {"label": "Регион"},
            "year": {"label": "Год", "ordered": True},
            "bin": {"label": f"{label}, интервалы по {width:g}",
                    "ordered": True, "order": bin_labels},
        },
        "measures": {
            "value": {"label": label, "column": "value", "unit": unit, "agg": "mean"},
            "count": {"label": "Число наблюдений", "agg": "count", "column": "country"},
            "delta": {"label": "Изменение за период", "column": "value", "unit": unit, "agg": "last"},
        },
        "kpis": [
            {"label": "Стран в отборе", "agg": {"fn": "count_distinct", "column": "country_code"},
             "decimals": 0},
            {"label": f"Медиана: {label}", "agg": {"fn": "median", "column": "value"},
             "decimals": 1, "unit": unit},
            {"label": "Максимум", "agg": {"fn": "max", "column": "value"}, "decimals": 1,
             "unit": unit, "subBy": "country"},
            {"label": "Минимум", "agg": {"fn": "min", "column": "value"}, "decimals": 1,
             "unit": unit, "subBy": "country"},
        ],
        "filters": [
            {"id": "last", "label": "Последний год страны", "column": "last",
             "default": "last", "valueLabels": {"1": "Да", "0": "Нет"}},
            {"id": "year", "label": "Год", "column": "year"},
            {"id": "region", "label": "Регион", "column": "region_ru"},
        ],
        "charts": [
            {"id": "top", "title": f"Топ-{args.top}: {label}",
             "type": "hbar", "dimension": "country", "measure": "value",
             "topN": args.top, "rest": "mean",
             "note": "«Остальные» — среднее по объединённым строкам, не среднее из средних."},
            {"id": "trend", "title": "Динамика: медиана по годам",
             "type": "line", "dimension": "year", "measure": "value",
             "note": "Медиана по странам, у которых есть данные за этот год."},
            {"id": "dist", "title": "Распределение по странам",
             "type": "vbar", "dimension": "bin", "measure": "count", "agg": "count",
             "note": f"Интервалы шириной {width:g}."},
            {"id": "table", "title": f"Данные по странам (Top-{args.top})",
             "type": "table", "dimension": "country", "measure": "value",
             "topN": args.top},
        ],
    }

    summary = build(spec, args.out, data=data, skill_path=args.skill,
                    spec_path=pathlib.Path(args.csv))
    print(f"Готово: {summary['path']} ({summary['bytes'] / 1024:.0f} КБ, "
          f"строк {summary['rows']}, графиков {len(summary['charts'])})")
    print("Проверка: python3 /opt/viz/check_page.py " + summary["path"])
    print("          python3 /opt/viz/kit/verify_page.py " + summary["path"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
