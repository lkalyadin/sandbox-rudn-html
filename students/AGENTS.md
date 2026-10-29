# Контекст проекта: студенческий стенд OpenCode

Это выжимка, чтобы не переписывать контекст каждой сессии. Подробности:

- `HANDOFF_TO_NEXT_AGENT.md` — полный журнал сессий (симптом → причина → правка), риски, чек-листы.
- `DEPLOY_INSTRUCTIONS.md` — инструкция по развёртыванию стенда с нуля.

## Секреты

В этом репозитории секретов нет: пароль стенда, ключ Vercel AI Gateway и ключи провайдеров
заменены плейсхолдерами вида `<SANDBOX_PASSWORD>` / `<AI_GATEWAY_API_KEY>`. При развёртывании
стенда значения **спрашивают у владельца** (или берут из `.env` на хосте стенда) и кладут в файл
с правами 600. В git, в чат и в документацию их не вставлять.

## Что это

### Основной стенд разработки — `https://45.159.173.65:4601` (постоянный)

Это **основной** адрес с 29.10.2026 (переехал с `94.141.97.249`): `opencode serve` на
`127.0.0.1:4600` + Caddy, без изоляции. Здесь идёт разработка стенда, здесь живёт агент,
отсюда мы подключаемся к VPS по SSH (`deployagent`, ключ `~/.ssh/sandbox_new_ed25519`).
Старый хост `94.141.97.249` не выключен и остаётся роллбэком, но его данные устаревают.

Хост: Ubuntu 26.04, hostname `opencode-main`, deployagent uid 1001, **1 vCPU / 2.6 ГБ RAM**,
swap 2 ГБ, docker **не установлен** — образы стенда собираются на целевом VPS (см. ниже)
либо берутся из готовой заготовки-бандла.

### Студенческие/демо-стенды — адрес МЕНЯЕТСЯ

Демо-стенд для студентов разворачивается на отдельном VPS и **мигрирует**:
после занятия стенд гасят, поднимают новый на другом IP.

| Дата | Адрес стенда | Пароль | Статус |
|------|--------------|--------|--------|
| с 28.10.2026 | `https://45.159.173.29` | `demo` (разовая замена) | **резервный стенд «без ограничений»**: без изоляции (`runc`, прямой интернет), без лимитов CPU/RAM (+swap 2 ГБ), все доступные бесплатные модели `opencode`, без навыка визуализации, без ключей и шлюза, `deployagent` с `NOPASSWD: ALL`; 1 vCPU / 1.6 ГБ |

Погашенные стенды в таблицу не заносим: адрес живёт в `.env` стенда. 28.10.2026 погашены
`45.159.173.8` (выбрались бесплатные лимиты за одну пару — штатное исчерпание пула),
`45.159.173.38` и `45.159.173.32` (заменены одним простым стендом на `.29`).

Root-шаги (что делает человек в Putty) — `ROOT-STEPS.md`.

**Правило: не зашивать IP стенда в скрипты и не искать «тот самый» адрес.**
Актуальный адрес всегда в `.env` целевого стенда → `PUBLIC_URL`
(на демо-стендах: `/srv/opencode/sandbox/.env`; у старого стенда на `94.141.97.249`
остался `/srv/opencode-student/sandbox/.env` — новый основной хост студенческого стенда
не содержит).
Панель мониторинга Beszel **не установлена ни на одном актуальном стенде** — см. раздел «Мониторинг».

Логин/пароль студентов: `opencode` / `<SANDBOX_PASSWORD>`; на стенде `45.159.173.29`
разово стоит `demo` (по просьбе преподавателя, в общую инструкцию не переносим).

### Как поднять новый демо-стенд, когда старый погашен

Два пути (оба отработаны 24.10.2026):

1. **Быстрый — из заготовки-бандла** (2–3 минуты, без сборки):
   `/srv/opencode/bundles/stand-<метка>.tar.gz` (на хосте разработки —
   `/srv/opencode-student/bundles/`) содержит собранные образы, скелет и `.env` с ключами.
   На новом VPS: датасеты в `/home/deployagent/datasets` → распаковать →
   `bash 98-deploy-from-bundle.sh <IP>` (сам ставит htpasswd, сертификат, TLS, датасеты,
   каталог и user-таймеры) → под root `bash /srv/opencode/sandbox/scripts/95-root-setup.sh`
   (квота + очистка + linger). **Все root-команды для Putty — в `ROOT-STEPS.md`**
   (bootstrap нового VPS, 95-root-setup, сервисные команды).
   Скрипты: `sandbox/scripts/97-make-stand-bundle.sh` (сборка бандла, теперь на живом стенде),
   `sandbox/scripts/98-deploy-from-bundle.sh` (подъём из бандла).

   **Что в бандле секретно — ровно один файл:** `env.template` (пароль стенда +
   ключ AI-шлюза `vck_…` + белый список моделей; права `600`). Скелет и образы
   ключей не содержат — проверено 28.10.2026: в скелете только `.env.example`,
   `grep` по слоям всех четырёх образов на `vck_` и на пароль стенда даёт 0,
   в образе песочницы нет `auth.json`/`opencode.db`. Ключ живёт в `.env` стенда
   (600) и в контейнере `gateway` (runtime env); в песочнице его нет, это
   проверяет `31-up-fast.sh --check`. Следствие: **бандл — сам по себе секрет**,
   его нельзя отдавать/публиковать; при утечке бандла менять ключ и пароль.

2. **Долгий — сборка на месте** (~10 минут): скопировать скелет, `bash scripts/30-up.sh`.
   Подробная инструкция — `DEPLOY_STAND.md` (в корне `students/`).

Ссылки на результаты студентов: `https://<IP-стенда>/files/...` — без пароля, закрыты CSP `sandbox`.

### Папка задачи на каждую сессию (с 27.10.2026)

Проблема: все студенты работают в одном `/work`, поэтому параллельные работы
перезаписывали друг друга (`output/dashboard.html` у всех одинаковый).

Решение: **каждая задача живёт в своей папке** `/work/sessions/<id>/output/`.

| Что | Где |
|---|---|
| Хелпер | `sandbox/tools/new_task.py` → в песочнице `python3 /opt/tools/new_task.py` |
| id | `OPENCODE_SESSION_ID`, если окружение его отдаёт (в песочнице отдаёт), иначе UTC-время + 2 случайных байта |
| Результат | `/work/sessions/<id>/output/<файл>.html` |
| Ссылка | `https://<IP>/files/sessions/<id>/output/<файл>.html` (проверено: 200; листинг каталога — 403) |

Почему python3, а не `sh script.sh`: политика песочницы разрешает без вопросов
`python3 *`, а `sh <скрипт>` уходит в «ask» — студент получал бы запрос разрешения
на первом же шаге каждой задачи (проверено живьём 27.10.2026).

Правило записано в двух местах, чтобы агент не пропустил: `SKILL.md` §10.1 и
`/work/AGENTS.md` (шаблон `sandbox/workspace.template/AGENTS.md`). Ночная очистка
и `90-reset.sh` сносят `sessions/` вместе со всей рабочей папкой.

### Hallmark и новый навык (с 27.10.2026)

- `sandbox/skills/economist-sandbox/SKILL.md` — версия «configurable-one-page-dashboard
  v0.5» (требования преподавателя) + §10 «Стендовые правила»: папка задачи,
  обязательный `check_page.py`, лимиты, каталог, Hallmark. §10 добавлен, чтобы
  сохранить правило 6 (проверка страницы до выдачи ссылки).
- Hallmark скопирован в `sandbox/skills/hallmark/` (копия `github.com/Nutlope/hallmark`,
  864 КБ, 104 файла) и монтируется в песочницу как `/opt/hallmark:ro`.
  Что есть/чего нет — `skills/hallmark/SANDBOX-NOTE.md`: картинки тем и `scripts/`
  не копировались, `sloplint` в песочнице недоступен (нет node), вместо него
  `check_page.py`.
- Новые монтирования в `docker-compose.yml` у сервиса `sandbox`: `./tools:/opt/tools:ro`,
  `./skills/hallmark:/opt/hallmark:ro`. После правки — `docker compose up -d --force-recreate sandbox`.

### Конструктор дашборда `/opt/viz/kit` (с 27.10.2026, вечер)

Причина появления: две студенческие сессии получали результат за 20–33 минуты
при готовых данных к 4-й минуте. Разбор логов показал, что модели заново пишут
50–60 КБ одного и того же движка (§2–§7), а потом 12–28 минут воюют с Chart.js
в headless-браузере и с собственными тест-скриптами. Итог: результат за
2–10 секунд проверок вместо десятков минут.

| Что | Где | Что делает |
|---|---|---|
| `engine.js` | `sandbox/docker/kit/` → `/opt/viz/kit` | движок страницы на чистом SVG/DOM: две иконки, панель настроек (Общие/Графики), наследование overrides, скрытие, Top N + «Остальные» по исходным строкам, клик-отбор, тёмная тема, сохранение автономного HTML, блок Skill.MD |
| `template.html`, `themes.py` | там же | оболочка + 4 темы Hallmark на системных шрифтах: `almanac`, `console`, `coral`, `furrow` |
| `dashboard.py` | там же | сборщик: `--spec spec.json --out page.html`; валидация spec (≤6 графиков, ≤3 фильтров, ≤4 KPI, ≤100 000 строк), понятные ошибки |
| `wb.py` | там же | World Bank: отбрасывает 42 макроагрегата по официальным кодам, добавляет регион, `add_last_flag()` (у стран разные последние годы) |
| `verify_page.py` + `selftest.js` | там же | 9 универсальных проверок интерактива через `window.DASH` |
| `examples/wb_country.py`, `examples/bank_share.py` | там же | готовые шаблоны: рейтинг + динамика + распределение + таблица; доля со знаменателем |
| `README.md` | там же | схема `spec.json` для модели |

Заодно починены стендовые утилиты (это были главные пожиратели времени):

- `check_page.py`: `console.log` больше не считается ошибкой (только `ERROR`),
  `--virtual-time-budget` 8000 → 2500 и таймаут 40 → 25 с, при зависании печатается
  памятка (Chart.js + `ResizeObserver`); проверяется, что страница вообще
  отрисовалась (пустой DOM, `canvas` 0×0); пути ищутся от cwd, потом от `/work`.
- `screenshot.py`: входной путь от cwd, `--out` относительный всегда от cwd
  (раньше `preview.png` уезжал в `/work`); при таймауте подсказка.

В `SKILL.md` добавлены §10.0 (порядок действий), §10.9 (kit), §10.10 (чтение
`/opt` через `cat`, точный путь к тексту навыка), §10.11 (антипаттерн Chart.js),
§10.12 (один вызов `question`, не писать свой тест-фреймворк), §10.13
(обязательный формат финального ответа: ссылка → отчёт → чек-лист студента).
§10.3 переписан: один прогон `check_page.py` + `verify_page.py` + один скриншот.

Сетка карточек зависит от числа графиков (`data-count`): 4 → 2×2, 3 → 3 в ряд,
5–6 → 3+3, 1–2 → по числу; высота в ряду выравнивается. Раньше на 1180 px
получалось «3 + 1» с карточкой другого размера.

После правок в `docker/kit/` нужен пересбор образа:
`docker compose build sandbox && docker compose up -d --force-recreate sandbox`.
**Ловушка:** `20-sync-workspace.sh` не перезаписывает существующие шаблоны, поэтому
обновлённые `workspace.template/AGENTS.md`/`README.md` надо класть в `/work` руками
(`docker exec -i -u 1000 … sh -c 'cat > /work/AGENTS.md'`).

## Ключевые пути

**На основном хосте `45.159.173.65`** (стенд `:4601`):

- Студенческого стенда здесь **нет**: docker не установлен, `/srv/opencode-student` отсутствует.
- Стенд — systemd, не docker: `systemctl --user status opencode-web caddy`.

**На старом хосте `94.141.97.249`** (оставлен для роллбэка; студенческий стенд погашен,
файлы не удалены):

- Исходники стенда: `/srv/opencode-student/sandbox/` (там `docker-compose.yml`, `scripts/`, `edge/`, `docker/`, `skills/`).
- Готовые образы стенда: docker images `opencode-student-*` (пока docker включён на хосте).
- Заготовки для быстрого подъёма: `/srv/opencode-student/bundles/stand-*.tar.gz`
  (на актуальном стенде — `/srv/opencode/bundles/`, там же `.sha256`).
- Мониторинг (старая копия, не запущен): `/srv/opencode-student/monitoring/`.
- Рабочая папка студентов (погашенного стенда): `/srv/opencode-student/workspace`.

**На демо-стенде `45.159.173.29`** (единственный актуальный; простой режим — см. раздел про провайдеров):

- Скелет: `/srv/opencode/sandbox/`; рабочая папка: `/srv/opencode/workspace`
  (владелец uid 1000 = uid песочницы в образе, **не** uid deployagent 1001).
- Папки задач студентов: `/srv/opencode/workspace/sessions/<id>/` (см. «Папка на каждую задачу»).
- Датасеты: `/home/deployagent/datasets`.
- Мониторинг: **не установлен**.

**В этом репозитории** (`/home/deployagent/projects/`): датасеты в `datasets/`,
каталог датасетов в `sandbox/catalog/`, инструкции — `students/DEPLOY_STAND.md`
(подъём с нуля на новом VPS), `students/DEPLOY_INSTRUCTIONS.md` (исторический разбор старого
хоста `94.141.97.249`).

Конфиг и навык стенда: `sandbox/config/opencode.json`, `sandbox/skills/economist-sandbox/SKILL.md`.

## Команды

Команды стенда выполняются **на том VPS, где он запущен** (демо-стенд: `45.159.173.29`).
Там `deployagent` в группе `docker`, поэтому `sg docker -c` не нужен:

```bash
ssh -i ~/.ssh/sandbox_new_ed25519 deployagent@45.159.173.29
cd /srv/opencode/sandbox
bash scripts/31-up-fast.sh                     # ПОСЛЕ РЕБУТА: поднять + проверить (--check — только проверка)
bash scripts/30-up.sh                          # поднять/пересобрать целиком
bash scripts/40-info.sh                        # инфо для студентов (--show покажет пароль)
bash scripts/50-verify-isolation.sh            # изоляция, 13 проверок
bash scripts/55-verify-stand.sh [url]          # стенд жив + очистка сработала
bash scripts/90-reset.sh                       # сброс между парами
docker compose ps / "logs -f sandbox"          # статус и логи
bash scripts/56-monitor.sh                     # дашборд нагрузки (см. ниже)
bash scripts/58-limits.sh                      # лимиты моделей: пул opencode + баланс шлюза
bash scripts/58-limits.sh --ping                # то же + живой запрос в бесплатную модель
```

На основном хосте (`45.159.173.65`) docker **не установлен** и студенческий стенд не
разворачивается — образы собираются на демо-стенде или берутся из бандла. Стенд `:4601` —
systemd, не docker: `systemctl --user status opencode-web caddy`.

### После перезагрузки сервера

Контейнеры поднимаются **сами**: `docker.service` включён в автозагрузку, у всех сервисов
`restart: unless-stopped`. Обычно делать ничего не нужно — достаточно проверить:

```bash
cd /srv/opencode/sandbox
bash scripts/31-up-fast.sh --check
```

`31-up-fast.sh` **не пересобирает образы и не трогает сертификат/htpasswd** (в отличие от
`30-up.sh`) — только поднимает контейнеры и проверяет, что живое. С проверками:

- все 5 контейнеров работают;
- в контейнере `gateway` есть ключ шлюза, в песочнице его **нет**;
- белый список моделей непуст;
- в UI 11 моделей (8 `opencode` + 3 `vercel-free`) и **нет платных** (считает сама
  проверка; 27.10.2026 провайдер `go-cheap` удалён, остались только бесплатные);
- модели `vercel-free` отвечают;
- стенд отвечает снаружи.

Если что-то не поднялось (или нужно пересоздать контейнеры после правки compose):

```bash
sg docker -c "bash scripts/31-up-fast.sh"        # без --check: поднять + проверить
```

Скрипт сам разберётся и в конце напечатает, что именно сломано. Проверен вживую:
после `docker compose stop` (имитация ребута) одна команда возвращает стенд в рабочее
состояние. Порядок запуска контейнеров не важен: список моделей берётся из конфига,
а не от прокси, поэтому sandbox может стартовать раньше gateway.

## Vercel AI Gateway (временно, до 2026-10-22)

Бесплатный лимит провайдера `opencode` (apiKey «public») **общий на весь стенд** — 25–30 студентов
делят один пул, и он исчерпывается. Тогда подключается запасной провайдер `vercel-free`
(Vercel AI Gateway) со своим ключом и своим балансом.

> **Наблюдение 28.10.2026:** на стенде `45.159.173.8` бесплатные лимиты выбрались
> **за одну пару** — это не поломка стенда, а исчерпание пула. Стенд погашен, занятия
> продолжаются на `45.159.173.29` / `45.159.173.38`. Если повторится: смотреть лимиты
> в кабинете провайдера, переключать дефолтную модель на другую бесплатную
> (`glm-5.3-flash-free`, `nemotron-3.5-lightning-free`) или уводить нагрузку на
> `vercel-free` через шлюз (там свой баланс ~15 USD, платная `zai/glm-5.3-flash` — резерв).

**Где смотреть лимиты (проверено 28.10.2026):**

| Что | Панель у провайдера | Наш способ |
|---|---|---|
| бесплатный пул `opencode` (apiKey «public») | **нет**: это не аккаунт, `x-ratelimit-*` провайдер не отдаёт | ответ `429 {"type":"FreeUsageLimitError"}` + заголовок `Retry-After` (окно суточное, сброс ~00:00 UTC, то есть 03:00 МСК); в стенде — `bash scripts/58-limits.sh` (считает такие ошибки в логе песочницы) |
| наш ключ Vercel AI Gateway (`vercel-free`) | да: vercel.com → AI Gateway → Usage (расход по моделям) | `GET https://ai-gateway.vercel.sh/v1/credits` → `balance` / `total_used` (28.10: 13.01 / 1.99 USD) — тоже в `58-limits.sh` |
| жив ли пул прямо сейчас | — | `bash scripts/58-limits.sh --ping` (однотокенный запрос реальным клиентом) |

Важная тонкость: прямой `curl` без клиентских заголовков получает `429` даже когда
стенд работает — лимит считается по клиенту/сессии, поэтому верить надо ошибкам
в логе настоящего клиента (`FreeUsageLimit`), а не ручным запросам.

### Простой / резервный режим (сейчас `45.159.173.29`)

Канонический скелет (`/srv/opencode-student/sandbox`) для этих режимов **не меняем** —
скрипты вариантов лежат в репозитории документации:
`students/stand-variants/simple-mode/` (58 — мониторинг лимитов, 59 — только бесплатные
модели, 61 — простой режим) и `students/stand-variants/reserve-open/` (62 — «без
ограничений», без навыка визуализации). На стенд их копируют в
`/srv/opencode/sandbox/scripts/` и запускают оттуда.

Текущая конфигурация `45.159.173.29` — **резервный стенд «без ограничений»**:

| Что | Как сейчас |
|---|---|
| Изоляция | нет: `SANDBOX_RUNTIME=runc`, `egress`/`gateway` в профилях compose, `sandbox_net` не internal → прямой интернет |
| Лимиты | `mem_limit` и `cpus` у песочницы **сняты** (`pids_limit` 512 остался) |
| Модели | все доступные бесплатные `opencode` — сейчас 7 (`nemotron-3-ultra-free` 28.10.2026 исчезла из каталога провайдера); скрыт только нерабочий `big-pickle` (`/work/opencode.json` + шаблон) |
| Ключи | **на диске нет**: из `.env` удалены `AI_GATEWAY_API_KEY` и `GATEWAY_ALLOWED_MODELS`, снесены `.env.bak`, развёрнутый бандл с `env.template` и сам тарбол бандла; сервис `gateway` удалён из compose (он и требовал ключ). Проверено `grep -rE "vck_\|sk-"` по `/srv/opencode`, `/home/deployagent`, `/etc` — пусто; в env контейнеров и в `opencode.db` — 0 |
| Навык визуализации | удалён целиком: `economist-sandbox` и `hallmark` не монтируются, `instructions` пуст, каталог `/opt/viz` из образа **скрыт пустым каталогом**, `catalog/` и датасеты в `/work/data` удалены |
| Политики агента | сняты: `shell` без спроса, `webfetch`/`websearch`/чтение `.env`/внешние каталоги разрешены; `provider.use` оставлены (иначе в UI всплывут сотни платных моделей) |
| Sudo для агента | `deployagent` получил `NOPASSWD: ALL` (`/etc/sudoers.d/90-deployagent`) — root-шаги здесь агент делает сам |
| Root в песочнице | `user: "0:0"`, `read_only: false`, `cap_drop` **снят** — иначе root без `CAP_DAC_OVERRIDE` не может писать файлы, принадлежащие uid 1000 (`/work`, том `/home/sandbox`) |
| Админ из UI | `/opt/tools/admin.py`: `show`, `password <новый>`, `ssh-key "<ключ>"`. Пароль → `.env` + `edge/htpasswd` (формат `{SHA}`), ключи → очередь `/srv/opencode/admin/ssh-keys.append`; применяют root-юниты `opencode-student-restart.path` (пересоздаёт контейнер) и `opencode-student-keys.path` (дописывает ключ в `authorized_keys` с правами 600) |
| Sudo внутри контейнера | нет: `sudo` в образе отсутствует, но процесс и так uid 0 |
| Память | `mem_limit` у песочницы снят, поэтому добавлен swap 2 ГБ (`/swapfile` + `/etc/fstab`, `vm.swappiness=20`) |
| Пароль | `demo` |

**Почему SSH-ключи идут через очередь.** `authorized_keys` нельзя монтировать в
контейнер на запись: sshd отказывается пускать по ключам, если файл доступен на
запись группе/миру, а из контейнера права владельца не сохранить (проверено —
`chmod 666` на файле = «Permission denied» при входе). Поэтому контейнер кладёт
ключ в очередь, а root-таймер дописывает его и выставляет `600 deployagent:deployagent`.

```bash
cd /srv/opencode
python3 sandbox/scripts/62-open-mode.py /srv/opencode
cd sandbox && docker compose up -d && docker compose restart sandbox
```

Проверено на стенде 28.10.2026: `7 opencode=7` в UI (одну модель провайдер убрал из
каталога), `example.com` из песочницы 200, агент выполняет `echo` в shell без
подтверждения, `/etc/opencode/skills` пуст, `31-up-fast --check` зелёный, root-таймер
автоочистки удалён (в `/etc/fstab` остались только образ квоты и swap).
Смена пароля и добавление SSH-ключа проверены живьём из UI-хелпера: пароль применился
(старый → 401, новый → 200 в API и на `/upload/`), ключ появился в
`authorized_keys` с правами 600. Перезагрузку сервера стенд переживает: контейнеры
поднимаются сами (`restart: unless-stopped`), `/work` монтируется из образа по
`fstab`, swap включается, path-юниты стартуют.

Ловушки:

- `/work/opencode.json` принадлежит uid 1000 — из-под `deployagent` не пишется:
  `docker exec -i opencode-student-sandbox sh -c 'cat > /work/opencode.json' < файл.json`.
- `50-verify-isolation.sh` на таком стенде **по определению красный** — не гонять.
- `check_page.py` под `runc` проверен: chromium запускается (опасения про
  `cap_drop: ALL`/`no-new-privileges` не подтвердились).
- `/work/AGENTS.md` и `README.md` заменены 28.10.2026 на нейтральные (без дашбордов,
  `/opt/viz`, `check_page` и навыка); копии — в `sandbox/workspace.template/`.
  Ночная автоочистка на этом стенде **отключена** (root: `systemctl disable --now
  opencode-student-cleanup.timer`), поэтому `/work` не стирается; подъём после
  ребута — сам (`restart: unless-stopped`), проверка — `scripts/31-up-fast.sh --check`.

Вернуть изоляцию: `docker compose --profile isolated up -d egress`, вернуть
`HTTP_PROXY/HTTPS_PROXY` и `internal: true` в compose (бэкапы рядом:
`config/opencode.json.bak-reserve`, `docker-compose.yml.bak-reserve`,
`/srv/opencode/.env.bak`), `SANDBOX_RUNTIME=runsc`.

**Как устроено (три части):**

| Где | Что | Зачем |
|-----|-----|-------|
| `config/opencode.json` → `provider."vercel-free"` | свой провайдер с явным списком из 3 моделей, `baseURL: http://gateway:8080/v1` | каталоговый `vercel` содержит 315 моделей, почти все платные. Ограничить каталог нельзя: `whitelist`/`blacklist` в `provider.*` на каталоговые модели **не действуют** (проверено), `provider.use` фильтрует только по провайдеру |
| контейнер `gateway` (`gateway/proxy.py`) | держит настоящий ключ, отдаёт наружу только модели из `ALLOWED_MODELS` | **ключ не должен лежать в песочнице** |
| `docker-compose.yml` → сервис `gateway` | ключ из `.env` → `AI_GATEWAY_API_KEY`, белый список → `ALLOWED_MODELS` | прокси ходит в шлюз через свою сеть `egress_out`, мимо allowlist песочницы |

**Почему ключ нельзя класть в песочницу (проверено на живом стенде):** агент читает
`/proc/self/environ` и достаёт оттуда переменные окружения, а `curl`/`wget` запрещены
политикой, но `urllib` — нет. С ключом в окружении студент уходил в шлюз **платной**
моделью (`openai/gpt-5-nano` → HTTP 200), минуя и список моделей, и лимит. Поэтому:
ключ живёт только в контейнере `gateway` (uid 65534), в песочнице его нет — ни в
environ, ни в файлах.

**Модели (с 23.10.2026):**

| Модель | Статус |
|---|---|
| `zai/glm-5.3-flash` | **резерв, платная** (~0.15$/M input, ~0.5$/M output) — на случай, когда у бесплатных кончатся лимиты |
| `reflection/beam-free` | бесплатна, цена 0 |
| `nvidia/nemotron-3.5-lightning-free` | бесплатна, цена 0 |

Бесплатный провайдер `opencode` отдаёт 9 моделей (проверено 27.10.2026: `beam-free`,
`deepseek-v4.1-flash-free`, `flint-40b-free`, `glm-5.3-flash-free`, `mimo-v2.6-flash-free`,
`nemotron-3-ultra-free`, `nemotron-3.5-lightning-free`, `nemotron-3.5-super-vl-free`,
а также `big-pickle`, которая в каталоге есть, но при запуске отвечает
«Model unavailable»). Поэтому `big-pickle` скрыта через project-конфиг
`/work/opencode.json` (шаблон `workspace.template/opencode.json`), и в UI остаётся
**8 + 3 = 11 моделей**. Модели `longcat-2.5-preview-free` у провайдера больше нет
вообще — вернуть её нельзя.
Список — в `config/opencode.json` (`provider."vercel-free".models`) и в `.env`
(`GATEWAY_ALLOWED_MODELS`). **Списки должны совпадать**: прокси отклоняет всё, чего
нет в его белом списке, а UI показывает то, что описано в конфиге.

**Провайдер подписки `go-cheap` УДАЛЁН 27.10.2026** по решению преподавателя: стенд
работает только на бесплатных моделях. Ключ подписки был в конфиге (то есть в
песочнице) — считать его скомпрометированным и, если подписка понадобится снова,
сменить у провайдера. Дефолтная модель теперь `opencode/deepseek-v4.1-flash-free`.

**Ключ:** `/srv/opencode-student/sandbox/.env` → `AI_GATEWAY_API_KEY` (файл в gitignore,
права 600). В UI провайдер подключать не нужно — он описан в конфиге.

**Применить (после правки конфига/прокси/белого списка):**

```bash
cd /srv/opencode-student/sandbox
sg docker -c "docker compose build gateway && docker compose up -d gateway"
sg docker -c "docker compose restart sandbox"     # правило 7: конфиг — только при рестарте
sg docker -c "bash scripts/31-up-fast.sh --check"   # самопроверка (в т.ч. что ключ не утёк)
```

**Проверка:** проще всего одной командой — `sg docker -c "bash scripts/31-up-fast.sh --check"`.
Она проверяет всё перечисленное ниже и печатает, что именно сломано. Вручную:

```bash
# 1) в UI 11 моделей: 8 opencode + 3 vercel-free
sg docker -c "docker exec opencode-student-sandbox sh -lc 'curl -s -u opencode:\"\$OPENCODE_SERVER_PASSWORD\" http://127.0.0.1:4096/api/model'"

# 2) модели отвечают
sg docker -c "docker exec opencode-student-sandbox opencode run -m vercel-free/zai/glm-5.3-flash 'say ok'"

# 3) ключа в песочнице нет (должно быть 0 и 0)
sg docker -c "docker exec opencode-student-sandbox sh -lc 'cat /proc/self/environ | tr \"\\0\" \"\\n\" | grep -c AI_GATEWAY'"

# 4) платная модель через прокси не проходит (должен быть 403)
sg docker -c "docker exec opencode-student-sandbox python3 -c 'import urllib.request,json;urllib.request.urlopen(urllib.request.Request(\"http://gateway:8080/v1/chat/completions\",data=json.dumps({\"model\":\"openai/gpt-5-nano\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}).encode()))'"
```

**Откат:**

```bash
cd /srv/opencode-student/sandbox
# 1) в config/opencode.json: убрать блок "provider" → "vercel-free" и строку
#    provider.use "vercel-free" в policies; model вернуть opencode/*-free
#    rate limit на opencode/deepseek-v4.1-flash-free: тогда его тоже придётся чем-то закрывать
# 2) в .env: убрать AI_GATEWAY_API_KEY и GATEWAY_ALLOWED_MODELS
# 3) в docker-compose.yml: убрать сервис gateway, из environment sandbox убрать
#    gateway из NO_PROXY и extra_hosts
# 4) в egress/allowlist: убрать правило ai-gateway.vercel.sh (и пересобрать egress)
sg docker -c "docker compose build gateway egress && docker compose up -d gateway egress"
sg docker -c "docker compose restart sandbox"
```

**Где лежат креды (важно):** в OpenCode 2.x ключи **не** в `~/.local/share/opencode/auth.json`
(файла нет вообще), а в SQLite `opencode.db`, таблица `credential`. Поэтому «ключ не сохранился» —
обычно просто искали не там. Штатно: `opencode auth export` (JSON с секретами), `opencode auth list`
(без секрета). Удаление записи через API **не стирает** ключ из файла БД — нужен `VACUUM`,
иначе `grep` по файлу его найдёт.

**Подводные камни:**

- **Ночная очистка сносит ключ в БД контейнера** (`90-reset.sh` чистит `~/.local/share/opencode/*`).
  Сейчас это не страшно: ключ берётся из `.env` хоста, а не из БД. Если вернёте схему
  «ключ в БД» — вбивать заново.
- **Баланс общий** (~15 USD, сейчас 14.73). Пока прокси на месте, студент потратить его
  не может: платные модели режутся на прокси (403), а бесплатные стоят 0. Но если прокси
  выключить и вернуть прямой доступ к шлюзу — риск вернётся.
- **Модель по умолчанию.** С 23.10.2026: `opencode/deepseek-v4.1-flash-free` (бесплатная).
  Заметка: на нём раньше замечали rate limit — если станет мешать парам, искать следующего дефолта
  среди бесплатных (`glm-5.3-flash-free`, `nemotron-3.5-lightning-free`).
- **Контейнер `gateway` переживает рестарт** (`restart: unless-stopped`), но при
  `docker compose down` поднимается только вместе со всем стендом.

Подробности — `HANDOFF_TO_NEXT_AGENT.md`, приложение Г.

## Правила, которые нельзя нарушать

1. **`edge/sw.js` — свой** (не workbox): штатный service worker OpenCode перехватывает любую
   навигацию и отдаёт UI → «Unrecognised route!». Не заменять на штатный.
2. **CSP `sandbox` у `/files/` обязателен** — не даёт HTML из песочницы выполнять в origin UI.
   Если возвращать basic-auth на `/files/`, это отдельное решение.
3. **Правка `edge/site.*.conf` применяется через `docker compose restart edge`**, не `nginx -s reload`
   (envsubst работает только при старте контейнера).
4. **`WORKSPACE` в скриптах — абсолютный** (`/srv/opencode-student/workspace`), дефолт датасетов —
   `/home/deployagent/projects/datasets`, подъём песочницы в `trap` при любом исходе.
5. **Ночная очистка (root, 03:30 UTC) удаляет всё**, включая `data/`; user-таймер
   `opencode-student-restore.timer` (03:40) возвращает датасеты. `lost+found` не удалять (ext4).
6. **Лимиты в SKILL.md обязательны**: ≤6 графиков, ≤3 фильтра, ≤1 доп. показатель, ≤100 000 строк;
   агент обязан прогнать страницу через `python3 /opt/viz/check_page.py` и не отдавать ссылку,
   пока проверка не зелёная.
7. **Правки `config/opencode.json` и навыка** применяются после `docker compose restart sandbox`.
8. **DNS под gVisor не работает**: сохранять статические IP egress `172.28.0.254`, edge `172.28.0.5`
   и `extra_hosts` у sandbox, иначе песочница теряет прокси.
9. **TLS короткоживущий (~6 дней, LE на IP, профиль shortlived)**: продление — таймер
   `opencode-student-cert.timer` (04:17 UTC). Проверка: `openssl x509 -enddate -noout -in edge/certs/fullchain.pem`.
10. **Скрывать сломанные модели — только через `/work/opencode.json`** (project-конфиг),
    а не через `/etc/opencode/opencode.json`: managed-конфиг (`/etc/opencode/`) имеет
    высший приоритет, и студент не смог бы вернуть модель себе. Сейчас там скрыта
    `big-pickle` (в каталоге есть, при запуске — «Model unavailable»); `longcat`
    у провайдера больше нет.

## Модели и проекты стенда

### Модели: только бесплатные (с 27.10.2026)

Провайдер подписки `go-cheap` удалён по решению преподавателя: стенд работает на
бесплатном пуле `opencode` (8 моделей) и на `vercel-free` через прокси-шлюз (3 модели).
Итого в UI **11** моделей, платных нет.

`longcat-2.5-preview-free` и `longcat-2.0-free` провайдер больше не отдаёт
(«Model unavailable») — вернуть нельзя. `big-pickle` в каталоге есть, но при запуске
тоже «Model unavailable», поэтому она скрыта через project-конфиг, чтобы студенты
не выбирали сломанную модель.

| Что | Где |
|---|---|
| Скрывающий файл (шаблон) | `sandbox/workspace.template/opencode.json` → `/work/opencode.json` |
| Как показать модель студенту | убрать `"disabled": true` в `/work/opencode.json` → «Reload configuration» (`Ctrl+P`) |
| Как применить правку всем | тот же файл + `bash scripts/20-sync-workspace.sh` (или руками в `/work`) |

**Почему именно project-конфиг.** В OpenCode 2.0.32 конфиги сливаются в таком
порядке (позже побеждает): remote → `~/.config/opencode` → `OPENCODE_CONFIG` →
project → `OPENCODE_CONFIG_CONTENT` → **managed (`/etc/opencode/`)**. Политики
(`policies`) из managed-конфига, наоборот, имеют высший приоритет и студент их
не переопределит. Отсюда два правила:

- ключ V2 — **`providers`** (не `provider`): в V1-ключе `provider` поле `disabled`
  у модели молча выбрасывается при парсинге (проверено);
- `disabled: true` у модели убирает её из `/api/model` совсем, и сервер отдаёт
  404 при попытке ею пользоваться — то есть включить её может только тот, кто
  снимет флаг в конфиге.

### Набор датасетов (обновлён 27.10.2026)

25 CSV (~2.2 МБ), только экономика, у каждого в `README.md` есть **число строк и размер**:

- **микро:** `bank.csv` (4 521, UCI Bank Marketing, разделитель `;`),
  `car_evaluation.csv` (1 728), `wholesale_customers.csv` (440);
- **макро:** 20 файлов `wb_*.csv` — показатели World Bank 2015–2023 по странам
  (ВВП, ВВП на душу, рост, ВНД, инфляция, безработица общая и молодёжная, участие
  в рабочей силе, налоги, госдолг, образование, здравоохранение, экспорт, импорт,
  ПИИ, Джини, население, бедность, промышленность, переводы); форма одинаковая
  (`country, country_code, year, <показатель>`) → файлы соединяются по стране и году;
- **временные ряды:** `owid_gdp_per_capita.csv`, `owid_consumer_price_index.csv` (OWID).

- **В `wb_*.csv` лежат не только страны:** кроме ~200 стран в колонке `country`
  есть 42 макроагрегата Всемирного банка (`World`, `Euro area`, `OECD members`,
  `Sub-Saharan Africa`, `High income`, `IDA only`…). Без фильтра «World» встаёт
  первым в рейтинге стран. Отбрасывать — `from wb import load` (`/opt/viz/kit/wb.py`,
  официальные коды агрегатов); предупреждение добавлено в `datasets/README.md`.
- Источник правды: `projects/datasets/` (там же `README.md`, он же копируется в `/work/data`).
- На стенде: `/home/deployagent/datasets` → `bash scripts/20-sync-workspace.sh`
  (кладёт в `/work/data` **только для чтения**).
- `bank.csv` совпадает с примером в `SKILL.md` §8 (job / education / contact /
  housing / month / balance / duration / y).
- Сборщик набора (не в репозитории, разовый): WB API + UCI + OWID, см.
  `HANDOFF_TO_NEXT_AGENT.md`, если нужно обновить цифры.

### Дефолтный проект стенда — `work`

В UI OpenCode «проект» — это рабочая папка. У стенда их ровно одна:

```
/work  →  имя "work"
```

- Имя проекта живёт в БД (`opencode.db`), а `90-reset.sh` базу чистит → после
  сброса проект появляется заново без имени. Поэтому есть скрипт
  `sandbox/scripts/92-project-work.sh`: он возвращает имя `work` и поднимает
  активность проекта (по активности OpenCode выбирает проект по умолчанию).
  Вызывается из `30-up.sh`, `31-up-fast.sh` и `90-reset.sh`.
- Лишние проекты (`/work/data`, `/opt/catalog` и т.п.) создаются, когда студент
  сам открывает подпапку. Их можно убрать: `time_archived` в таблице `project`
  (сделано 2026-10-22; при следующем `resolve()` проект оживает сам).
- Локальная (браузерная) часть выбора проекта живёт в localStorage, сервер её
  не контролирует: у вернувшегося студента останется тот проект, который он
  открывал last. Для свежего браузера дефолт — `/work`.

## Текущее состояние и остатки (перед выдачей студентам)

- Стенд готов: изоляция 13/13, TLS доверенный, service worker и самопроверка агента в браузере починены.
- [ ] Сменить пароль `<SANDBOX_PASSWORD>` (`.env` + `scripts/30-up.sh`).
- [ ] Убрать `deployagent` из группы `docker` (после приёмки; учтя, что таймеры требуют её).
- [ ] Решить судьбу старого стенда `:4601`.
- [ ] `/files/` без пароля — осознанный компромисс, между студентами приватности нет.

## Мониторинг

Два независимых инструмента.

**1. Текстовый дашборд стенда** — `/srv/opencode-student/sandbox/scripts/56-monitor.sh`:
одиночный снимок состояния сервера, обоих стендов, контейнеров, сессий и логов.
Живой режим: `watch -n 10 .../56-monitor.sh`. История (с флагом `--log`):
`/tmp/opencode/monitor.log`. Всё читает, ничего не меняет.

**1б. Лимиты моделей** — `scripts/58-limits.sh`: ошибки `FreeUsageLimit` в логе песочницы,
баланс нашего ключа Vercel AI Gateway, число моделей в UI; с `--ping` — живой
однотокенный запрос. Панели у бесплатного пула нет, это единственный способ
увидеть, что он кончился (подробнее — раздел про провайдеров).

**2. Веб-панель Beszel** — графики по каждому сервису (CPU/RAM/сеть/диск, история ~30 дней).
**Сейчас не поднята ни на одном актуальном стенде**: последняя жила на машине, которую
пришлось бросить (адрес уехал к другому владельцу). Рабочая копия каталога (compose, `.env`,
`change-password.py`) осталась на хосте разработки: `/srv/opencode-student/monitoring/` —
оттуда панель можно поднять на любом стенде. Не путать с проектом стенда `opencode-student`.

| | |
|---|---|
| Логин/пароль | `admin@beszel.local` / из `monitoring/.env` → `BESZEL_ADMIN_EMAIL` / `BESZEL_ADMIN_PASSWORD` |
| Порт | `8090`, без TLS (пароль идёт открытым текстом — если поднимать снова, закрывать через edge) |
| Сводка из консоли | `python3 /tmp/opencode/beszel_summary.py "$(curl -s ...)"` — ключи в API сжаты (`c`=cpu, `m`=mem MB, `n`=имя, `b`=[in,out] KB/s) |
| Что мониторит | систему-хост и контейнеры стенда; агент ходит в `docker.sock` **read-only** |

Как устроено: `beszel` (hub, порт 8090) + `beszel-agent` (host-сеть, слушает unix-сокет
`./socket/beszel.sock`, ходит в docker.sock **read-only** для метрик контейнеров).
Hub достаётся до агента по сокету, поэтому наружу не торчит лишний порт (45876 закрыт).
Расход самого мониторинга ~20 МБ RAM.

Важные особенности:

- **Список систем задаётся в `monitoring/data/config.yml`**, а не кликами в UI: hub при старте
  синхронизирует БД с этим файлом и **удаляет** системы, которых там нет. Добавлять системы
  через UI бессмысленно — после перезапуска исчезнут. Правится файл, потом `docker compose restart beszel`.
- Hub генерирует ed25519-ключ в `monitoring/data/id_ed25519`; его публичная часть прописана
  в `monitoring/.env` → `BESZEL_HUB_KEY`. Если hub пересоздан с нуля — ключ обновить
  (через `GET /api/beszel/info` под авторизацией) и перезапустить агента.
- `USER_EMAIL`/`USER_PASSWORD` создают админа **только при самом первом старте** (миграция).
  Живой пароль лежит в SQLite (`monitoring/data/data.db`), а env влияет только на первый старт.
  **Смена пароля через UI (Settings → Users) работает не всегда**: у коллекции `users`
  `updateRule` пуст, обычным токеном PATCH даёт 403 «Only superusers can perform this action».
  Рабочий путь — скрипт `monitoring/change-password.py` (меняет и запись `users`, и
  PocketBase-суперюзера, затем синхронизирует `monitoring/.env` и пересоздаёт hub).
- **Пароль панели сейчас совпадает с паролем стенда** (`SANDBOX_PASSWORD` в
  `sandbox/.env`, т.е. `<SANDBOX_PASSWORD>`) — так решил преподаватель 2026-10-21.
  Учти: этот пароль знают студенты, а порт 8090 открыт наружу без TLS → панель мониторинга
  доступна студентам. Смена стендового пароля требует и смены пароля Beszel
  (иначе они разойдутся).
- Файлы БД в `monitoring/data/` создаются контейнером под root. deployagent каталог удалит,
  а вот файлы внутри — нет (нет sudo); `docker compose down && rm -rf data/*` как workaround.
- **Порт 8090 открыт без TLS** (пароль уходит открытым текстом) — тот же компромисс, что и
  у `/files/`. Если захочется закрыть: либо bind на `127.0.0.1` + SSH-туннель, либо пробросить
  location через существующий edge (правило 3: правка `site.*.conf` + `docker compose restart edge`).
- Ночная очистка (root, 03:30) ходит только в `/srv/opencode-student/workspace` — мониторинг
  и его история ей не затрагиваются. `56-monitor.sh` грепает контейнеры по префиксу
  `opencode-student-`, так что новые `opencode-monitor-*` ему не мешают.
- История: ~7 дней в высоком разрешении + до 30 дней почасовых агрегатов, чистка автоматическая
  (cron в hub, `delete old records`). Настроить короче нельзя — это зашито в Beszel.
