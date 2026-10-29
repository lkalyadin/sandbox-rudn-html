#!/usr/bin/env python3
"""Помощник для файлов World Bank из /work/data (wb_*.csv).

Зачем. В этих файлах под видом «стран» лежат ещё и макроагрегаты Всемирного
банка: `World`, `Euro area`, `OECD members`, `Sub-Saharan Africa`, группы по
доходу. Если их не убрать, рейтинг стран получается ложным: «World» окажется
на первом месте, а «East Asia & Pacific» — соседом Германии. Проверено на
живой сессии: модель потратила больше минуты и четыре шага, чтобы разобраться
в этом самой.

Здесь это уже сделано:

    from wb import load, rows
    df = load("wb_unemployment.csv")        # колонки: country, country_code, year, value
    df = df[df["is_country"]]               # агрегаты отброшены, регион добавлен
    data = rows(df, ["country", "year", "region", "value"])

Коды агрегатов — официальный список World Bank (WLD, EUU, EAS, …), поэтому
фильтр не зависит от названий и не ломается на «Egypt, Arab Rep.».
"""

from __future__ import annotations

import json
import pathlib
from typing import Iterable

DATA_DIR = pathlib.Path("/work/data")
KIT_DIR = pathlib.Path(__file__).resolve().parent

# Официальные агрегаты World Bank: регионы, группы по доходу, союзы, «мир».
AGGREGATE_CODES = frozenset("""
AFE AFW ARB CEB CSS EAP EAR EAS ECA ECS EMU EUU FCS FCV HIC HPC IBD IBT IDA IDB
IDX INX LAC LCN LDC LIC LMC LMY LTE MEA MIC MNA NAC OED OSS PRE PSS PST SAS SSA
SSF SST TEA TEC TLA TMN TSA TSS UMC WLD
""".split())

REGION_RU = {
    "Africa": "Африка",
    "Asia": "Азия",
    "Europe": "Европа",
    "North America": "Северная Америка",
    "South America": "Южная Америка",
    "Oceania": "Океания",
    "Antarctica": "Антарктика",
}

_REGIONS: dict[str, str] | None = None


def _regions() -> dict[str, str]:
    global _REGIONS
    if _REGIONS is None:
        _REGIONS = json.loads((KIT_DIR / "regions.json").read_text(encoding="utf-8"))
    return _REGIONS


def region_of(code: str | None, *, russian: bool = False) -> str:
    """Регион по коду ISO3; для неизвестных — «Прочие»/«Other»."""
    name = _regions().get(str(code or "").upper())
    if not name:
        return "Прочие" if russian else "Other"
    return REGION_RU.get(name, name) if russian else name


def load(name: str, value_column: str | None = None, *,
         data_dir: str | pathlib.Path = DATA_DIR):
    """Читает wb_*.csv и приводит к единому виду.

    Возвращает DataFrame с колонками:
      country, country_code, year, value, is_country, region, region_ru

    `value_column` можно не указывать: в этих файлах показатель один, имя
    берётся из последней колонки (например, gini_index).
    """
    import pandas as pd

    path = pathlib.Path(data_dir) / name
    if not path.is_file():
        raise FileNotFoundError(f"нет файла данных: {path}")
    df = pd.read_csv(path)
    for col in ("country", "country_code", "year"):
        if col not in df.columns:
            raise ValueError(
                f"{name}: ожидались колонки country, country_code, year; "
                f"есть {list(df.columns)}")
    if value_column is None:
        candidates = [c for c in df.columns if c not in ("country", "country_code", "year")]
        if len(candidates) != 1:
            raise ValueError(
                f"{name}: не понял, какой столбец показатель — {candidates}. "
                f"Передайте value_column='...'")
        value_column = candidates[0]

    out = df[["country", "country_code", "year", value_column]].copy()
    out.columns = ["country", "country_code", "year", "value"]
    out["year"] = out["year"].astype(int)
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out["is_country"] = ~out["country_code"].isin(AGGREGATE_CODES)
    out["region"] = [region_of(c) for c in out["country_code"]]
    out["region_ru"] = [region_of(c, russian=True) for c in out["country_code"]]
    out.attrs["value_column"] = value_column
    out.attrs["source"] = name
    return out


def only_countries(df):
    """Убирает макроагрегаты World Bank."""
    return df[df["is_country"]].copy()


def add_last_flag(df, *, by: str = "country_code", column: str = "last"):
    """Помечает последнее доступное наблюдение каждой страны (1/0).

    Нужно для фильтра «только последний год страны»: в панели World Bank
    у стран разные последние годы, и «год = 2023» молча выбрасывает половину
    выборки.
    """
    out = df.copy()
    last_year = out.groupby(by)["year"].transform("max")
    out[column] = (out["year"] == last_year).astype(int)
    return out


def add_delta(df, value_column: str = "value", *, by: str = "country_code",
              column: str = "delta"):
    """Добавляет изменение показателя: последнее значение минус первое.

    Значение повторяется во всех строках страны, поэтому в графике берите
    показатель с агрегатом `first` (или `mean` — результат тот же).
    """
    out = df.copy()
    first = out.groupby(by)[value_column].transform("first")
    last = out.groupby(by)[value_column].transform("last")
    out[column] = last - first
    return out


def rows(df, columns: Iterable[str]) -> dict:
    """DataFrame → {"columns": [...], "rows": [[...], ...]} для spec.json."""
    cols = list(columns)
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"нет колонок {missing}; есть {list(df.columns)}")
    payload = df[cols].to_dict("records")
    return {"columns": cols,
            "rows": [[rec[c] for c in cols] for rec in payload]}


def top_n(df, value_column: str = "value", n: int = 15, *, by: str = "country"):
    """Строки n стран с наибольшим последним значением (для проверки глазами)."""
    last = df.sort_values("year").groupby(by).tail(1)
    return last.nlargest(n, value_column)[[by, "year", value_column]]
