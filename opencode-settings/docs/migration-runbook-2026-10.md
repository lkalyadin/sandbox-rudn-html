# Переезд основного стенда `:4601` на новый VPS — runbook

Дата подготовки: 2026-10-28. Статус: **подготовлено, не выполнялось** (переезд — отдельная операция).
Область: основной стенд разработки (OpenCode 2.0.32 + Caddy, `https://<IP>:4601`), четыре проекта
и рабочие файлы. Студенческий стенд по новому правилу живёт **только на отдельной одноразовой VPS**
и на новом основном хосте не разворачивается (§10).

Целевой хост заранее: записать сюда новый IP и дату, чтобы команды ниже были однозначными.

```
НОВЫЙ_IP = ......................   (публичный IPv4 нового VPS)
НОВЫЙ_ХОСТ = .....................  (hostname)
ДАТА_ПЕРЕЕЗДА = ..................
```

---

## 0. Как этим пользоваться

1. Прочитать §2–§3 (что и куда переезжает, целевая картина) — там же решения, которые надо принять до работы.
2. На старом хосте: `bash scripts/export-main-stand.sh --dry-run`, затем без флага (§11, приложение A).
3. Поднять новый хост по §4–§7, разложить проекты по §8.
4. Прогнать §9 (проверки), только потом объявлять адрес пользователям.
5. Студенческий стенд — отдельно и независимо, §10.
6. Старый хост не выключать, пока не пройден §12 (откат/вывод из эксплуатации).

Все команды ниже — для пустого Ubuntu с root-доступом по SSH. Пользователь `deployagent` с
**uid/gid 1001** обязателен: в архиве права и владельцы файлов — 1001, в юнитах и скриптах
зашит `%h` = `/home/deployagent`, а сертификаты/файлы в старом стенде отдавались под uid 1001.

Что проверено на старом хосте при подготовке этого runbook:

* выпуск IP-сертификата самим Caddy (профиль `shortlived`) — прогнан против staging LE, сертификат
  получен (§7);
* `scripts/export-main-stand.sh` — реальный прогон: архив 19 МБ, `quick_check ok`, 2 креда и 59
  сессий в бэкапе БД, права 600 на секретах;
* `certbot 5.8` + `oc-cert-renew.sh` — схема, которая работает на старом хосте; на новый не переносится (§7).

Что **не** проверялось (делается уже на новом хосте): установка OpenCode с нуля, подъём Caddy
на новом IP в продовом LE, ребут нового хоста.

---

## 0.1. Секреты: в git не попадают, при развёртывании — спросить

В документации и репозитории секретов нет: реальные значения заменены плейсхолдерами
`<SANDBOX_PASSWORD>`, `<AI_GATEWAY_API_KEY>`. При развёртывании значения **спрашивают у владельца**
и кладут в файл с правами 600 — в git, чат и логи они не попадают.

| Секрет | Где нужен | Как получить |
|---|---|---|
| `OPENCODE_SERVER_PASSWORD` | basic-auth на `:4601` | спросить владельца (или задать новый) → `~/.config/opencode-web.env`, 600 |
| ключи провайдеров OpenCode (`vercel`, `opencode-go`) | таблица `credential` в `opencode.db` | переносятся архивом; либо заново: `opencode auth login` (ключи — у владельца) |
| `SANDBOX_PASSWORD` | логин `opencode` на студенческом стенде + `edge/htpasswd` | спросить владельца (плейсхолдер `<SANDBOX_PASSWORD>`) |
| `AI_GATEWAY_API_KEY` | контейнер `gateway` студенческого стенда (Vercel AI Gateway, платный) | спросить владельца или выпустить новый ключ в Vercel (плейсхолдер `<AI_GATEWAY_API_KEY>`) |
| `OPENCODE_GO_API_KEY` | подписка OpenCode Go (`.env` стенда; на основном хосте — кред в БД) | спросить владельца |
| SSH-ключи git (`id_ed25519_*`) | клонирование `gameconnect`, `adventuremazes` | только архив (`~/.ssh`, 600), не git |

Правила:

* в репозиторий — только плейсхолдеры `<...>`; перед публикацией проверять утечки сравнением с
  `.env` (значения не печатать), а не «на глаз»;
* при переносе ключ шлюза и пароль стенда **ротировать**: они лежали в документации на старом хосте;
* на новом хосте секреты создаются заново: `install -m 600` / `umask 077`, в юните — `EnvironmentFile`.

---

## 1. Что переезжает и что нет

| Переезжает | Откуда | Как |
|---|---|---|
| OpenCode 2.0.32 | `~/.opencode/bin/opencode` | переустановить installer'ом (не копировать бинарь) |
| Конфиг OpenCode | `~/.config/opencode/{opencode.jsonc,package.json,package-lock.json,service.json}` | архив |
| Пароль/окружение сервиса | `~/.config/opencode-web.env` (600) | архив (секрет) |
| База (креды провайдеров, проекты, сессии) | `~/.local/share/opencode/opencode.db` | архив, бэкап через sqlite3 API |
| Caddy 2.11.7 | `~/bin/caddy` | переустановить с GitHub (бинарь в архив не кладём) |
| Конфиг Caddy | `~/.config/caddy/{Caddyfile,Caddyfile.known-good,Caddyfile.fallback-internal}` | архив, но IP внутри правится |
| Юниты | `~/.config/systemd/user/{opencode-web,caddy}.service` | архив |
| Скрипт восстановления | `~/bin/oc-fix.sh` | архив |
| Статика `/normal-forms/` | `~/web/normal-forms` (симлинк) + цель в `~/projects` | архив |
| Ключи и git-алиасы | `~/.ssh/{config,known_hosts,id_ed25519_*}`, `~/.gitconfig` | архив (секрет) |
| Проекты | `~/projects/{gameconnect,adventuremazes}` | **git clone** из GitHub (не tar) |
| Проекты | `~/projects/{students,opencode-settings,datasets,demo}` + `AGENTS.md` + 20 файлов в корне | архив |
| Исходники студенческого стенда | `/srv/opencode-student/sandbox` (docker/, config/, skills/, scripts/, edge/*.conf, compose) | архив → `students/sandbox-source` |
| Плановые задачи | нет: сертификат продлевает сам Caddy (§7) | — |

| НЕ переезжает | Почему |
|---|---|
| `/srv/opencode-student/{bundles,workspace.img,monitoring,edge/certs}` (≈1.8 ГБ) | состояние/артефакты старого студенческого стенда; новый стенд собирается на одноразовой VPS (§10) |
| `~/.local/share/caddy` (сертификаты, ACME-аккаунт) | новый IP → новый сертификат; выпускается заново (§7) |
| `~/.local/share/oc-cert` и `~/bin/oc-cert-renew.sh` | остаются на старом хосте (ACME-состояние старого IP, certbot-схема) |
| `~/.local/venvs/certbot` | нужен только текущей схеме старого хоста; на новом хосте сертификатом занимается Caddy |
| `~/.cache` (1.7 ГБ: playwright/uv/puppeteer), `~/.npm` (360 МБ), `~/sandbox` (619 МБ) | пересобирается само |
| `~/projects/*/node_modules` (222 МБ у gameconnect) | `npm ci` на дев-машине, сервер собирать не должен |
| Логи, `~/.local/share/opencode/{log,snapshot,shell,tool-output}` | не нужны |
| История сессий | явно не нужна; но она лежит в той же БД, что и креды — БД переносим целиком (можно почистить потом) |
| docker, gVisor (`runsc`) | на новом основном хосте не нужны вовсе |

---

## 2. Как стенд поднимался (история, чтобы не потерять контекст)

`~/.bash_history` практически пуст (11 строк: правка env, рестарт сервиса, `id/nproc/free/df`),
поэтому хронология восстановлена по mtime файлов, `/var/log/apt/history.log`, `journalctl` и
документации в проектах. Фактическая последовательность:

| Когда (UTC) | Что сделано |
|---|---|
| 2026-10-18 19:42 | создан пользователь `deployagent` (uid 1001), включён linger; Ubuntu 26.04, 1 vCPU / 1641 МБ / 98 ГБ, swap-файл 4 ГБ |
| 2026-10-18 20:02–20:04 | `~/bin/caddy` **2.11.7**; `opencode` **2.0.32** официальным installer'ом в `~/.opencode/bin` (+ PATH в `~/.bashrc`) |
| 2026-10-18 20:03 / 20:14 | юниты `caddy.service` и `opencode-web.service` (user-scope, `Restart=on-failure`), `default.target.wants` |
| 2026-10-19 05:15 | `/etc/sysctl.d/99-unprivileged-ports.conf` → `net.ipv4.ip_unprivileged_port_start=80` (Caddy на :4601 и ACME на :80 без root) |
| 2026-10-19 19:10–19:13 | `apt install docker.io docker-compose-v2`, репозиторий gVisor, `runsc 20261012` |
| 2026-10-19…20 | студенческий стенд в `/srv/opencode-student` (edge nginx, песочница gVisor, egress, workspace loop-ext4), таймеры 03:30/03:40/04:17/вс 05:20, certbot в контейнере |
| 2026-10-24 | docker остановлен и **замаскирован** (`/etc/systemd/system/{docker.service,docker.socket,containerd} → /dev/null`), собран бандл стенда |
| 2026-10-27 | обновлены студенческий стенд и датасеты, собран второй бандл (`stand-20261027-1924.tar.gz`) |
| 2026-10-28 | сертификат: продление через docker не работало → свой certbot 5.8 в venv, `oc-cert-renew.timer`, `ExecReload` у Caddy; чистка проектов в БД (`scripts/archive-projects.py`) |

Выводы для переезда: основной стенд — это фактически **два бинаря + два юнита + конфиг + БД**;
вся тяжесть (docker/gVisor/edge/сертификаты студенческого стенда) к `:4601` отношения не имеет
и на новом хосте не нужна.

---

## 3. Целевая картина

```
Пользователь → https://НОВЫЙ_IP:4601 (Caddy, TLS) → 127.0.0.1:4600 (opencode serve)
                                    │
                                    └─ /normal-forms/ (статика)

Студенческие стенды: отдельные одноразовые VPS (docker + gVisor + edge), к основному хосту
не относятся; их исходники и процедура — проект students/ (§10).
```

Что упрощается на новом хосте (следствие разделения):

* **нет `/srv/opencode-student`** → не нужен общий каталог сертификатов и не нужен fstab-loop;
* **нет docker/gVisor** → меньше поверхности, нет падающих таймеров студенческого стенда;
* **TLS отдаём Caddy** (§7): на старом хосте это было невозможно, потому что
  порты 80/443 держал edge студенческого стенда. На чистом хосте Caddy сам выпускает и продлевает
  сертификат на IP — без certbot, таймеров и общих файлов;
* остальное сохраняем 1:1: тот же пользователь/uid, те же пути, тот же порт 4601, тот же basic-auth.

---

## 4. Требования к новому серверу

| Параметр | Значение | Комментарий |
|---|---|---|
| ОС | Ubuntu 24.04/26.04 LTS, x86-64 | проверено на 26.04 |
| CPU | 2 vCPU (минимум 1) | 1 vCPU работал, но любой прогон (сборка, headless-браузер) тормозит UI |
| RAM | 2–4 ГБ | сейчас занято ~600 МБ, `available` ~1 ГБ; 2 ГБ — комфортно |
| Диск | 20–40 ГБ | занято 22 ГБ, из них 1.7 ГБ кэши (не переносим) |
| Публичный IPv4 | обязателен, без NAT | ACME проверяет `http://IP` и `https://IP` снаружи |
| Порты | 22 (ssh), 4601 (стенд), 80 и/или 443 (ACME) | 443 нужен для TLS-ALPN, 80 — для HTTP-01 |
| Домен | не нужен | сертификат Let's Encrypt на IP (профиль shortlived, ~6.7 суток) |
| swap | 2 ГБ, если RAM ≤ 2 ГБ | `vm.swappiness=10` (на старом хосте не был закреплён — закрепить) |
| Docker | **не нужен** | студенческий стенд — на отдельной VPS |

Проверка после создания VPS:

```bash
curl -4 -s ifconfig.me; echo        # должно совпасть с НОВЫЙ_IP
getconf LONG_BIT                     # 64
nproc; free -m | head -2; df -h /
```

---

## 5. Шаг 1 — подготовка хоста (root)

```bash
# 1) пользователь с uid/gid 1001 (как на старом хосте — иначе права на файлы из архива разъедутся)
useradd -u 1001 -U -m -s /bin/bash deployagent
chmod 750 /home/deployagent
# ключ для входа (тот же, что сейчас в ~/.ssh/authorized_keys старого хоста)
install -d -m 700 -o deployagent -g deployagent /home/deployagent/.ssh
echo '<ПУБЛИЧНЫЙ КЛЮЧ>' > /home/deployagent/.ssh/authorized_keys
chown deployagent:deployagent /home/deployagent/.ssh/authorized_keys
chmod 600 /home/deployagent/.ssh/authorized_keys

# 2) linger: без него user-сервисы умирают с SSH-сессией и не встают после ребута
loginctl enable-linger deployagent

# 3) порт 80 без root (Caddy на :4601 + ACME на :80/443)
printf 'net.ipv4.ip_unprivileged_port_start=80\n' > /etc/sysctl.d/99-unprivileged-ports.conf
sysctl --system

# 4) swap (если RAM ≤ 2 ГБ)
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
printf '/swapfile none swap sw 0 0\n' >> /etc/fstab
printf 'vm.swappiness=10\n' > /etc/sysctl.d/99-swappiness.conf && sysctl --system

# 5) минимум пакетов (docker/gVisor НЕ ставим)
apt-get update
apt-get install -y curl ca-certificates openssl git python3 unzip jq

# 6) firewall (если провайдер даёт ufw)
ufw allow 22/tcp && ufw allow 4601/tcp && ufw allow 80/tcp && ufw allow 443/tcp
```

Гигиена доступа (по желанию, но лучше сразу): `PasswordAuthentication no`, вход только по ключу.
На старом хосте пароль по SSH был разрешён (`PasswordAuthentication` не задан → default yes) —
на новом лучше закрыть.

Проверка: `id deployagent` → `uid=1001`, `loginctl show-user deployagent | grep Linger` → `yes`,
`sysctl net.ipv4.ip_unprivileged_port_start` → `80`.

---

## 6. Шаг 2 — OpenCode

```bash
sudo -iu deployagent            # дальше всё от deployagent

# 1) установка (installer для OpenCode 1 отказывается ставить 2.x — нужен /v2/install)
curl -fsSL https://opencode.ai/v2/install | bash -s -- --version 2.0.32
~/.opencode/bin/opencode --version     # opencode v2.0.32
grep -q '.opencode/bin' ~/.bashrc || echo 'export PATH=/home/deployagent/.opencode/bin:$PATH' >> ~/.bashrc

# 2) рабочий каталог сервера (WorkingDirectory юнита) и TMPDIR
mkdir -p ~/projects ~/tmp ~/web

# 3) конфиги из архива (см. §11): ~/.config/opencode/*, ~/.config/opencode-web.env (600)
#    ~/.config/opencode/opencode.jsonc — сейчас содержит только {"$schema": ...}
#    ~/.config/opencode/package.json — @opencode-ai/plugin 1.19.3 (не используется: плагинов нет)
#    node_modules НЕ переносим; при необходимости: opencode plugin add <pkg>

# 4) БД: креды провайдеров (2 шт.) и проекты лежат в SQLite
install -d -m 700 ~/.local/share/opencode
install -m 600 /path/to/db/opencode.db ~/.local/share/opencode/opencode.db

# 5) юнит из архива, затем:
systemctl --user daemon-reload
systemctl --user enable --now opencode-web
journalctl --user -u opencode-web -n 30 --no-pager
```

Проверка без Caddy (локально):

```bash
PW=$(grep -oP '^OPENCODE_SERVER_PASSWORD=\K.*' ~/.config/opencode-web.env)
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:4600/api/model            # 401
curl -s -u opencode:"$PW" -o /dev/null -w '%{http_code}\n' http://127.0.0.1:4600/api/model  # 200
curl -s -u opencode:"$PW" http://127.0.0.1:4600/api/model | python3 -c \
  "import sys,json,collections;d=json.load(sys.stdin)['data'];print(len(d),dict(collections.Counter(m['providerID'] for m in d)))"
# ожидаем ~353 модели: vercel 315, opencode-go 30, opencode 8 (число плавает — это каталог провайдеров)
```

Альтернатива переносу БД (если хочется чистую историю): новую БД OpenCode создаст сам, а креды
добавить `opencode auth login` (понадобятся ключи Vercel AI Gateway и OpenCode Go) — тогда переносить
`opencode.db` не нужно. Минус: настраивать заново `project`/настройки.

> **Важно про версию.** БД мигрируется по схеме при старте; чтобы не ловить сюрпризов, ставим ту же
> 2.0.32, поднимаем стенд, убеждаемся что всё работает, и только потом обновляем (`opencode upgrade`).
> Перед обновлением — бэкап БД (см. `scripts/archive-projects.py`, там же готовый backup-код).

---

## 7. Шаг 3 — TLS: сертификатом управляет Caddy

Решение (29.10.2026): **никакого certbot на новом хосте**. Certbot-схема существовала только
потому, что порты 80/443 держал edge студенческого стенда. Теперь edge на этом хосте нет, порты
свободны, и Caddy 2.11.7 выпускает сертификат на **IP-идентификатор** сам — с профилем
`shortlived`, который для IP обязателен.

Проверено 28.10.2026 на этом же Caddy против **staging** LE: заказ создаётся, challenge проходит по
`tls-alpn-01` на :443, сертификат выпускается (`certificate obtained successfully`). Без профиля LE
отвечает `rejectedIdentifier: Default profile does not permit IP address identifiers` — профиль
обязателен.

Что это даёт: нет certbot, нет venv с pip, нет таймера продления, нет общих файлов с edge и нет
класса ошибок «файл сертификата обновился, а Caddy его не перечитал». Продление — автоматически
(certmagic: ARI, иначе ~2/3 срока жизни), состояние в `~/.local/share/caddy`.

```caddyfile
{
	email leonid.kalyadin@gmail.com
	auto_https disable_redirects
}

https://НОВЫЙ_IP:4601 {
	tls {
		issuer acme {
			profile shortlived
		}
	}

	redir /normal-forms /normal-forms/ 308
	handle_path /normal-forms/* {
		root * /home/deployagent/web/normal-forms
		file_server
	}

	reverse_proxy 127.0.0.1:4600
}
```

Если 443 закрыт фаерволом — переключить проверку на HTTP-01 (порт 80):

```caddyfile
	tls {
		issuer acme {
			profile shortlived
			disable_tlsalpn_challenge
		}
	}
```

На новом хосте **не ставим**: `oc-cert-renew.sh`, `oc-cert-renew.timer`, certbot/venv,
`~/.local/share/oc-cert`. На старом хосте они продолжают работать до его вывода — это страховка на
время переезда, и в архив переезда они больше не попадают (§11).

`oc-fix.sh` под эту схему подходит без правок: его `--reissue` сбрасывает
`~/.local/share/caddy/certificates` и перезапускает Caddy — Caddy выпускает сертификат заново.

---

## 8. Шаг 4 — Caddy и юнит

```bash
# бинарь: та же версия, что на старом хосте
cd ~/tmp
curl -fsSLO https://github.com/caddyserver/caddy/releases/download/v2.11.7/caddy_2.11.7_linux_amd64.tar.gz
tar xzf caddy_2.11.7_linux_amd64.tar.gz caddy && install -m 755 caddy ~/bin/caddy
~/bin/caddy version                 # v2.11.7

# конфиг: ~/.config/caddy/Caddyfile (из §7), IP внутри — новый
mkdir -p ~/.config/caddy
~/bin/caddy validate --config ~/.config/caddy/Caddyfile

# юнит из архива (в нём ExecReload — graceful reload без разрыва соединений)
systemctl --user daemon-reload
systemctl --user enable --now caddy
journalctl --user -u caddy -n 40 --no-pager     # ждём «certificate obtained successfully»
```

Проверка снаружи:

```bash
curl -sk -o /dev/null -w '%{http_code}\n' https://НОВЫЙ_IP:4601/            # 200
curl -sk -o /dev/null -w '%{http_code}\n' https://НОВЫЙ_IP:4601/api/model   # 401
echo | openssl s_client -connect НОВЫЙ_IP:4601 -servername НОВЫЙ_IP 2>/dev/null \
  | openssl x509 -noout -issuer -dates -ext subjectAltName
```

---

## 9. Шаг 5 — проекты и рабочие файлы

Источники: архив (§11) + git для двух репозиториев. Целевые пути — **те же**, что на старом хосте
(`/home/deployagent/projects/...`): от этого зависят записи в БД (`project`) и `KEEP` в
`scripts/archive-projects.py`.

```bash
# 1) из архива: projects/{students,opencode-settings,datasets,demo}, AGENTS.md, 20 файлов в корне,
#    ~/web/normal-forms (симлинк на ~/projects/db_normal_forms_quiz.html)
tar -xzf main-stand-<дата>.tar.gz -C / home/deployagent/projects home/deployagent/web
chown -R deployagent:deployagent /home/deployagent/projects /home/deployagent/web

# 2) git-проекты — клонировать, а не копировать (node_modules всё равно пересобираются)
cd ~/projects
git clone git@github-gameconnect:lkalyadin/game-connect.git gameconnect
git clone git@github-adventuremazes:lkalyadin/adventure-mazes-google.git adventuremazes
cd adventuremazes && git checkout feat/vlak-expeditions     # рабочая ветка на старом хосте
cd ../gameconnect && git checkout feat/cloud-save
```

SSH-алиасы (`github-gameconnect`, `github-adventuremazes`) приходят из `~/.ssh/config` в архиве
вместе с ключами. Проверка: `ssh -T git@github-gameconnect`.

Состояние на момент переезда (сверять, если делаете это позже):

| Проект | Размер | Ветка | Незакоммиченное |
|---|---|---|---|
| `gameconnect` | 249 МБ (node_modules 222 МБ) | `feat/cloud-save` | нет |
| `adventuremazes` | 242 МБ (.git 210 МБ) | `feat/vlak-expeditions` | `.opencode/` (untracked) |
| `students` | 544 КБ, **не git** | — | — |
| `opencode-settings` | ≈70 КБ, **не git** | — | — |
| `datasets` | 2.2 МБ, 26 файлов | — | — |
| корень `~/projects` | `AGENTS.md` + 20 файлов (HTML/MD/DOCX) | — | — |

Важные частности:

* `~/web/normal-forms/index.html` — **симлинк** на `~/projects/db_normal_forms_quiz.html`; при
  распаковке порядок не важен, но цель должна существовать (она в архиве).
* `students/` и `opencode-settings/` — не репозитории, это единственная копия документации и
  скриптов. После переезда их стоит завести в git (особенно `students` — см. §10).
* `adventuremazes` и `gameconnect` собираются **на дев-машине** (на хосте нет node/JDK): на сервере
  достаточно исходников.
* Каталоги `~/.cache`, `~/.npm`, `~/sandbox`, `~/tmp/shots` не переносим.

Проверка ссылок на старый IP (после копирования, до объявления адреса):

```bash
grep -RIl --exclude-dir=node_modules --exclude-dir=.git '94\.141\.97\.249' ~/projects ~/.config ~/bin 2>/dev/null
```

Ожидаемые попадания: `Caddyfile` (уже новый), `oc-fix.sh` (`IP=`),
`projects/students/*` (`PUBLIC_URL` для студенческих стендов), `projects/demo/*`, `AGENTS.md`/`docs`
(текст). Правится вручную; в студенческих доках адрес основного стенда нужен только как ссылка.

---

## 10. Шаг 6 — студенческий стенд: отдельная одноразовая VPS

Правило: на новом основном хосте **нет** `/srv/opencode-student`, docker, gVisor, edge и
сертификатов студенческого стенда. Стенд поднимается на чистом VPS и живёт там, пока нужен.

### 10.1 Что является исходниками (сохранить до выключения старого хоста)

Исходники стенда лежат **не в git**, а прямо в `/srv/opencode-student/sandbox`: `docker/Dockerfile`,
`docker-compose.yml`, `config/opencode.json`, `skills/`, `workspace.template/`, `edge/*.conf`,
`egress/`, `gateway/`, `upload-handler/`, `scripts/*.sh`, `catalog/`, `tools/`. Они уже попали в
архив переезда как `~/projects/students/sandbox-source` (§11), а `.env` — в `secrets/student-sandbox.env`.

Дальше: положить `sandbox-source` в git внутри `students/` (или отдельным репозиторием) и обновить
документацию так, чтобы «источник правды» был в репозитории, а не в `/srv` на хосте. Бандлы
(`stand-*.tar.gz`, 2×800 МБ) переносить не нужно — они пересобираются из исходников.

### 10.2 Требования к VPS стенда

Ubuntu 24.04/26.04, 2 vCPU / 3.4 ГБ минимум (эталон 4/7.2), диск от 50 ГБ, публичный IPv4,
открыты 22/80/443. Docker + gVisor ставятся под root. `DEPLOY_STAND.md` проекта `students` —
основная инструкция, ниже — только последовательность.

### 10.3 Два пути

**A. Из бандла (2–3 минуты, если бандл уже собран):**

```bash
# root на новом VPS
useradd -m -s /bin/bash deployagent && <ключ в authorized_keys>
apt-get update && apt-get install -y docker.io docker-compose-v2 openssl ca-certificates curl gpg
usermod -aG docker deployagent
# gVisor
curl -fsSL https://gvisor.dev/archive.key | gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main' > /etc/apt/sources.list.d/gvisor.list
apt-get update && apt-get install -y runsc && runsc install && systemctl restart docker
mkdir -p /srv/opencode && chown deployagent:deployagent /srv/opencode

# deployagent: распаковать бандл (НЕ в /tmp — tmpfs) и развернуть
tar xzf stand-<метка>.tar.gz && sha256sum -c stand-<метка>.tar.gz.sha256
cd stand-<метка> && bash 98-deploy-from-bundle.sh <IP_СТЕНДА>
# root: квота 30 ГБ + ночная очистка + linger
bash /srv/opencode/sandbox/scripts/95-root-setup.sh
```

**B. Сборка на месте (10–15 минут, без бандла):**

```bash
# deployagent: скелет из students/sandbox-source → /srv/opencode/sandbox
#   поправить пути (/srv/opencode-student → /srv/opencode), .env (PUBLIC_URL, uid 1000, CPU/RAM),
#   проверить, что путей дев-хоста не осталось
cd /srv/opencode/sandbox
bash scripts/00-preflight.sh
bash scripts/20-sync-workspace.sh /home/deployagent/datasets
bash scripts/30-up.sh              # htpasswd + сертификат + docker compose build (~6–10 мин, образ 2.4 ГБ) + up
bash scripts/70-build-catalog.sh
bash scripts/96-install-user-timers.sh
# root:
bash scripts/95-root-setup.sh
```

### 10.4 Что обязательно поменять

* `PUBLIC_URL=https://<IP_СТЕНДА>`, `ENABLE_TLS=true`;
* `SANDBOX_UID=SANDBOX_GID=1000` (uid внутри образа, **не** uid deployagent);
* `SANDBOX_CPUS`/`SANDBOX_MEMORY` — из `nproc` и ~60 % RAM (иначе старт падает на лимитах);
* пути `98-deploy-from-bundle.sh` (`/srv/opencode-student/workspace` → `/srv/opencode/workspace`,
  `~/projects/datasets` → `~/datasets`);
* `SANDBOX_PASSWORD` — оставить прежним (студенты помнят один пароль), ключ шлюза — актуальный;
  оба значения **спросить у владельца** (в репозитории плейсхолдеры, см. §0.1);
* на стенде свой TLS: certbot в контейнере + `opencode-student-cert.timer` (04:17) + edge; на
  основном хосте к этому отношения нет.

### 10.5 Приёмка стенда

```bash
cd /srv/opencode/sandbox
bash scripts/31-up-fast.sh --check     # контейнеры, ключ шлюза, модели, внешняя доступность
bash scripts/50-verify-isolation.sh    # 13/13 (gVisor, egress, uid, rootfs, лимиты)
bash scripts/55-verify-stand.sh        # контейнеры running, HTTPS 200, сессий 0
bash scripts/56-monitor.sh             # exit 0
bash scripts/40-info.sh --show         # выдать студентам адрес/логин/пароль
openssl x509 -enddate -noout -in edge/certs/fullchain.pem
```

Однострочник «здоров»: `31-up-fast --check` зелёный + `50` = 13/13 + `56` = 0 + сертификат в будущем.

---

## 11. Экспорт со старого хоста (что и как забирать)

Скрипт: `scripts/export-main-stand.sh` (ничего не меняет, только читает).

```bash
cd ~/projects/opencode-settings
bash scripts/export-main-stand.sh --dry-run     # план: пути и размеры
bash scripts/export-main-stand.sh               # → ~/tmp/migration/main-stand-<дата>.tar.gz (≈19 МБ) + .sha256
```

Внутри (макет повторяет целевые пути, распаковка — от `/`):

```
home/deployagent/.config/opencode/{opencode.jsonc,package.json,package-lock.json,service.json}
home/deployagent/.config/opencode-web.env                600
home/deployagent/.config/caddy/{Caddyfile,Caddyfile.known-good,Caddyfile.fallback-internal,backups}
home/deployagent/.config/systemd/user/{opencode-web,caddy}.service
home/deployagent/bin/oc-fix.sh
home/deployagent/web/normal-forms                        симлинк
home/deployagent/.ssh/{config,known_hosts,id_ed25519_*}  600
home/deployagent/{.gitconfig,.bashrc,.profile,.zshrc}
home/deployagent/projects/{students,opencode-settings,datasets,demo,AGENTS.md,*.html,*.md,*.docx}
home/deployagent/projects/students/sandbox-source        исходники студенческого стенда
db/opencode.db                                           бэкап (sqlite3 API), 600
secrets/student-sandbox.env                              600
MANIFEST.txt, sysinfo.txt                                версии, состав, снимок окружения
```

Передача: `scp`/`rsync` по SSH (архив — секрет: внутри ключи и БД с кредами; права 600). Проверка
целостности на новом хосте: `sha256sum -c main-stand-<дата>.tar.gz.sha256`.

---

## 12. Проверки после переезда

```bash
# юниты и порты
systemctl --user is-active opencode-web caddy        # active active
ss -ltnp | grep -E '4600|4601'                       # 4600 только 127.0.0.1, 4601 наружу
journalctl --user -u opencode-web -u caddy -n 50 --no-pager

# доступ
curl -sk -o /dev/null -w '%{http_code}\n' https://НОВЫЙ_IP:4601/                 # 200
curl -sk -o /dev/null -w '%{http_code}\n' https://НОВЫЙ_IP:4601/api/model        # 401
PW=$(grep -oP '^OPENCODE_SERVER_PASSWORD=\K.*' ~/.config/opencode-web.env)
curl -sk -u opencode:"$PW" -o /dev/null -w '%{http_code}\n' https://НОВЫЙ_IP:4601/api/model  # 200
curl -sk -o /dev/null -w '%{http_code}\n' https://НОВЫЙ_IP:4601/normal-forms/    # 200

# сертификат
echo | openssl s_client -connect НОВЫЙ_IP:4601 -servername НОВЫЙ_IP 2>/dev/null \
  | openssl x509 -noout -issuer -dates -ext subjectAltName    # SAN = IP:НОВЫЙ_IP, дата в будущем
echo | openssl s_client -connect НОВЫЙ_IP:4601 -verify_return_error 2>&1 | grep 'Verify return code'  # 0 (ok)

# проекты и файлы
ls ~/projects; git -C ~/projects/gameconnect status -sb; git -C ~/projects/adventuremazes status -sb
ls -l ~/web/normal-forms/index.html                  # симлинк живой
ls -l ~/.local/share/opencode/opencode.db            # 600

# timers: на новом хосте их нет — сертификат продлевает Caddy, это норма
systemctl --user list-timers --all --no-pager | grep -E 'oc-cert|opencode-student' || echo 'таймеров нет — так и должно быть'

# ресурсы
free -m | head -2; df -h /; uptime
```

**Обязательно проверить ребут** — именно тут вылезает забытый linger или невключённый юнит:

```bash
sudo reboot
# после подъёма:
systemctl --user is-active opencode-web caddy
```

---

## 13. Переключение, откат, вывод старого хоста

1. **Не выключать старый хост** минимум неделю после переезда — это точка отката.
2. Объявить новый адрес: `https://НОВЫЙ_IP:4601/`, тот же логин `opencode` и пароль из
   `~/.config/opencode-web.env`.
3. Обновить документацию: `projects/AGENTS.md`, `opencode-settings/AGENTS.md`,
   `docs/snapshot-*.md`, при необходимости — `students/.env` (`PUBLIC_URL` стенда не связан с
   основным хостом, но ссылки в доках — да).
4. Откат: старый хост продолжает работать; если что-то пошло не так — просто не переключать
   пользователей. БД не мигрирует «в одну сторону»: на новом хосте она копия.
5. Вывод старого хоста: убедиться, что исходники студенческого стенда забраны в репозиторий
   (§10.1), снять финальный бэкап БД, `systemctl --user disable --now opencode-web caddy`, и только
   потом гасить VPS. Доступ к `/srv/opencode-student` после выключения не восстановить.

---

## 14. Грабли (проверенные на этом опыте)

1. **Installer OpenCode 1 не ставит 2.x** — нужен `https://opencode.ai/v2/install`; версия
   пинится `--version 2.0.32`.
2. **Нет `python3-venv`/`pip`** в базовом образе — venv создавать `--without-pip` + `get-pip.py`
   (или `apt install python3-venv` от root).
3. **Порт 80 без root** — без `ip_unprivileged_port_start=80` не поднимется Caddy на `:4601` и не
   пройдёт ACME.
4. **Linger** — без него user-сервисы не встают после ребута/выхода из SSH.
5. **uid 1001** — иначе права на `~/.ssh`, `web`, файлы проектов разъедутся, а `%h`-пути в юнитах
   останутся прежними (это ок), но владельцы файлов будут чужими.
6. **IP-сертификат LE требует профиль `shortlived`** и HTTP-01/TLS-ALPN; без профиля —
   `rejectedIdentifier`. Это же правило — для Caddy: `issuer acme { profile shortlived }`.
7. **Сертификат живёт ~6.7 суток** — без автоматического продления стенд «протухает» за неделю;
   с Caddy продление идёт само, но проверять дату в `journalctl -u caddy` всё равно стоит.
9. **`/tmp` — tmpfs** (840 МБ): крупные архивы/образы класть в `~/tmp`, не в `/tmp`.
10. **БД с WAL**: копировать только через `sqlite3 backup` API (в скрипте это уже сделано), иначе
    получите битую копию или потеряете последние транзакции.
11. **1 vCPU**: любые сборки/браузеры на этом хосте тормозят UI; сборка студенческого образа — на
    VPS стенда, сборки проектов — на дев-машине.
12. **Ссылки на старый IP** разбросаны по конфигам, скриптам и докам — после копирования пройтись
    `grep -RIl '94\.141\.97\.249'` (см. §9).
13. **Ключи и пароли** — только файлами с правами 600; в чат/доки не вставлять. В `opencode.db`
    креды лежат в открытом виде: после удаления креда нужен `VACUUM`, иначе значение остаётся в файле.
14. **Падающие юниты старого хоста** (`opencode-student-catalog`, `-restore`) — это про docker/edge;
    на новом хосте их быть не должно (не переносить юниты `opencode-student-*`).
15. **Не тащить `/srv/opencode-student/bundles`** (1.5 ГБ) — пересобираются; но исходники из
    `sandbox` забрать обязательно (§10.1).

---

## Приложение A. Быстрый чек-лист переезда

```
[ ] старый хост: export-main-stand.sh → архив + .sha256 (600)
[ ] старый хост: git-проекты — ветки записаны, незакоммиченное закоммичено/запушено
[ ] старый хост: sandbox-source студенческого стенда попал в архив (students/sandbox-source)
[ ] новый хост: Ubuntu, 2 vCPU/2 ГБ+, диск 20 ГБ+, публичный IPv4
[ ] новый хост: deployagent uid 1001, linger, sysctl порт 80, swap (если нужно)
[ ] секреты получены у владельца (basic-auth, пароль стенда, ключ шлюза) — не из репозитория
[ ] новый хост: opencode 2.0.32 + конфиги + env (600) + БД (600) + юнит → active
[ ] новый хост: caddy 2.11.7 + Caddyfile (новый IP) + юнит → active, сертификат выпущен
[ ] новый хост: projects (архив + 2 git clone), datasets, ~/web, .ssh/.gitconfig
[ ] новый хост: проверки §12, включая reboot
[ ] студенческий стенд: поднят на отдельной VPS по §10, 31-up-fast --check + 50 = 13/13
[ ] старый хост: оставлен включённым на неделю (откат), затем выведен по §13
```

## Приложение B. Где что лежит (карта старого хоста)

| Что | Путь |
|---|---|
| Бинарь OpenCode / Caddy | `~/.opencode/bin/opencode` (2.0.32) / `~/bin/caddy` (2.11.7) |
| Конфиг OpenCode | `~/.config/opencode/opencode.jsonc` (только `$schema`) + `package.json` (плагин 1.19.3) |
| Пароль сервера | `~/.config/opencode-web.env` → `OPENCODE_SERVER_PASSWORD`, `TMPDIR=/home/deployagent/tmp` |
| Пароль в state | `~/.config/opencode/service.json` (600, ключ `password`) |
| БД | `~/.local/share/opencode/opencode.db` (57 МБ, 600) + `-wal`, `-shm` |
| Caddyfile и бэкапы | `~/.config/caddy/` (`Caddyfile`, `.known-good`, `.fallback-internal`, `backups/`) |
| Юниты | `~/.config/systemd/user/{opencode-web,caddy}.service` (+ `oc-cert-renew.*` — только на старом хосте) |
| Скрипты | `~/bin/oc-fix.sh` (восстановление); `~/bin/oc-cert-renew.sh` — на старом хосте, на новом не нужен |
| Статика | `~/web/normal-forms` → `~/projects/db_normal_forms_quiz.html` |
| Проекты | `~/projects/{gameconnect,adventuremazes,students,opencode-settings,datasets,demo}` |
| Снимок/доки | `~/projects/opencode-settings/{AGENTS.md,docs/,scripts/}` |
| Sysctl | `/etc/sysctl.d/99-unprivileged-ports.conf` (порт 80) |
| Старый студенческий стенд | `/srv/opencode-student/*` — не переезжает, исходники → `students/sandbox-source` |
