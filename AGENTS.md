# Роутер проектов

Это корневая папка-хаб для отдельных OpenCode-проектов. Каждый проект — свой каталог со своим `AGENTS.md`.

- **students/** — студенческий стенд OpenCode на VPS (docker, edge, датасеты). Контекст и правила: `students/AGENTS.md` — прочитать его перед любой работой по стенду. Датасеты для стенда лежат в `datasets/` — этот путь захардкожен дефолтом в скриптах стенда (`/srv/opencode-student/sandbox/scripts/`), не переносить.
- **opencode-settings/** — настройки основного стенда `https://94.141.97.249:4601` (OpenCode 2.0.32 + Caddy, systemd user-юниты, без docker). Что развёрнуто, ограничения хоста (1 vCPU / 1.6 ГБ), провайдеры и модели, правила правок — `opencode-settings/AGENTS.md`; фактический снимок — `opencode-settings/docs/snapshot-2026-10-28.md`.
- **demo/** — песочница-демо, рабочий каталог сессий учеников.
- **gameconnect/** — форк плагина `capacitor-game-connect` (Capacitor 8, Play Games / GameKit) для игры Adventure Mazes; доработка облачных сохранений. Контекст: `gameconnect/AGENTS.md`, анализ: `gameconnect/docs/cloud-save-research.md`. На этом VPS нет node/JDK — сборка только на дев-машине.

Игра Adventure Mazes живёт отдельным git-репозиторием: `adventuremazes/` = `/home/deployagent/projects/adventuremazes` (AGENTS.md — там; сессии начинать из её каталога).
