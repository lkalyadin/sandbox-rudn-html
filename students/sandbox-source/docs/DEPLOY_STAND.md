# Инструкция: развернуть студенческий стенд OpenCode на новом VPS

> Проверено вживую 24.10.2026 на голом VPS (Ubuntu 24.04, 4 vCPU, 7.2 ГБ RAM, 49 ГБ диск).
> Стенд поднят на `https://92.246.128.129` и работает: изоляция 13/13, TLS Let's Encrypt
> на голый IP, дефолтная модель — из подписки OpenCode Go.
>
> Исходники стенда: `/srv/opencode/sandbox` на уже поднятом сервере
> (или `/srv/opencode-student/sandbox` на старом).

---

## 0. Что где лежит и что НЕ копируется

Стенд = 6 контейнеров (`sandbox`, `egress`, `gateway`, `upload-handler`, `edge`, `sandbox-home`),
плюс каталог `/srv/opencode/workspace` (рабочая папка студентов).

При переносе **не копируем**: `.env` (ключи!), `edge/certs`, `edge/htpasswd`, `edge/letsencrypt`,
`workspace/` (данные студентов). Всё это пересоздаётся на новом сервере.

```bash
cd /srv/opencode-student
tar czf /tmp/sandbox-src.tgz \
  --exclude='sandbox/workspace' --exclude='sandbox/.env' \
  --exclude='sandbox/edge/certs' --exclude='sandbox/edge/htpasswd' \
  --exclude='sandbox/edge/letsencrypt' --exclude='sandbox/*.log' sandbox
scp /tmp/sandbox-src.tgz <user>@<IP>:/tmp/
```

> `edge/letsencrypt` в старом стенде принадлежит root — без `--exclude` tar падает с «Permission denied».

---

## 1. Root-блок (выполняет пользователь в Putty, один раз)

```bash
useradd -m -s /bin/bash deployagent
mkdir -p /home/deployagent/.ssh
echo '<ПУБЛИЧНЫЙ КЛЮЧ АГЕНТА>' > /home/deployagent/.ssh/authorized_keys
chmod 700 /home/deployagent/.ssh && chmod 600 /home/deployagent/.ssh/authorized_keys
chown -R deployagent:deployagent /home/deployagent/.ssh

apt-get update
apt-get install -y docker.io docker-compose-v2 openssl ca-certificates curl gpg
usermod -aG docker deployagent          # это фактически root для агента

curl -fsSL https://gvisor.dev/archive.key | gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" > /etc/apt/sources.list.d/gvisor.list
apt-get update && apt-get install -y runsc
runsc install
systemctl restart docker

mkdir -p /srv/opencode && chown deployagent:deployagent /srv/opencode
```

Порты наружу: **22, 80, 443**.

После этого — `sudo bash /srv/opencode/sandbox/scripts/95-root-setup.sh`
(квота ext4 30 ГБ на workspace + ночная очистка в 03:30 + `enable-linger`; скрипт в комплекте стенда).

---

## 2. Агент: подготовка каталога

```bash
ssh -i ~/.ssh/sandbox_new_ed25519 deployagent@<IP>
mkdir -p /srv/opencode/sandbox
tar xzf /tmp/sandbox-src.tgz -C /srv/opencode
rm -rf /srv/opencode/sandbox/workspace
```

Правки под новый сервер (одной пачкой):

```bash
cd /srv/opencode/sandbox
# пути стенда
grep -rl "opencode-student/workspace\|<СТАРЫЙ_IP>" scripts docker-compose.yml edge egress skills | \
  xargs sed -i "s#/srv/opencode-student/workspace#/srv/opencode/workspace#g; s#https://<СТАРЫЙ_IP>#https://<НОВЫЙ_IP>#g"
# датасеты: дефолтный путь
sed -i "s#/home/deployagent/projects/datasets#/home/deployagent/datasets#g" scripts/*.sh
# uid песочницы = uid deployagent на сервере (проверь: id deployagent)
sed -i "s/^SANDBOX_UID=.*/SANDBOX_UID=<UID>/; s/^SANDBOX_GID=.*/SANDBOX_GID=<GID>/" .env
# upload-handler пишет в workspace — у него тоже должен быть этот uid
sed -i "s#user: \"1000:1000\"#user: \"\${SANDBOX_UID:-<UID>}:\${SANDBOX_GID:-<GID>}\"#" docker-compose.yml
mkdir -p /srv/opencode/workspace
```

`.env` готовится из `.env` старого стенда: меняются только `PUBLIC_URL` и `ENABLE_TLS=true`.
`SANDBOX_PASSWORD` — тот же (студенты помнят один пароль), `AI_GATEWAY_API_KEY` и `OPENCODE_GO_API_KEY` — свои.

---

## 3. Запуск

```bash
cd /srv/opencode/sandbox
bash scripts/30-up.sh          # htpasswd + сертификат-fallback + сборка образов + up + проверка готовности
bash scripts/20-sync-workspace.sh /home/deployagent/datasets   # датасеты в /work/data
bash scripts/70-build-catalog.sh                                # каталог для агента
```

Сборка песочницы (2.4 ГБ образ) занимает ~6–10 минут. Датасеты кладутся на хост сюда:
`/home/deployagent/datasets` (копия `projects/datasets`).

---

## 4. TLS: Let's Encrypt на голый IP

**Главная находка 24.10.2026:** в certbot 5.8 для IP-сертификатов нужен флаг
**`--ip-address`**, а не `-d`. Старая команда из документации (`certonly -d <IP>`) отдаёт
«Let's Encrypt не выдаёт сертификаты на голый IP» — даже с `--preferred-profile shortlived`.

```bash
cd /srv/opencode/sandbox
mkdir -p edge/letsencrypt edge/acme edge/certs

docker run --rm \
  -v "$PWD/edge/letsencrypt:/etc/letsencrypt" \
  -v "$PWD/edge/acme:/var/www/.well-known/acme-challenge" \
  certbot/certbot certonly --webroot -w /var/www \
  --ip-address <IP> --preferred-profile shortlived \
  --agree-tos --register-unsafely-without-email --keep-until-expiring

docker run --rm -v "$PWD/edge/letsencrypt:/etc/letsencrypt" -v "$PWD/edge/certs:/out" \
  --entrypoint sh certbot/certbot -c "
    cp -L /etc/letsencrypt/live/<IP>/fullchain.pem /out/fullchain.pem
    cp -L /etc/letsencrypt/live/<IP>/privkey.pem  /out/privkey.pem
    chmod 644 /out/fullchain.pem; chmod 600 /out/privkey.pem"

docker exec opencode-student-edge nginx -s reload
openssl x509 -in edge/certs/fullchain.pem -noout -dates
```

Профиль `shortlived` = ~6.4 суток, поэтому нужен ежедневный `certbot renew` (таймер ниже).
Проверка ACME работает через webroot `edge/acme` → nginx `location /.well-known/acme-challenge/`.

---

## 5. Таймеры

Пользовательские (от `deployagent`):

```bash
cp opencode-student-{restore,cert,catalog}.{service,timer} ~/.config/systemd/user/
sed -i "s#/srv/opencode-student/sandbox#/srv/opencode/sandbox#g" ~/.config/systemd/user/*.service
systemctl --user daemon-reload
for n in restore cert catalog; do systemctl --user enable --now opencode-student-$n.timer; done
```

| Таймер | Время | Что делает |
|---|---|---|
| `opencode-student-cleanup.timer` (root) | 03:30 | стирает содержимое workspace |
| `opencode-student-restore.timer` (user) | 03:40 | возвращает датасеты и стартовые файлы |
| `opencode-student-cert.timer` (user) | 04:17 | `certbot renew` (ARI сам решает, пора ли) |
| `opencode-student-catalog.timer` (user) | воскресенье 05:20 | пересборка каталога датасетов |

Для пользовательских таймеров нужен `loginctl enable-linger deployagent` (root, делает 95-root-setup.sh).

---

## 6. Приёмка

```bash
bash scripts/31-up-fast.sh --check     # контейнеры, ключи, модели, доступность
bash scripts/50-verify-isolation.sh    # 13/13
bash scripts/92-project-work.sh        # имя проекта "work" в UI
```

Плюс руками снаружи:

| Проверка | Ожидаемо |
|---|---|
| `https://<IP>/` | 200, окно входа basic-auth |
| `https://<IP>/files/` | 403 (листинг закрыт — так задумано) |
| `https://<IP>/files/output/<файл>` | 200, файл скачивается |
| `https://<IP>/sw.js` | 200 (свой service worker, не workbox!) |
| `docker exec opencode-student-sandbox opencode run "ок"` | дефолтная модель отвечает |
| `docker compose logs egress \| grep -i blocked` | пусто (ничего не заблокировано зря) |

---

## 7. Модели и ключи

- Провайдер `opencode` (ключ `public`) — бесплатные модели, **общий квота на всех студентов**,
  может отдавать «Free usage limit reached».
- Провайдер `go-cheap` — подписка OpenCode Go, ключ лежит в `config/opencode.json`
  (в этой версии стенда — **в песочнице**, см. риск ниже) и в `.env` как `OPENCODE_GO_API_KEY`.
- Провайдер `vercel-free` — через контейнер `gateway`: настоящий ключ в шлюзе, в песочнице его нет,
  прокси режет модели вне белого списка `GATEWAY_ALLOWED_MODELS`.

**Риск (осознанный, 24.10.2026):** ключ Go лежит в песочнице, поэтому агент студента достаёт
его одной командой (`opencode auth export` / SQLite-БД `opencode.db` / `/proc/self/environ`).
Курс стенда временный; после снятия стенда ключ подписки **сменить**.
Если нужен непротекаемый вариант — переделать по схеме `vercel-free`: ключ в контейнере `gateway`,
в песочнице только `baseURL` на прокси.

Лимиты Go считаются в долларах на модель (5 ч — 20% месячного бюджета, месяц — 100%).
Поэтому в `go-cheap` открыты только самые дешёвые модели: `muse-spark-1.2-contributor`,
`mimo-v2.6-flash`, `gpt-5.6-luna`, `claude-haiku-5-5`, `glm-5.3-flash`, `deepseek-v4.1-flash`.

---

## 8. Грабли (не наступать снова)

1. **certbot и IP** — только `--ip-address`, не `-d` (см. §4).
2. **uid песочницы** = uid пользователя, которому принадлежит `/srv/opencode/workspace`.
   Если в `.env` 1000, а каталог принадлежит 1001 — песочница не пишет в `/work` (и `upload-handler` тоже).
3. **DNS под gVisor не работает** — статические IP `egress`/`edge` в сетях и `extra_hosts` у песочницы
   не трогать (в compose уже зашито: `172.28.0.5` = edge).
4. **Правки `config/opencode.json` и навыка** применяются только после `docker compose restart sandbox`.
5. **Правки `edge/site.*.conf`** — только после `docker compose restart edge` (`envsubst` работает на старте).
6. **Свой `edge/sw.js`** — штатный service worker OpenCode перехватывает навигацию и отдаёт
   «Unrecognised route!».
7. **CSP `sandbox`** у `/files/` обязателен — иначе HTML из песочницы выполнится в origin UI.
8. **Диск**: 49 ГБ на VPS — образы ~3 ГБ, квота workspace 30 ГБ. Следить за `df -h`.
9. **Ночная очистка (root)** стирает workspace целиком, включая `data/` — датасеты возвращает
   user-таймер в 03:40.
10. **`edge/letsencrypt` принадлежит root** — при копировании стенда tar отвалится без `--exclude`.

---

## 9. Гашение стенда (файлы остаются)

```bash
cd /srv/opencode/sandbox
docker compose stop        # обратимо: поднять обратно — docker compose start
```

Контейнеры с `restart: unless-stopped`, остановленные вручную, после ребута не поднимаются.
Если нужно убрать совсем: `docker compose down` (образы и `.env` останутся на диске).

---

## 10. Быстрый подъём нового стенда из заготовки-бандла (2–3 минуты)

Когда старый демо-стенд погашен, а поднять нужно новый на другом IP — не собираем образы заново,
а берём готовые. Бандл лежит на хосте разработки:

```
/srv/opencode-student/bundles/stand-<метка>.tar.gz     (~766 МБ, права 600)
```

Внутри: `images.tar.gz` (собранные образы), `skeleton.tar.gz` (каркас),
`env.template` (пароль + ключи, **секрет**), `98-deploy-from-bundle.sh`, `README.txt`.

Пересобрать бандл после правок стенда (например, после смены моделей или пароля):

```bash
cd /srv/opencode-student/sandbox
sg docker -c "bash scripts/97-make-stand-bundle.sh"     # пока docker на хосте ещё включён
```

Подъём на новом VPS:

```bash
tar xzf stand-<метка>.tar.gz
cd stand-<метка>
bash 98-deploy-from-bundle.sh <НОВЫЙ_IP>     # load + compose up + TLS + датасеты
# затем под root:
bash /srv/opencode/sandbox/scripts/95-root-setup.sh   # квота на диск + ночная очистка
```

Скрипт сам: распаковывает скелет, `docker load`, правит `.env` под новый IP и uid,
поднимает контейнеры **без сборки**, выпускает LE-сертификат на IP, возвращает датасеты
и собирает каталог, зовёт `31-up-fast.sh --check`.

> **Важно:** после `docker load` на сервере, где стенд уже работает, теги образов
> могут «съехать» на загруженные (другие image ID). Тогда `docker compose up -d`
> пересоздаст контейнеры — со студентами это перерыв. Лечится безопасно:
> ```bash
> for c in opencode-student-sandbox opencode-student-egress opencode-student-gateway opencode-upload-handler; do
>   docker tag "$(docker inspect "$c" --format '{{.Image}}')" "$(docker inspect "$c" --format '{{.Config.Image}}')"
> done
> ```
> На пустом стенде это не нужно.

---

## 11. Мелочи, которые стоили времени

- **`/tmp` на хосте разработки — tmpfs в RAM (821 МБ).** Архив образов туда не влезает
  («Disk quota exceeded» от gzip), и большой файл в `/tmp` ест память. Крупные файлы —
  только на диск (`/srv/...`), рабочий каталог бандла специально создан там.
- **`certbot` и IP-сертификаты** — только `--ip-address`, не `-d` (см. §4).
- **uid песочницы** = владелец `/srv/opencode/workspace` (см. §2).
- **Сертификат LE на IP живёт ~6.4 суток** — таймер продления обязателен.
- **Панель мониторинга** переезжает вместе со стендом: каталог `monitoring/` копируется
  вместе с `data/` (БД и `id_ed25519` — root-owned, выгружаются через
  `docker run alpine tar`); `APP_URL` в compose переводится на новый IP.
