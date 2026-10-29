# sandbox-rudn-html

Рабочее пространство основного стенда OpenCode (РУДН, экономика): документация стенда, скрипты,
исходники студенческой песочницы и учебные датасеты. Публичная копия — без секретов.

## Что внутри

| Каталог / файл | Что это |
|---|---|
| `opencode-settings/` | основной стенд `:4601`: `AGENTS.md` (что развёрнуто, риски, правила), `docs/` (снимок состояния + runbook переезда), `scripts/` (архивация проектов в БД, экспорт для переезда) |
| `students/` | студенческий стенд: `AGENTS.md`, `DEPLOY_STAND.md`, `ROOT-STEPS.md`, `HANDOFF_TO_NEXT_AGENT.md`, `stand-variants/` (режимы simple/free-only/reserve) и `sandbox-source/` — исходники стенда (Dockerfile, `docker-compose.yml`, скрипты, конфиг OpenCode, навык, edge, egress, gateway) |
| `datasets/` | 26 CSV для учебных заданий (World Bank, OWID) + `README.md` с описанием колонок |
| `demo/` | архивный снимок прежнего демо-стенда (для истории, не для развёртывания) |
| HTML/MD/DOCX в корне | учебные материалы: квизы, тесты, ДЗ по визуализации |
| `AGENTS.md` | роутер проектов (что где лежит и какие правила) |

Студенческий стенд теперь разворачивается **только на отдельной одноразовой VPS** (docker + gVisor +
edge), а не на хосте основного стенда. Процедура — `students/DEPLOY_STAND.md` и `students/ROOT-STEPS.md`.

## Чего здесь нет

* **Секретов.** Пароли и ключи заменены плейсхолдерами `<SANDBOX_PASSWORD>`, `<AI_GATEWAY_API_KEY>`.
  Реальные значения спрашивают у владельца при развёртывании и кладут в файл с правами 600
  (см. `opencode-settings/docs/migration-runbook-2026-10.md`, §0.1).
* `gameconnect/` и `adventuremazes/` — у них свои репозитории:
  [game-connect](https://github.com/lkalyadin/game-connect),
  [adventure-mazes-google](https://github.com/lkalyadin/adventure-mazes-google).
* База OpenCode (`opencode.db`), TLS-сертификаты, ключи SSH, бандлы docker-образов.

## Быстрый старт

* Поднять/переехать основной стенд: `opencode-settings/docs/migration-runbook-2026-10.md`.
* Поднять студенческий стенд на чистом VPS: `students/ROOT-STEPS.md` (bootstrap) →
  `students/DEPLOY_STAND.md` (развёртывание, бандл или сборка образа).

## Данные

`datasets/` — выгрузки World Bank Open Data и Our World in Data (CC BY 4.0), подробности и источники
в `datasets/README.md`.
