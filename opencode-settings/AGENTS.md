# Проект `opencode-settings` — настройка основного стенда `https://45.159.173.65:4601`

Здесь обсуждаются и делаются настройки **основного стенда разработки** (`:4601`), который
крутится прямо на этом же хосте. Студенческие/демо-стенды (docker, edge, датасеты,
изоляция) — **отдельный проект `students/`**, его правила в `students/AGENTS.md`.

Снимок фактического состояния с датами и цифрами: `docs/snapshot-2026-10-29.md`
(снимок старого хоста `94.141.97.249` — `docs/snapshot-2026-10-28.md`, оставлен как история).
Переезд на новый VPS **выполнен 29.10.2026**: `docs/migration-runbook-2026-10.md` — что переносили,
как поднимали стенд с нуля, что делать со студенческим стендом (отдельная одноразовая VPS) и как
экспортировать данные (`scripts/export-main-stand.sh`); старый хост `94.141.97.249` не выключен и
используется как роллбэк.
Правило: **перед любой правкой сверяться со снимком** — конфиг здесь почти пустой,
всё «на дефолтах», поэтому легко по незнанию переписать чужое.

---

## 1. Что развёрнуто

Это **не docker**. Два systemd-**user**-сервиса (не системные, не root); таймера
продления сертификата нет — им занимается сам Caddy (ACME, см. «TLS»).

| Юнит | Что | Слушает |
|---|---|---|
| `opencode-web.service` | `opencode serve --hostname 127.0.0.1 --port 4600 --print-logs` | `127.0.0.1:4600` |
| `caddy.service` | `~/bin/caddy run --config ~/.config/caddy/Caddyfile` | `*:4601` (TLS), `:80` — только на время ACME-проверки |

Юнит-файлы: `~/.config/systemd/user/`. У пользователя `deployagent` включён **linger**
(`Linger=yes`), поэтому сервисы живут без активной SSH-сессии и поднимаются после ребута.

Схема запроса: `клиент → https://45.159.173.65:4601 (Caddy, TLS) → 127.0.0.1:4600 (opencode)`.

Хост: `45.159.173.65`, hostname `opencode-main` (Ubuntu 26.04 LTS). Старый хост
`94.141.97.249` (hostname `opencode`) оставлен включённым для роллбэка: на нём тот же
стенд на `:4601`, но TLS продлевается старой certbot-схемой (`oc-cert-renew.timer`).

### Ключевые пути

| Что | Путь |
|---|---|
| Бинарь OpenCode | `~/.opencode/bin/opencode` (v2.0.32, channel `latest`) |
| Рабочий каталог сервера (корень проектов) | `~/projects` (в юните `WorkingDirectory=%h/projects`) |
| Переменные окружения сервиса | `~/.config/opencode-web.env` (права 600) |
| Пользовательский конфиг | `~/.config/opencode/opencode.jsonc` (**сейчас практически пустой**) |
| Плагины | `~/.config/opencode/package.json` → `@opencode-ai/plugin` 1.19.3 + `node_modules/` |
| База OpenCode (сессии, креды) | `~/.local/share/opencode/opencode.db` (SQLite, 600) |
| Конфиг Caddy | `~/.config/caddy/Caddyfile` |
| TLS-сертификат | `~/.local/share/caddy/certificates/<IP>/` (Caddy хранит и отдаёт сам) |
| Продление TLS | автоматически Caddy (ACME Let's Encrypt, профиль `shortlived` ≈ 6 суток) |
| Состояние ACME и сертификаты | `~/.local/share/caddy` (аккаунт LE + сертификаты, 700) |
| Статика `/normal-forms/` | `/home/deployagent/web/normal-forms` (отдаёт Caddy) |
| Аварийное восстановление | `~/bin/oc-fix.sh` (см. §5) |
| Чистка списка проектов в БД | `scripts/archive-projects.py` (в этом проекте) |
| Экспорт для переезда на новый хост | `scripts/export-main-stand.sh` (в этом проекте) |
| Bootstrap нового хоста (root, один раз) | `scripts/new-host-bootstrap.sh` (в этом проекте) |
| Бэкапы БД | `~/tmp/opencode-backups/opencode-<дата>.db` (600; каталог создаётся при первом бэкапе) |

### Аутентификация

* HTTP **basic-auth** на уровне сервера OpenCode: логин `opencode`, пароль из
  `~/.config/opencode-web.env` → `OPENCODE_SERVER_PASSWORD` (в чатах и доках пароль
  не печатать, ссылаться на файл).
* `/` (оболочка UI) отдаётся **без** пароля — это нормально, там только статика;
  `/api/*` без пароля даёт **401**.
* TLS — Let's Encrypt на IP, **Caddy выпускает и продлевает сертификат сам**
  (`tls { issuer acme { profile shortlived } }`, срок ≈ 6 суток, продление автоматическое).
  Отдельного certbot/таймера и общих сертификатов со студенческим стендом больше нет;
  `auto_https disable_redirects` оставлен, чтобы Caddy не пытался слушать 443 и не делал
  редирект с 80.

### Провайдеры и модели (353 в каталоге)

Ключи лежат **не** в `auth.json` (файла нет), а в SQLite `opencode.db`, таблица `credential`:

| Провайдер | Моделей | Ключ | Комментарий |
|---|---|---|---|
| `vercel` | 315 | Vercel AI Gateway (в БД) | каталоговый, **почти все модели платные** |
| `opencode-go` | 30 | подписка OpenCode Go (в БД) | платные (`glm-5.3`, `kimi-k3`, `gpt-6-luna`…) + `*-free` |
| `opencode` | 8 | публичный (бесплатный пул) | `deepseek-v4.1-flash-free` (дефолт), `glm-5.3-flash-free`, `nemotron-3.5-*`, `beam-free`, `flint-40b-free`, `mimo-v2.6-flash-free`, `big-pickle` (сломанная) |

**Белого списка нет:** `/etc/opencode/` отсутствует, `provider.use`/`disabled` не заданы,
`opencode.jsonc` содержит только `$schema`. Значит любая сессия может уйти в платную
модель и потратить баланс — это осознанный режим «без ограничений», а не недоделка.

Навыков (`skills/`) и `instructions` нет — это чистый OpenCode, без стендовых
дополнений вроде `economist-sandbox` / `hallmark` / `/opt/viz`.

---

## 2. Ресурсы и жёсткие ограничения

| Параметр | Значение (29.10.2026) |
|---|---|
| ОС | Ubuntu 26.04 LTS |
| CPU | **1 vCPU** |
| RAM | **2646 МБ** (~416 МБ занимает сам `opencode serve`) |
| Swap | `/swapfile` 2 ГБ, `vm.swappiness=10`, занято 0 |
| Диск | `/` 29 ГБ, занято 4.2 ГБ (16 %) |
| Docker | **не установлен** — на этом хосте контейнеры не запускаются |
| Лимит задач в юните | `Tasks: 37 (limit: 1683)` |
| Открытые наружу порты | 22 (ssh), 80 (только на время ACME-проверки), 4601 (caddy) |
| Свободные 80/443 | да — студенческий стенд живёт на отдельной VPS |

Практические следствия:

1. **Docker здесь не установлен** — образы стенда собираются на демо-стенде или
   берутся из бандла, см. `students/AGENTS.md`.
2. **1 vCPU — узкое место**, а не память. Один тяжёлый прогон (headless-Chromium, сборка,
   `npm install`) тормозит всё, включая UI.
3. **Сервисы — user-scope.** `systemctl --user …` от `deployagent`. Из root-консоли нужен
   `sudo -u deployagent XDG_RUNTIME_DIR=/run/user/1001 systemctl --user …` либо `oc-fix.sh`.
4. `TMPDIR=/home/deployagent/tmp` (из env сервиса). Файлы класть туда, а не в `/tmp`.

---

## 3. Риски, которые надо знать заранее

1. **Сертификат живёт ~6 суток (профиль shortlived).** Его выпускает и продлевает **сам
   Caddy** (ACME, `tls { issuer acme { profile shortlived } }` в Caddyfile), без certbot,
   таймеров и root. Проверка: `echo | openssl s_client -connect 45.159.173.65:4601
   -servername 45.159.173.65 | openssl x509 -noout -issuer -dates` — дата должна быть
   в будущем. Если сертификат не отдаётся/рассинхронизирован — `systemctl --user restart
   caddy` (Caddy кэширует файлы), при необходимости `bash ~/bin/oc-fix.sh`.
2. **Старый хост `94.141.97.249` — роллбэк, не выключать.** Там остался свой стенд на
   `:4601` со своей БД и certbot-схемой продления (`oc-cert-renew.timer`); после переезда
   данные на нём устаревают. Пока идёт наблюдение, правки делать только на новом хосте,
   иначе состояния разъедутся.
3. **Ключи платных провайдеров лежат в БД в открытом виде.** `opencode.db` — 600, но любой
   процесс под `deployagent` (в том числе агент в сессии) может их прочитать. Удаление
   креда через API **не стирает** его из файла: нужен `VACUUM`.
4. **`/` отдаётся без пароля** (только оболочка UI, `api` — 401). Если это неприемлемо,
   закрывать basic-auth на уровне Caddy.
5. **Мусорные проекты в БД.** После переезда в базе 18 записей: 8 активных и 10 в архиве.
   Активных больше, чем реальных проектов, из-за дублей `/home/deployagent/projects`
   (4 записи: корень + вложенные сессии) — на новом хосте `archive-projects.py` ещё не
   прогонялся. Строки появляются сами: проект в OpenCode — это папка, запись создаётся при
   старте сессии в каталоге и не удаляется, если папку убрать (отсюда `/demo/opencode-sandbox/...`
   с прежнего хоста, `/tmp/opencode` — старый `TMPDIR`). Чистится
   `python3 scripts/archive-projects.py` (план) → `--apply`: выставляет `time_archived`,
   делает бэкап БД через sqlite3 backup API, не трогает `global`, сводит дубли путей к самой
   свежей записи. Актуальные пути — список `KEEP` в начале скрипта; при заведении нового
   проекта дописать его туда. Мягкая архивация обратима (`time_archived = NULL`), и папка
   «оживает» сама, если её снова открыть.
6. **Студенческого стенда на этом хосте нет** (и `/srv/opencode-student` отсутствует).
   Не разворачивать его здесь: по правилу проекта он живёт только на отдельной одноразовой
   VPS, см. `students/AGENTS.md`.

---

## 4. Команды

```bash
# статус и порты
systemctl --user status opencode-web caddy
ss -ltnp | grep -E '4600|4601'
journalctl --user -u opencode-web -n 100 --no-pager      # логи сервера
journalctl --user -u caddy -n 50 --no-pager

# жив ли снаружи (пароль — из ~/.config/opencode-web.env)
curl -sk -o /dev/null -w '%{http_code}\n' https://45.159.173.65:4601/api/model    # ждём 401
curl -sk -u opencode:"$PW" -o /dev/null -w '%{http_code}\n' https://45.159.173.65:4601/api/model  # 200

# модели в каталоге
curl -s -u opencode:"$PW" http://127.0.0.1:4600/api/model \
  | python3 -c "import sys,json,collections;d=json.load(sys.stdin)['data'];print(len(d),collections.Counter(m['providerID'] for m in d))"

# сертификат: кто выпустил, сроки, что лежит в хранилище Caddy
echo | openssl s_client -connect 45.159.173.65:4601 -servername 45.159.173.65 2>/dev/null \
  | openssl x509 -noout -issuer -dates
ls ~/.local/share/caddy/certificates/*/
journalctl --user -u caddy -n 50 --no-pager   # выпуск/продление ACME

# перезапуск после правки конфига/юнита (это user-scope!)
systemctl --user restart opencode-web        # конфиг opencode.jsonc читается при старте
systemctl --user reload caddy                # Caddyfile или новые файлы сертификата (graceful)
systemctl --user restart caddy               # если reload не подхватил файлы сертификата

# проверить Caddyfile без применения
~/bin/caddy validate --config ~/.config/caddy/Caddyfile

# список проектов в БД: план / применить (правит KEEP в scripts/archive-projects.py)
python3 ~/projects/opencode-settings/scripts/archive-projects.py
python3 ~/projects/opencode-settings/scripts/archive-projects.py --apply
```

---

## 5. Правила работы в этом проекте

1. **Сначала снимок, потом правка.** Перед изменением конфига/юнита: `systemctl --user
   status opencode-web`, `ss -ltnp`, `cp` правимого файла в `.bak-ГГГГММДД`.
2. **Правки конфига OpenCode применяются рестартом** `opencode-web` (не «reload»).
   Правки `Caddyfile` — `systemctl --user reload caddy` (в юните есть `ExecReload`,
   соединения не рвутся) или рестартом. Сертификат Caddy выпускает и обновляет сам;
   после смены `tls`/IP в конфиге может понадобиться рестарт, а не reload.
3. **Пароли, ключи и содержимое `credential` в чат не выводить.** Ссылаться на файлы
   (`opencode-web.env`, `opencode.db → credential`). В документации — только пути.
4. **Не смешивать со студенческим стендом.** Всё, что про docker, edge, изоляцию,
   датасеты, навыки, лимиты моделей для студентов — проект `students/`. Здесь — только
   `:4601`: юниты, Caddy, провайдеры, модели, конфиг, ресурсы хоста.
5. **Помнить про 1 vCPU / 2.6 ГБ.** Не запускать на этом хосте сборки, не ставить
   тяжёлые сервисы (Postgres и подобное — только если реально нужно, с `mem_limit`-ами
   и пониманием, что CPU один).
6. **Проверять после каждого вмешательства:** оба юнита `active`, `/api/model` = 200 с
   паролем и 401 без, сертификат не просрочен. Если сломалось — `bash ~/bin/oc-fix.sh`.
7. **Не разворачивать студенческий стенд на этом хосте** (ни docker, ни edge) без явной
   просьбы: он живёт на отдельной одноразовой VPS, см. `students/AGENTS.md`.

---

## 6. Чек-лист «стенд `:4601` жив»

- [ ] `systemctl --user is-active opencode-web caddy` → `active active`
- [ ] `ss -ltnp | grep 4600` → слушает только `127.0.0.1`
- [ ] `https://45.159.173.65:4601/` открывается, без пароля `/api/model` даёт 401
- [ ] с паролем `/api/model` даёт 200 и 353 модели (8 `opencode` + 30 `opencode-go` + 315 `vercel`)
- [ ] `openssl x509 -enddate` (или `openssl s_client`) — дата в будущем; сертификат выпущен
      Caddy, отдельного таймера продления нет
- [ ] `free -m` — `available` ≥ 500 МБ, swap почти не тронут
