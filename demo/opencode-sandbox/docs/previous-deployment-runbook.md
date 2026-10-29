# Runbook + журнал действий: развёртывание OpenCode v2 с веб-интерфейсом на VPS

> Экспортированный технический лог работы ИИ-агента и инструкция для других агентов.
> Дата работы: 18 октября 2026. Разделы 1–7 — инструкция; раздел 8 — хронологический журнал реально выполненных действий.
> Пароли и credential-URL в тексте редоктированы (`<ПАРОЛЬ>`). Это журнал действий, а не полный дословный транскрипт.
> Исходная сессия: https://www.perplexity.ai/computer/tasks/2bb35640-eef9-4972-8630-9d5e722ce836

## 1. Контекст и цель

| Параметр | Значение |
|---|---|
| Сервер | VPS, IP `94.141.97.249`, SSH-порт `22` |
| ОС | Ubuntu 26.04 LTS (x86_64), 2 vCPU, 3.3 ГБ RAM, ~93 ГБ свободно |
| Пользователь | `deployagent` (uid 1001), **без root/sudo** |
| Доступ агента | Временная пара ed25519 (комментарий `perplexity-computer-deployagent-temp`) в `~/.ssh/authorized_keys` |
| Требование | OpenCode + веб-интерфейс, доступ наружу, HTTPS |

Ключевое ограничение: нет root. Всё ставится в `$HOME`, сервисы — пользовательские systemd-юниты, TLS — Caddy с приватным CA (порты 80/443 без root не занять).

## 2. Итоговая архитектура

```
Интернет ──HTTPS:4601──> Caddy (tls internal, приватный CA)
                              │ reverse_proxy
                              v
                      127.0.0.1:4600  opencode serve (v2, API + Web UI)
                              │
                              v
                      ~/projects (рабочая папка проектов)
```

- **OpenCode v2.0.32** — `~/.opencode/bin/opencode`.
- **`opencode-web.service`** — пользовательский systemd-юнит: `opencode serve --hostname 127.0.0.1 --port 4600`.
- **`caddy.service`** — пользовательский юнит: Caddy v2.11.7 (`~/bin/caddy`), `https://0.0.0.0:4601` → `127.0.0.1:4600`.
- Пароль — `~/.config/opencode-web.env` (chmod 600), подключается через `EnvironmentFile`.
- Linger включён на этом сервере (`loginctl enable-linger deployagent` выполнился успешно); автозапуск сервисов включён. Перезагрузку сервера в рамках сессии не выполняли.

## 3. Пошаговое развёртывание

Команды ниже — фактически выполненные в этой сессии (см. журнал в §8). Помечено, что именно проверено.

### 3.1. Подготовка

```bash
mkdir -p ~/.config/systemd/user ~/.config/caddy ~/bin ~/projects
```

### 3.2. Установка OpenCode v2

```bash
curl -fsSL https://opencode.ai/v2/install | bash
~/.opencode/bin/opencode --version   # на момент установки: opencode v2.0.32
```

Примечания:
- Скрипт ставит актуальную на момент запуска версию; команда не «пришивает» v2.0.32.
- Если в `~/.opencode/bin` стоял бинарник v1 — он будет заменён. В сессии попытка `OPENCODE_INSTALL_DIR=$HOME/ocv2 curl ... | bash` не сработала: переменная через pipe применяется к `curl`, а не к инсталлятору (поддерживает ли установщик эту переменную — не устанавливалось).

### 3.3. Пароль

```bash
NEWPASS=$(openssl rand -base64 24 | tr -d '/+=\n')
printf 'OPENCODE_SERVER_PASSWORD=%s\n' "$NEWPASS" > ~/.config/opencode-web.env
chmod 600 ~/.config/opencode-web.env
```

Сервер v2 всегда требует пароль: с `OPENCODE_SERVER_PASSWORD` использует его, без — генерирует и печатает в лог. Basic auth: логин `opencode`, пароль из файла. В веб-интерфейсе тот же пароль вводится один раз («Connect to a server» → «Use password»), дальше хранится в localStorage браузера.

### 3.4. systemd-юнит OpenCode

`~/.config/systemd/user/opencode-web.service`:

```ini
[Unit]
Description=OpenCode v2 Web UI
After=network-online.target

[Service]
WorkingDirectory=%h/projects
ExecStart=%h/.opencode/bin/opencode serve --hostname 127.0.0.1 --port 4600 --print-logs
EnvironmentFile=%h/.config/opencode-web.env
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now opencode-web
loginctl enable-linger deployagent    # на этом VPS сработало; в общем случае может требовать прав
```

### 3.5. Caddy (HTTPS-прокси)

```bash
curl -fsSL "https://caddyserver.com/api/download?os=linux&arch=amd64" -o ~/bin/caddy
chmod +x ~/bin/caddy
```

`~/.config/caddy/Caddyfile` (протестированная рабочая конфигурация):

```
{
	auto_https disable_redirects
	default_sni 94.141.97.249
}

https://94.141.97.249:4601 {
	tls internal
	reverse_proxy 127.0.0.1:4600
}
```

`~/.config/systemd/user/caddy.service`:

```ini
[Unit]
Description=Caddy HTTPS proxy for OpenCode
After=network-online.target

[Service]
ExecStart=%h/bin/caddy run --config %h/.config/caddy/Caddyfile
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now caddy
```

## 4. Проверка (выполнено, с ожидаемыми результатами)

```bash
systemctl --user is-active opencode-web caddy    # active / active
ss -tln | grep -E '4600|4601'                    # 127.0.0.1:4600 и *:4601

# снаружи (без -k, через доверие к CA-сертификату):
curl --cacert root.crt -o /dev/null -w '%{http_code}\n' https://94.141.97.249:4601/api/project
#   -> 401 без пароля
curl --cacert root.crt -u opencode:<ПАРОЛЬ> https://94.141.97.249:4601/api/project
#   -> 200 + JSON со списком проектов

# стойкость к перезапуску сервисов (выполнено, прошло):
systemctl --user restart opencode-web caddy
```

Полный пользовательский сценарий в реальном браузере (проверен на проде в чистой сессии): предупреждение о сертификате → «Дополнительно» → «Перейти на сайт» → «Use password» → пароль → Add project (`~/projects`) → New session → открывается композер (поле Prompt, кнопка Send, проект «projects», модель по умолчанию с плашкой «Big Pickle»). Ни один AI-запрос при проверке не отправлялся — работоспособность самой модели не проверена.

Модель безопасности v2 (наблюдение): SPA-оболочка (статика) отдаётся без пароля (200), все `/api/*` — 401 без пароля, с паролем — данные.

## 5. Найденные грабли (переформулировано по фактическим наблюдениям)

1. **v1 (1.19.3) в этой установке**: страницы Settings и New session в веб-интерфейсе воспроизводимо падали (`Settings/Language context must be used within a context provider`). Очистка localStorage, смена рабочей папки, обход из issue #37546 (`settings.v3 → general.newLayoutDesigns=false`) — не помогли. В установленной v2.0.32 эти же сценарии прошли полностью. Универсальность бага v1 не доказывалась.
2. **Caddy, `auto_https off`** — TLS-handshake падал (tlsv1 alert internal error). Рабочая конфигурация — `auto_https disable_redirects` (+ `default_sni`), она проверена целиком; изолировать причину каждого отдельного симптома не проводилось.
3. **`default_sni <IP>`** — при доступе по голому IP браузеры не отправляют SNI; без этой опции рукопожатие TLS падало. С опцией — работает.
4. **Конфликт портов Caddy**: сайт `https://IP:4602` с upstream `127.0.0.1:4602` упал с `bind: address already in use` — wildcard-прослушка Caddy конфликтует с уже занятым конкретным адресом того же порта. Прокси-цель — другой номер порта.
5. **`pkill -f "opencode serve"` убил собственную SSH-сессию**, потому что паттерн совпал с текстом самой команды (heredoc). Обход: экранирование в паттерне, напр. `pkill -f "...46[1]0"`.
6. **Запуск opencode из `$HOME`** давал в логе `failed to initialize fff ... Consider smaller per-project directories` → в юните задан `WorkingDirectory=%h/projects`.
7. **Linger**: `loginctl enable-linger deployagent` на этом VPS сработал без root (rc=0). В общем случае может требовать административной политики.
8. **v2 при первом входе показывает «Connect to a server»** — штатный поток: SPA-клиент подключается к серверу паролем (тот же, что в `OPENCODE_SERVER_PASSWORD`).

## 6. Эксплуатация

Проверенное в сессии:

```bash
systemctl --user status opencode-web
systemctl --user restart opencode-web caddy
systemctl --user stop opencode-web
journalctl --user -u opencode-web --no-pager -n 50   # рабочие логи (юнит запущен с --print-logs)
journalctl --user -u caddy --no-pager -n 50
```

Рекомендации (в сессии не выполнялись):

```bash
# смена пароля: отредактировать ~/.config/opencode-web.env, затем
systemctl --user restart opencode-web

# обновление opencode:
~/.opencode/bin/opencode upgrade && systemctl --user restart opencode-web
```

- Лог v1 по пути `~/.local/share/opencode/log/opencode.log` — историческое свидетельство той сессии; для v2 рабочих логов смотреть `journalctl --user -u opencode-web`.
- Терминальный интерфейс: по SSH под `deployagent` запустить `opencode` (TUI). Замечание: TUI по умолчанию поднимает собственный фоновый сервис — отдельный экземпляр от веб-сервера.
- Модели/провайдеры подключаются в веб-интерфейсе: Settings → Providers. Плашка «Big Pickle» в композере наблюдалась, но работа модели не проверялась.

## 7. Сертификат и безопасность

- Серверный сертификат выпущен **приватным CA Caddy** («Caddy Local Authority - 2026 ECC Root», корневой CA валиден до 2036), лист — 12 часов, обновляется автоматически. Это не публично доверенный CA: незнакомый браузер покажет предупреждение (ERR_CERT_AUTHORITY_INVALID).
- Корневой сертификат CA: `~/.local/share/caddy/pki/authorities/local/root.crt` на сервере (копия передана владельцу). SHA-256 отпечаток: `66:DE:78:EF:D2:AE:0A:03:9E:40:C8:B8:DE:65:4C:78:83:D0:2B:72:04:0E:69:EE:0E:C3:9F:B8:CD:E1:22:2F`. Проверка `curl --cacert root.crt` (401/200) выполнялась — доверие работает.
- Импорт этого CA в системное доверенное хранилище — отдельное решение владельца: CA контролируется этим сервером. Публично доверенный сертификат (Let's Encrypt и т.п.) на такой схеме не проверялся; требуемые для него условия в сессии не устанавливались.
- Внешняя поверхность: `22/tcp` (SSH) и `4601/tcp` (HTTPS). OpenCode слушает только localhost; наружу — только Caddy.
- Отзыв доступа агента: удалить в `/home/deployagent/.ssh/authorized_keys` строку с комментарием `perplexity-computer-deployagent-temp`.
- Пароль веб-интерфейса передавался через чат — владельцу рекомендуется сменить его после отзыва доступа агента.

## 8. Хронологический журнал действий

1. **Разведка**: SSH-подключение под `deployagent@94.141.97.249`. Результат: Ubuntu 26.04, 2 vCPU/3.3 ГБ, `curl` есть, `sudo -n true` — отказ, из слушающих портов только 22, Python 3.14, Node отсутствует.
2. **Установка opencode v1**: `curl -fsSL https://opencode.ai/install | bash` → 1.19.3 в `~/.opencode/bin`. `opencode web --help` → есть `--hostname/--port`.
3. **Документация** ([opencode.ai/docs/web](https://opencode.ai/docs/web)): веб-UI поддерживает basic-auth через `OPENCODE_SERVER_PASSWORD`, логин по умолчанию `opencode`.
4. **Первый вариант**: сервис `opencode-web` (v1) на `0.0.0.0:4600` с basic auth. Проверка снаружи: 401 без пароля / 200 с паролем.
5. **Ротация и закрытие**: пароль сменили (первый ходил по чистому HTTP), opencode переведён на `127.0.0.1:4600`, пароль вынесен в `EnvironmentFile` (chmod 600). Установлен Caddy v2.11.7 (`caddyserver.com/api/download`).
6. **Итерации Caddyfile** (см. грабли №2–4): базовый конфиг → падение `listening on :80: bind: permission denied`; `auto_https off` → `tlsv1 alert internal error`; `auto_https disable_redirects` → TLS-ошибка при подключении без SNI; `+ default_sni 94.141.97.249` → локально и снаружи 200.
7. **Верификация CA**: root-сертификат скачан, fingerprint снят, `curl --cacert` → 401/200.
8. **Браузерная проверка v1**: главная и диалог выбора папок работают (реальные папки сервера); Settings → краш `Settings context must be used within a context provider`; New session → переход на `/new-session?draftId=...` и краш; повторно `Language context must be used within a context provider`. Очистка localStorage/sessionStorage — без эффекта; обход из [issue #37546](https://github.com/anomalyco/opencode/issues/37546) (`settings.v3 → newLayoutDesigns=false`) — без эффекта. Все сетевые запросы при этом возвращали 200 (ошибок загрузки нет). В логе v1 — `failed to initialize fff ... home directories` (запуск из `$HOME`) → добавлен `WorkingDirectory=%h/projects`.
9. **Поиск в трекере**: похожие симптомы в [issue #30478](https://github.com/anomalyco/opencode/issues/30478) (v1.15.13, помогала чистка браузера — здесь нет), [#35701](https://github.com/anomalyco/opencode/issues/35701), [#37546](https://github.com/anomalyco/opencode/issues/37546). Универсальную причину не установили.
10. **Установка v2 для сравнения**: `curl -fsSL https://opencode.ai/v2/install | bash` — скрипт заменил бинарник v1 на v2.0.32 в `~/.opencode/bin` (попытка отдельного каталога через `OPENCODE_INSTALL_DIR` через pipe не сработала — переменная применилась к `curl`, не к инсталлятору).
11. **Тест v2**: `opencode serve` на `127.0.0.1:4602`. Первый вариант Caddy-сайта `https://IP:4602 → 127.0.0.1:4602` упал (`bind: address already in use`). Тест перенесён: v2 на `4610`, Caddy-сайт `4602`. Попутно `pkill -f "opencode serve"` оборвал собственную SSH-сессию (паттерн совпал с текстом heredoc) — конфиги пришлось переписывать.
12. **Браузерный тест v2**: «Connect to a server» → «Use password» → пароль → главная; Settings — полный интерфейс (Preferences/Appearance/…/Server/About) без ошибок; Add project (`~/projects`, «Select folder»); New session → композер (Prompt, Send, «Big Pickle», «Connect to 75+ providers»). AI-запросы не отправлялись.
13. **Перевод прода на v2**: `ExecStart` сменён на `opencode serve ... --print-logs`, Caddyfile очищен до единственного сайта `:4601`, тестовые процессы/сайты удалены. Проверка: v2.0.32, 200 через Caddy.
14. **Финальная верификация**: API — `/api/project` без пароля 401, с паролем 200+JSON, с неверным паролем 401; SPA-оболочка 200 без пароля (наблюдаемое штатное поведение v2). Полный пользовательский сценарий в чистой браузерной сессии на проде: cert warning → Proceed → «Use password» → Connect → Add project → New session → композер без ошибок. `Linger=yes`, оба сервиса enabled+active, перезапуск сервисов пережили.

## 9. Источники

- Исходная сессия: https://www.perplexity.ai/computer/tasks/2bb35640-eef9-4972-8630-9d5e722ce836
- Установка v1: https://opencode.ai/docs/ ; v2: https://opencode.ai/v2/docs
- Basic-auth веб-UI v1: https://opencode.ai/docs/web
- Безопасность сервера v2 (всегда пароль): https://github.com/anomalyco/opencode/issues/45913
- Похожие симптомы краха контекстов (контекст, не доказательство причины): https://github.com/anomalyco/opencode/issues/30478 , https://github.com/anomalyco/opencode/issues/35701 , https://github.com/anomalyco/opencode/issues/37546
- Caddy `tls internal`: https://caddyserver.com/docs/caddyfile/directives/tls
