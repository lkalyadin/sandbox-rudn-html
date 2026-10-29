#!/usr/bin/env python3
"""Пример: с чего начать разбор данных.

Запускается агентом, но можно запустить и руками:

    python3 example/analyse.py
"""
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
OUTPUT = Path(__file__).resolve().parent.parent / "output"


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)

    path = DATA / "world_happiness_2019.csv"
    if not path.exists():
        print(f"Нет файла {path}. Посмотрите, что есть в data/")
        return

    df = pd.read_csv(path)
    print(f"Строк: {len(df)}, колонок: {len(df.columns)}")
    print("Колонки:", ", ".join(df.columns))

    score_col = next(
        (c for c in df.columns if "score" in c.lower() or "happiness" in c.lower()),
        None,
    )
    country_col = next((c for c in df.columns if "country" in c.lower()), None)

    if not score_col or not country_col:
        print("Не нашёл колонки со страной и индексом — разберитесь со схемой")
        return

    top = df.sort_values(score_col, ascending=False).head(10)
    print(f"\nТоп-10 по «{score_col}»:")
    print(top[[country_col, score_col]].to_string(index=False))

    # График — то, что чаще всего и просят на выходе.
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(top[country_col][::-1], top[score_col][::-1], color="#4c72b0")
    ax.set_xlabel(score_col)
    ax.set_title(f"Топ-10 стран: {score_col}")
    fig.tight_layout()

    out = OUTPUT / "happiness_top10.png"
    fig.savefig(out, dpi=140)
    print(f"\nГрафик сохранён: {out}")


if __name__ == "__main__":
    main()
