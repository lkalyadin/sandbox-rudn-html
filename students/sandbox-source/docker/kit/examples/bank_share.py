#!/usr/bin/env python3
"""Пример дашборда по банковскому маркетингу (`bank.csv`, микро-данные).

Показывает главное отличие от панели World Bank: здесь считаем ДОЛЮ
(доля y = yes в группе) и показываем знаменатель, а не среднее.

    cd "$TASK"
    python3 /opt/viz/kit/examples/bank_share.py --out output/dashboard.html

Данные: UCI Bank Marketing, разделитель `;`, 4 521 строка. Строка — контакт,
а не уникальный клиент (ID нет), поэтому «клиенты» в подписях не пишем.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, "/opt/viz/kit")

from dashboard import build   # noqa: E402

JOB_RU = {
    "admin.": "офисные служащие", "blue-collar": "рабочие", "entrepreneur": "предприниматели",
    "housemaid": "домработники", "management": "руководители", "retired": "пенсионеры",
    "self-employed": "самозанятые", "services": "сфера услуг", "student": "студенты",
    "technician": "технические специалисты", "unemployed": "безработные", "unknown": "не указано",
}
EDU_RU = {"primary": "начальное", "secondary": "среднее", "tertiary": "высшее", "unknown": "не указано"}
MONTH_RU = {"jan": "янв", "feb": "фев", "mar": "мар", "apr": "апр", "may": "май", "jun": "июн",
            "jul": "июл", "aug": "авг", "sep": "сен", "oct": "окт", "nov": "ноя", "dec": "дек"}
YESNO_RU = {"yes": "да", "no": "нет"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Дашборд по bank.csv")
    ap.add_argument("--csv", default="/work/data/bank.csv")
    ap.add_argument("--out", default="output/dashboard.html")
    ap.add_argument("--theme", default="coral",
                    choices=["almanac", "console", "coral", "furrow"])
    ap.add_argument("--skill", default=None)
    args = ap.parse_args(argv)

    import pandas as pd

    df = pd.read_csv(args.csv, sep=";")
    df["age_group"] = pd.cut(df["age"], bins=[17, 25, 35, 45, 55, 65, 120],
                             labels=["18–25", "26–35", "36–45", "46–55", "56–65", "66+"])
    df["job_ru"] = df["job"].map(JOB_RU).fillna(df["job"])
    df["education_ru"] = df["education"].map(EDU_RU).fillna(df["education"])
    df["month_ru"] = df["month"].map(MONTH_RU).fillna(df["month"])
    df["housing_ru"] = df["housing"].map(YESNO_RU).fillna(df["housing"])

    columns = ["job_ru", "education_ru", "month_ru", "age_group", "housing_ru",
               "y", "balance", "duration"]
    rows = [[row[c] for c in columns] for row in df[columns].to_dict("records")]

    spec = {
        "title": "Оформление депозита: в каких сегментах доля выше",
        "question": ("В каких сегментах наблюдаемая доля согласий на депозит выше "
                     "и каков размер этих групп?"),
        "theme": args.theme,
        "decimals": 1,
        "source": "bank.csv (UCI Bank Marketing, 4 521 контакт)",
        "note": ("Строка — один контакт кампании, а не уникальный клиент: ID нет. "
                 "Доля = согласия / строки группы после фильтров. "
                 "Наблюдаемая связь не доказывает причинность."),
        "dimensions": {
            "job_ru": {"label": "Профессия"},
            "education_ru": {"label": "Образование"},
            "month_ru": {"label": "Месяц контакта", "ordered": True,
                         "order": ["янв", "фев", "мар", "апр", "май", "июн",
                                   "июл", "авг", "сен", "окт", "ноя", "дек"]},
            "age_group": {"label": "Возраст, лет", "ordered": True,
                          "order": ["18–25", "26–35", "36–45", "46–55", "56–65", "66+"]},
            "housing_ru": {"label": "Кредит на жильё"},
        },
        "measures": {
            "yes": {"label": "Доля согласий", "column": "y", "agg": "share",
                    "equals": "yes", "share": True},
            "balance": {"label": "Средний баланс, €", "column": "balance",
                        "unit": "€", "agg": "mean"},
            "count": {"label": "Число контактов", "agg": "count", "column": "y"},
        },
        "kpis": [
            {"label": "Контактов в отборе", "agg": {"fn": "count", "column": "y"}, "decimals": 0},
            {"label": "Доля согласий", "agg": {"fn": "share", "column": "y"},
             "equals": "yes", "share": True, "decimals": 1},
            {"label": "Средний баланс", "agg": {"fn": "mean", "column": "balance"},
             "unit": "€", "decimals": 0},
            {"label": "Медианная длительность", "agg": {"fn": "median", "column": "duration"},
             "unit": "с", "decimals": 0},
        ],
        "filters": [
            {"id": "education", "label": "Образование", "column": "education_ru"},
            {"id": "housing", "label": "Кредит на жильё", "column": "housing_ru"},
            {"id": "month", "label": "Месяц контакта", "column": "month_ru"},
        ],
        "charts": [
            {"id": "jobs", "title": "Доля согласий по профессиям",
             "type": "hbar", "dimension": "job_ru", "measure": "yes",
             "note": "Тултип показывает число согласий и знаменатель группы."},
            {"id": "edu", "title": "Доля согласий по образованию",
             "type": "vbar", "dimension": "education_ru", "measure": "yes"},
            {"id": "age", "title": "Доля согласий по возрасту",
             "type": "vbar", "dimension": "age_group", "measure": "yes",
             "note": "Возрастные группы — эвристика, не статистическая значимость."},
            {"id": "months", "title": "Число контактов по месяцам",
             "type": "vbar", "dimension": "month_ru", "measure": "count",
             "agg": "count",
             "note": "Года в данных нет: месяц — не полноценный временной ряд."},
        ],
    }

    summary = build(spec, args.out,
                    data={"columns": columns, "rows": rows},
                    skill_path=args.skill, spec_path=pathlib.Path(args.csv))
    print(f"Готово: {summary['path']} ({summary['bytes'] / 1024:.0f} КБ, "
          f"строк {summary['rows']})")
    print("Проверка: python3 /opt/viz/check_page.py " + summary["path"])
    print("          python3 /opt/viz/kit/verify_page.py " + summary["path"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
