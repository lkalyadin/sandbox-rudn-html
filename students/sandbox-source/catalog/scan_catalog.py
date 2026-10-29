#!/usr/bin/env python3
"""Сканирует учебный репозиторий датасетов и собирает каталог.

Зачем. В репозитории prasertcbs/basic-dataset больше тысячи файлов. Студент
спрашивает «что у тебя есть?» — агент должен ответить по фактам: какие
датасеты, какая тема, какой размер. Для этого нужен каталог с метаинформацией,
а не память модели.

Что делает:
  1. Забирает дерево репозитория через GitHub API (одним запросом).
  2. Отбирает табличные файлы (csv/tsv/xlsx/json/sqlite/parquet/feather).
  3. Размечает тематику по имени файла (словарь ключевых слов).
  4. По желанию (-–headers) берёт первую строку каждого CSV — это колонки.
  5. Пишет catalog.json (полные метаданные) и catalog.md (человекочитаемый
     индекс: сначала сводка по темам, потом таблицы по темам).

Запуск:
    python3 scan_catalog.py --out-dir /opt/catalog              # быстро, без колонок
    python3 scan_catalog.py --out-dir /opt/catalog --headers    # + колонки
    python3 scan_catalog.py --out-dir /work --headers --rows     # + счётчик строк

Внутри песочницы работает через прокси (HTTP_PROXY в окружении) — поэтому
агент может обновить каталог сам:

    python3 /opt/catalog/scan.py --out-dir /work/catalog
"""

import argparse
import concurrent.futures as cf
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO = os.environ.get("DATASET_REPO", "prasertcbs/basic-dataset")
BRANCH = os.environ.get("DATASET_BRANCH", "master")
API = f"https://api.github.com/repos/{REPO}/git/trees/{BRANCH}?recursive=1"
RAW = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/"

# Табличные форматы: по ним строим каталог.
TABLE_EXT = {".csv", ".tsv", ".xlsx", ".xls", ".json", ".sqlite", ".sqlite3",
              ".parquet", ".feather", ".db"}

# Тематики. Ключ — подстрока в имени файла или в названии папки (нижний регистр).
# Порядок важен: первое совпадение выигрывает. Темы идут в этом же порядке
# и в каталоге — от самых «экономических» к остальным.
THEMES = [
    ("Экономика и финансы", [
        "gdp", "gni", "gini", "income", "salary", "wage", "econom", "inflation",
        "unemploy", "budget", "revenue", "profit", "price", "cost", "money",
        "bank", "credit", "loan", "tax", "invest", "stock", "market", "trade",
        "export", "import", "cpi", "debt", "housing", "house", "bigmac",
        "opec", "oilprice", "oil_price", "gold_price", "oil_gold", "fx_rate",
        "bitcoin", "crypto", "pension", "insurance", "accounting", "capita",
        "gdp_percapita", "worldbank", "cost_of_living", "forbes", "fortune",
        "listed_company", "company_revenue", "sp500", "eod", "index_monthly",
        "gold_monthly", "gold_prices", "nasdaq", "commodity",
    ]),
    ("Бизнес, маркетинг, клиенты", [
        "marketing", "advertis", "ad_", "startup", "business", "company",
        "customer", "sales", "ecommerce", "e-commerce", "campaign", "brand",
        "promotion", "retail", "supermarket", "shopper", "telecom", "churn",
        "employee", "hr_comma", "companies", "kickstarter", "pizza", "order",
        "freight",
    ]),
    ("Демография, общество, география", [
        "population", "birth", "death", "census", "demograph", "migration",
        "marriage", "divorce", "fertility", "mortality", "gender", "household",
        "province", "country", "region", "adult", "person", "place", "tambon",
        "amphur", "lotto", "zoo", "dog_breed", "seed_data", "height_mass",
        "geolocation", "geo", "latitude", "longitude",
    ]),
    ("Кино, сериалы, развлечения", [
        "imdb", "movie", "film", "cinema", "netflix", "tv_show", "tvshow",
        "show", "title", "entertain", "bollywood", "hollywood", "anime",
        "pixar", "disney", "kdrama", "disney_plus", "blockbuster", "oscars",
        "oscar", "golden_globe", "boxoffice", "box_office", "movie_metadata",
        "movies", "quote", "quotes", "miss_universe", "avengers", "iron_man",
        "nine_temples", "tarot",
    ]),
    ("Музыка и стриминг", [
        "spotify", "song", "music", "audio", "playlist", "radio", "lastfm",
        "last.fm", "track", "album", "artist", "band", "podcast", "musicbrainz",
    ]),
    ("Спорт", [
        "fifa", "nba", "nfl", "mlb", "nhl", "soccer", "football", "basketball",
        "tennis", "atp", "wta", "olympic", "sport", "worldcup", "world_cup",
        "premier_league", "formula", "swimming", "cricket", "golf", "nascar",
        "uefa", "laliga", "bundesliga", "liverpool", "runner", "running",
        "athletic", "epl", "league", "championship", "sports",
    ]),
    ("Игры и гейм-данные", [
        "pokemon", "pokedex", "videogame", "video_game", "ign", "animal_crossing",
        "game", "steam", "moveset",
    ]),
    ("Образование и наука", [
        "pisa", "school", "student", "university", "college", "education",
        "course", "exam", "tutor", "research", "citation", "ieee", "survey",
        "developer_survey", "unrank", "ranking", "phd", "scholar", "cwur",
        "patent", "nobel", "tuition", "graduate", "wordles",
    ]),
    ("Здоровье, медицина, питание", [
        "health", "heart", "diabet", "obes", "hospital", "disease", "covid",
        "medical", "medicine", "fitness", "sleep", "diet", "nutrition", "food",
        "calorie", "cafe", "coffee", "starbucks", "mcdonald", "menu", "recipe",
        "grocery", "groceries", "bread", "wine", "beer", "caffeine", "cereal",
        "vaccine", "patient", "drug", "nutrient", "pastry", "cholocate",
        "exercise", "bmi", "gun",
    ]),
    ("Туризм, транспорт, поездки", [
        "tourism", "tourist", "hotel", "airbnb", "seattle-airbnb", "flight",
        "airline", "airport", "booking", "attraction", "restaurant", "travel",
        "trip", "flight_delay", "crash", "passenger", "cabin", "aviation",
        "fleet", "bangkok", "nyc", "spots", "beach",
    ]),
    ("Товары, бренды, цены, авто", [
        "used_car", "usedcar", "car_sales", "automobile", "mpg", "brakes",
        "phone", "mobile", "app_store", "play_store", "gadget", "electronics",
        "fashion", "beauty", "chocolate", "icecream", "pet", "furniture",
        "basket", "super_bowl", "camera", "petrol", "vehicles",
    ]),
    ("Погода, климат, экология", [
        "temperature", "climate", "weather", "air_quality", "aqi", "pollution",
        "emission", "ecolog", "footprint", "global_warming", "carbon", "pm2_5",
    ]),
    ("Соцсети, книги, медиа", [
        "twitter", "instagram", "facebook", "social", "tiktok", "youtube",
        "follower", "wiki", "wikipedia", "book", "novel", "author",
    ]),
    ("Примеры для машинного обучения", [
        "mnist", "emnist", "face_recog", "brain_network", "gamma", "seaborn",
        "pwt90", "iris", "kinase", "digits",
    ]),
    ("Учебные примеры (R, ISLR)", [
        "islr", "ch10", "anova", "wide_fmt", "long_fmt", "xtab", "panel_data",
        "demonа", "demoNA", "ch10ex", "categorical", "epldata",
    ]),
]

# Быстрый список: файлы, которые чаще всего нужны на паре по экономике.
# Агент читает эту таблицу первой — она отвечает на вопрос «что у тебя есть?».
# Путь может исчезнуть в репозитории — тогда строка просто пропускается.
QUICK = [
    ("Advertising.csv", "рекламный бюджет (ТВ/радио/газеты) → продажи; 200 строк, идеален для симулятора"),
    ("bigmac_index.csv", "индекс Биг-Мака: 55 стран, 2011–2021, цены, ВВП, курсы валют"),
    ("OPEC_daily_oilprice.csv", "цены на нефть с 2003 года, дневные"),
    ("OPEC_monthly_oilprice.csv", "цены на нефть помесячно"),
    ("inflation_data_1701-2022.csv", "инфляция по странам за 322 года — эффектная линия времени"),
    ("gapminder.csv", "страна, год, ВВП, население, продолжительность жизни"),
    ("gdp_percapita_2015.csv", "ВВП на душу населения по странам"),
    ("gini_income_inequality.csv", "коэффициент неравенства (Джини) по странам и годам"),
    ("Cost_of_living_index.csv", "индекс стоимости жизни по городам мира"),
    ("credit_default_1500.csv", "дефолты по кредитам — учебный набор для риск-скоринга"),
    ("Telco-Customer-Churn.csv", "отток клиентов телеком-оператора: предсказание churn"),
    ("BankChurners.csv", "отток вкладчиков банка"),
    ("netflix_titles.csv", "каталог Netflix: 6 000+ тайтлов, жанры, страны, даты добавления"),
    ("Video_Games_Sales_as_at_22_Dec_2016.csv", "продажи видеоигр по платформам и жанрам"),
    ("Startups in 2021 end.csv", "стартапы 2021: страна, отрасль, инвесторы"),
    ("forbes_global2000_2021.csv", "Forbes Global 2000: выручка крупнейших компаний"),
    ("MoviesOnStreamingPlatforms_updated.csv", "что где стримят: Netflix, HBO, Disney, Amazon"),
    ("boxoffice.csv", "кассовые сборы фильмов"),
    ("flight_delay_20000.csv", "задержки рейсов: авиакомпания, маршрут, погода"),
    ("seattle-airbnb/listings.csv", "объявления Airbnb в Сиэтле (16 МБ — крупный, качать долго)"),
    ("bread basket.csv", "цены на хлеб: инфляция и стоимость жизни по странам"),
    ("worldbank_gdp_gini_birth_death_rate.csv", "ВВП, Джини, рождаемость и смертность по странам"),
    ("gdp-vs-happiness.csv", "ВВП и счастье: Gapminder + World Happiness Report"),
    ("boston_house_price.csv", "цены на жильё в Бостоне"),
    ("supermarket_customers.csv", "маленький классический набор: сегменты и типы покупок"),
    ("us_news_best_countries_index/us_news_best_countries_2021.xlsx", "индекс лучших стран"),
    ("world-university-rankings/timesData.csv", "рейтинг вузов Times"),
    ("cwurData.csv", "рейтинг вузов CWUR"),
]

# Файлы, которые бессмысленно показывать студенту как «датасет».
SKIP_PATTERNS = re.compile(
    r"(^|/)(readme|license|contributing|code_of_conduct|security)\b"
    r"|\.gitattributes$|\.gitignore$",
    re.IGNORECASE,
)

UA = "opencode-student-sandbox-catalog/1.0"


def human(size):
    if size is None:
        return "?"
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return f"{size:.0f} {unit}" if unit == "Б" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} ГБ"


def guess_theme(path):
    name = os.path.basename(path).lower()
    hay = path.lower()
    for theme, keys in THEMES:
        for k in keys:
            if k in name or k in hay:
                return theme
    return "Прочее"


def fetch(url, timeout=30, headers=None, limit=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read() if limit is None else r.read(limit)
    return data


def get_tree():
    raw = fetch(API, timeout=60)
    d = json.loads(raw.decode("utf-8", "replace"))
    if "tree" not in d:
        raise SystemExit(f"GitHub API вернул неожиданный ответ: {str(d)[:200]}")
    return d["tree"], d.get("truncated", False)


def header_of(path, ext):
    """Первая строка файла — это заголовок с колонками."""
    try:
        data = fetch(RAW + urllib.parse.quote(path), timeout=25,
                     headers={"Range": "bytes=0-2047"}, limit=2048)
    except Exception:
        return None
    text = data.decode("utf-8", "replace")
    line = text.split("\n", 1)[0].strip()
    if not line:
        return None
    if ext == ".tsv":
        cols = line.split("\t")
    else:
        cols = line.split(",")
    cols = [c.strip().strip('"') for c in cols]
    cols = [c for c in cols if c][:40]
    return cols if len(cols) > 1 else None


def count_rows(path, ext):
    """Точный счётчик строк — только для небольших файлов (скачиваем целиком)."""
    try:
        data = fetch(RAW + urllib.parse.quote(path), timeout=40)
    except Exception:
        return None
    n = data.count(b"\n")
    if not data.endswith(b"\n"):
        n += 1
    return max(0, n - 1)  # минус заголовок


def build(args):
    tree, truncated = get_tree()
    items = []
    for x in tree:
        if x.get("type") != "blob":
            continue
        path = x["path"]
        if SKIP_PATTERNS.search(path):
            continue
        ext = os.path.splitext(path)[1].lower()
        if ext not in TABLE_EXT:
            continue
        items.append({
            "path": path,
            "name": os.path.basename(path),
            "ext": ext,
            "size": x.get("size"),
            "url": RAW + urllib.parse.quote(path),
        })

    if args.headers:
        todo = [i for i in items if i["ext"] in (".csv", ".tsv")]
        if args.limit:
            todo = todo[: args.limit]
        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(header_of, i["path"], i["ext"]): i for i in todo}
            for n, f in enumerate(cf.as_completed(futs), 1):
                item = futs[f]
                try:
                    item["columns"] = f.result()
                except Exception:
                    item["columns"] = None
                if n % 50 == 0:
                    print(f"  заголовки: {n}/{len(todo)}", file=sys.stderr)

    if args.rows:
        todo = [i for i in items
                if i["ext"] == ".csv" and (i["size"] or 0) <= args.rows_mb * 1024 * 1024]
        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(count_rows, i["path"], i["ext"]): i for i in todo}
            for n, f in enumerate(cf.as_completed(futs), 1):
                item = futs[f]
                try:
                    item["rows"] = f.result()
                except Exception:
                    item["rows"] = None
                if n % 25 == 0:
                    print(f"  строки: {n}/{len(todo)}", file=sys.stderr)

    for i in items:
        i["theme"] = guess_theme(i["path"])
        i["size_h"] = human(i.get("size"))

    items.sort(key=lambda i: (i["theme"], -(i.get("size") or 0)))
    return items, truncated


def write_md(items, path, meta):
    by_theme = {}
    for i in items:
        by_theme.setdefault(i["theme"], []).append(i)
    # Порядок тем — как в THEMES (от экономических к остальным), «Прочее» в конце.
    order = [t for t, _ in THEMES if t in by_theme]
    if "Прочее" in by_theme:
        order.append("Прочее")
    order = [(t, by_theme[t]) for t in order]

    out = []
    out.append("# Каталог учебных датасетов")
    out.append("")
    out.append(f"Источник: `{REPO}` (ветка `{BRANCH}`), снимок: {meta['scanned']}.")
    out.append(f"Всего табличных файлов: **{len(items)}**, общий объём: "
               f"**{meta['total_h']}**.")
    out.append("")
    out.append("Каждый файл скачивается напрямую:")
    out.append("`https://raw.githubusercontent.com/" + REPO + "/" + BRANCH + "/<путь>`")
    out.append("")
    out.append("## Сводка по темам")
    out.append("")
    out.append("| Тема | Файлов | Объём |")
    out.append("|---|---:|---:|")
    for theme, files in order:
        total = sum(x.get("size") or 0 for x in files)
        out.append(f"| {theme} | {len(files)} | {human(total)} |")
    out.append("")
    out.append("## Быстрый список (чаще всего нужно на паре)")
    out.append("")
    out.append("| Файл | Размер | О чём |")
    out.append("|---|---:|---|")
    by_path = {i["path"]: i for i in items}
    for qpath, desc in QUICK:
        i = by_path.get(qpath)
        if not i:
            continue
        out.append(f"| `{qpath}` | {i['size_h']} | {desc} |")
    out.append("")
    out.append("## Файлы по темам")
    for theme, files in order:
        out.append("")
        out.append(f"### {theme} ({len(files)})")
        out.append("")
        out.append("| Файл | Размер | Формат | Строк | Колонки |")
        out.append("|---|---:|---|---:|---|")
        for i in files:
            cols = i.get("columns")
            coltxt = ", ".join(cols[:8]) + ("…" if cols and len(cols) > 8 else "") if cols else "—"
            out.append(f"| `{i['path']}` | {i['size_h']} | {i['ext'].lstrip('.')} | "
                       f"{i.get('rows') or '—'} | {coltxt} |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def main():
    ap = argparse.ArgumentParser(description="Каталог датасетов из GitHub")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--headers", action="store_true", help="брать колонки (1 запрос на файл)")
    ap.add_argument("--rows", action="store_true", help="считать строки (скачивает файлы целиком)")
    ap.add_argument("--rows-mb", type=float, default=2.0)
    ap.add_argument("--limit", type=int, default=0, help="ограничить число файлов для заголовков")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    print(f"Сканирую {REPO}@{BRANCH}…", file=sys.stderr)
    items, truncated = build(args)
    total = sum(i.get("size") or 0 for i in items)
    meta = {
        "repo": REPO,
        "branch": BRANCH,
        "scanned": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "files": len(items),
        "total_bytes": total,
        "total_h": human(total),
        "tree_truncated": truncated,
        "with_headers": bool(args.headers),
        "with_rows": bool(args.rows),
    }
    with open(os.path.join(args.out_dir, "catalog.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "items": items}, f, ensure_ascii=False, indent=1)
    write_md(items, os.path.join(args.out_dir, "catalog.md"), meta)
    print(f"Готово: {len(items)} файлов, {meta['total_h']} → {args.out_dir}/catalog.md",
          file=sys.stderr)


if __name__ == "__main__":
    main()
