"""Темы оформления для /opt/viz/kit.

Каждая тема — два набора CSS-токенов: светлый (`:root`) и тёмный
(`body.theme-dark`). Шрифты только системные: в песочнице нет интернета, а
страница должна открываться через file:// без внешних запросов.

Темы — адаптация палитр Hallmark (Almanac, Console, Coral, Furrow) под
аналитическую панель (§6 Skill.MD: app screen, а не лендинг). Полные темы
Hallmark тянут Google Fonts, поэтому здесь они переведены на системные
шрифты, а декоративные приёмы (градиенты, «карточки в карточках») убраны.
"""

FONT_SANS = ('system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", '
             'Arial, "Noto Sans", sans-serif')
FONT_NUM = ('ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, '
            '"Liberation Mono", monospace')

THEMES = {
    "almanac": {
        "label": "Almanac — светлая редакционная, тёплая бумага",
        "light": {
            "paper": "#f6f4ef",
            "sheet": "#fffdf8",
            "sheet-hover": "#f1ede4",
            "ink": "#221f1a",
            "ink-2": "#423c33",
            "muted": "#6f6759",
            "rule": "#e2dcd0",
            "rule-strong": "#cabfab",
            "chip": "#eae3d5",
            "track": "#efe9dd",
            "grid": "#e6e0d4",
            "accent": "#2f6f5e",
            "warn-bg": "#fdf3e0",
            "warn-border": "#e6cf9e",
            "warn-ink": "#8a5a12",
            "tip-bg": "#221f1a",
            "tip-ink": "#fbf8f2",
        },
        "dark": {
            "paper": "#171613",
            "sheet": "#201e1a",
            "sheet-hover": "#2a2721",
            "ink": "#f4f1e8",
            "ink-2": "#ddd7c9",
            "muted": "#a49c8b",
            "rule": "#33302a",
            "rule-strong": "#4a463d",
            "chip": "#2c2923",
            "track": "#2a2721",
            "grid": "#2b2823",
            "accent": "#6fbfa5",
            "warn-bg": "#3a2f1c",
            "warn-border": "#5c4a26",
            "warn-ink": "#e8c07a",
            "tip-bg": "#f4f1e8",
            "tip-ink": "#1d1b17",
        },
    },
    "console": {
        "label": "Console — светлая, графит и холодный серый",
        "light": {
            "paper": "#f4f5f7",
            "sheet": "#ffffff",
            "sheet-hover": "#eef0f3",
            "ink": "#14181d",
            "ink-2": "#333b45",
            "muted": "#667080",
            "rule": "#dfe3e8",
            "rule-strong": "#c2c9d2",
            "chip": "#e7eaee",
            "track": "#ebecf0",
            "grid": "#e6e9ed",
            "accent": "#2b5cd9",
            "warn-bg": "#fff4e5",
            "warn-border": "#efd0a0",
            "warn-ink": "#8a5a12",
            "tip-bg": "#14181d",
            "tip-ink": "#f7f9fb",
        },
        "dark": {
            "paper": "#0f1216",
            "sheet": "#161a20",
            "sheet-hover": "#1e242c",
            "ink": "#e8edf3",
            "ink-2": "#c3ccd8",
            "muted": "#8b96a4",
            "rule": "#242a32",
            "rule-strong": "#3a434f",
            "chip": "#1f252d",
            "track": "#1d232b",
            "grid": "#20262e",
            "accent": "#6f9bff",
            "warn-bg": "#332a1b",
            "warn-border": "#54452a",
            "warn-ink": "#e2bb79",
            "tip-bg": "#e8edf3",
            "tip-ink": "#12151a",
        },
    },
    "coral": {
        "label": "Coral — светлая тёплая, коралловый акцент",
        "light": {
            "paper": "#fbf6f3",
            "sheet": "#ffffff",
            "sheet-hover": "#f6ece7",
            "ink": "#241b18",
            "ink-2": "#4a3a34",
            "muted": "#7d665e",
            "rule": "#eeddd5",
            "rule-strong": "#dcc0b4",
            "chip": "#f4e3db",
            "track": "#f3e7e1",
            "grid": "#f0e2db",
            "accent": "#c1533a",
            "warn-bg": "#fdf1e2",
            "warn-border": "#e8c9a4",
            "warn-ink": "#8a4d12",
            "tip-bg": "#241b18",
            "tip-ink": "#fdf7f4",
        },
        "dark": {
            "paper": "#191311",
            "sheet": "#221a17",
            "sheet-hover": "#2c221e",
            "ink": "#f7efe9",
            "ink-2": "#e0cec5",
            "muted": "#ad968c",
            "rule": "#352a25",
            "rule-strong": "#4e3d36",
            "chip": "#2b211d",
            "track": "#2a201c",
            "grid": "#2c221e",
            "accent": "#f0806a",
            "warn-bg": "#382a1c",
            "warn-border": "#574329",
            "warn-ink": "#eec182",
            "tip-bg": "#f7efe9",
            "tip-ink": "#1f1714",
        },
    },
    "furrow": {
        "label": "Furrow — светлая землистая, оливковый акцент",
        "light": {
            "paper": "#f5f5ee",
            "sheet": "#fdfdf7",
            "sheet-hover": "#eeeee2",
            "ink": "#1e2118",
            "ink-2": "#3d4232",
            "muted": "#6c7059",
            "rule": "#e0e1d2",
            "rule-strong": "#c5c7b0",
            "chip": "#e8e9d9",
            "track": "#eeefe1",
            "grid": "#e5e6d7",
            "accent": "#5b6b2f",
            "warn-bg": "#fbf3dd",
            "warn-border": "#e3d09b",
            "warn-ink": "#7d5a12",
            "tip-bg": "#1e2118",
            "tip-ink": "#f8f9f0",
        },
        "dark": {
            "paper": "#14160f",
            "sheet": "#1b1e15",
            "sheet-hover": "#24281c",
            "ink": "#f0f2e6",
            "ink-2": "#d5d9c5",
            "muted": "#9ba087",
            "rule": "#2a2e20",
            "rule-strong": "#40452f",
            "chip": "#24281b",
            "track": "#232719",
            "grid": "#252a1b",
            "accent": "#a9c264",
            "warn-bg": "#332c19",
            "warn-border": "#514426",
            "warn-ink": "#dfc07e",
            "tip-bg": "#f0f2e6",
            "tip-ink": "#171a11",
        },
    },
}

THEME_NAMES = list(THEMES.keys())
DEFAULT_THEME = "almanac"


def _block(selector: str, tokens: dict) -> str:
    lines = [selector + " {"]
    for key, value in tokens.items():
        lines.append(f"  --{key}: {value};")
    lines.append(f"  --font-sans: {FONT_SANS};")
    lines.append(f"  --font-num: {FONT_NUM};")
    lines.append("  --radius: 8px;")
    lines.append("  --chart-color: var(--accent);")
    lines.append("}")
    return "\n".join(lines)


def css(theme: str = DEFAULT_THEME) -> str:
    """Возвращает CSS с токенами темы (светлая + тёмная) или бросает KeyError."""
    spec = THEMES[theme]
    return (_block(":root", spec["light"]) + "\n" +
            _block("body.theme-dark", spec["dark"]) + "\n")


def accent(theme: str = DEFAULT_THEME) -> str:
    return THEMES[theme]["light"]["accent"]
