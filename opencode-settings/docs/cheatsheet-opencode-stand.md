# Шпаргалка: стенд OpenCode на новом хосте

**Адрес:** https://45.159.173.65:4601 · **Хост:** `opencode-main` (Ubuntu 26.04, 1 vCPU, 2.6 ГБ RAM, 29 ГБ)
**Что внутри:** OpenCode 2.0.32 (`127.0.0.1:4600`) + Caddy 2.11.7 (`:4601`, TLS от Let's Encrypt) + проекты в `~/projects`
**Репозиторий:** https://github.com/lkalyadin/sandbox-rudn-html

---

## Содержание

1. [Пять команд, которые нужны чаще всего](#1-пять-команд-которые-нужны-чаще-всего)
2. [TLS: продлевается сам](#2-tls-продлевается-сам)
3. [Секреты: где лежат и где их нет](#3-секреты-где-лежат-и-где-их-нет)
4. [Проекты, ветки, git](#4-проекты-ветки-git)
5. [Студенческий стенд](#5-студенческий-стенд--только-отдельная-vps)
6. [PostgreSQL (если понадобится)](#6-postgresql-если-понадобится)
7. [Бэкапы](#7-бэкапы)
8. [Аварийные сценарии](#8-аварийные-сценарии)
9. [Старый хост и откат](#9-старый-хост-и-откат)
10. [Где документация](#10-где-документация)

---

## 1. Пять команд, которые нужны чаще всего

```bash
# 1. Живой ли стенд (юниты, порты, HTTPS, сертификат, коды ответов)
bash ~/bin/oc-fix.sh

# 2. Статус сервисов
systemctl --user status opencode-web caddy

# 3. Логи
journalctl --user -u opencode-web -n 100 --no-pager
journalctl --user -u caddy -n 50 --no-pager

# 4. Проверка доступа снаружи
curl -sk -o /dev/null -w '%{http_code}\n' https://45.159.173.65:4601/            # 200
curl -sk -o /dev/null -w '%{http_code}\n' https://45.159.173.65:4601/api/model   # 401
PW=$(grep -oP '^OPENCODE_SERVER_PASSWORD=\K.*' ~/.config/opencode-web.env)
curl -sk -u opencode:"$PW" -o /dev/null -w '%{http_code}\n' \
  https://45.159.173.65:4601/api/model                                           # 200

# 5. Рестарт (opencode-web обрывает активные сессии в UI!)
systemctl --user restart opencode-web
systemctl --user reload caddy      # graceful, для Caddyfile
systemctl --user restart caddy     # если reload не подхватил изменения
```

> Все сервисы — **user-scope** (`systemctl --user`), живут без SSH-сессии благодаря linger.
> `sudo` у `deployagent` нет, и для эксплуатации стенда он не нужен.

---

## 2. TLS: продлевается сам

Сертификат выпускает **Caddy**, без certbot: Let's Encrypt на IP, профиль `shortlived` (≈6.7 суток),
challenge — HTTP-01 на 80 / TLS-ALPN на 443. Продление — автоматически (ARI, ~2/3 срока).

```bash
# какой сертификат реально отдаётся
echo | openssl s_client -connect 45.159.173.65:4601 -servername 45.159.173.65 2>/dev/null \
  | openssl x509 -noout -issuer -dates -ext subjectAltName

# проверка цепочки как у браузера (ждём 0)
echo | openssl s_client -connect 45.159.173.65:4601 -servername 45.159.173.65 -verify_return_error 2>&1 \
  | grep 'Verify return code'

# когда продлил в последний раз
journalctl --user -u caddy | grep 'certificate obtained' | tail -3
```

**Если TLS сломался:**

```bash
systemctl --user restart caddy        # Caddy перевыпустит
bash ~/bin/oc-fix.sh --reissue        # сброс хранилища сертификатов + перевыпуск
bash ~/bin/oc-fix.sh --internal       # аварийный приватный CA (браузер будет ругаться)
bash ~/bin/oc-fix.sh --letsencrypt    # вернуться обратно на Let's Encrypt
```

Порты 80/443 наружу должны быть открыты — на них проходит проверка Let's Encrypt.

---

## 3. Секреты: где лежат и где их нет

В репозитории секретов **нет** — только плейсхолдеры `<SANDBOX_PASSWORD>`, `<AI_GATEWAY_API_KEY>`.
Реальные значения — на хосте, права 600.

| Что | Где | Зачем |
|---|---|---|
| Пароль basic-auth (`opencode`) | `~/.config/opencode-web.env` | вход в UI и API на `:4601` |
| Тот же пароль в state | `~/.config/opencode/service.json` | внутренний state OpenCode |
| Ключи провайдеров (Vercel, OpenCode Go) | `~/.local/share/opencode/opencode.db` → таблица `credential` | модели; после удаления креда нужен `VACUUM` |
| Пароль и ключ шлюза студенческого стенда | `~/.config/student-sandbox.env` | сборка/подъём студенческих VPS |
| SSH-ключи git | `~/.ssh/id_ed25519_gameconnect`, `~/.ssh/id_ed25519_adventuremazes`, `~/.ssh/id_ed25519_sandbox-rudn-html` | клонирование и push |

```bash
# что в git секретов нет — проверка перед коммитом (значения не печатать!)
cd ~/projects && git status --short | head
grep -RIl --exclude-dir=.git -E 'SANDBOX_PASSWORD=|AI_GATEWAY_API_KEY=' . | head
```

---

## 4. Проекты, ветки, git

`~/projects` — клон `sandbox-rudn-html` (origin по SSH, push работает), внутри:

| Каталог | Что | Git |
|---|---|---|
| `opencode-settings/` | документация стенда, runbook переезда, скрипты | в этом же репозитории |
| `students/` | документация студенческого стенда + `sandbox-source/` (Dockerfile, compose, скрипты, навык, edge) | в этом же репозитории |
| `datasets/` | 26 CSV (World Bank, OWID) | в этом же репозитории |
| `demo/`, `*.html/.md/.docx` | архивный снимок демо-стенда и учебные материалы | в этом же репозитории |
| `gameconnect/` | форк Capacitor Game Connect | свой репозиторий, ветка `feat/cloud-save` |
| `adventuremazes/` | игра Adventure Mazes | свой репозиторий, ветка `feat/vlak-expeditions` |

```bash
cd ~/projects
git add -A && git commit -m "..." && git push        # обычный цикл
git -C gameconnect status -sb                        # состояние игровых проектов
```

`gameconnect` и `adventuremazes` собираются **на дев-машине** — на хосте нет node/JDK.
`node_modules` в репозиторий не кладём (`.gitignore`).

---

## 5. Студенческий стенд — только отдельная VPS

На этом хосте **нет** docker, gVisor, edge и `/srv` — так и должно быть. Стенд поднимается на
чистом одноразовом VPS и гасится после занятия.

**Исходники:** `~/projects/students/sandbox-source/` (Dockerfile, `docker-compose.yml`, `config/`,
`skills/`, `edge/*.conf`, `egress/`, `gateway/`, `upload-handler/`, `scripts/`).
**Инструкции:** `~/projects/students/ROOT-STEPS.md` (bootstrap) → `DEPLOY_STAND.md` (развёртывание).

Коротко:

```bash
# root на новом VPS: пользователь deployagent, docker + compose, gVisor (runsc), /srv/opencode
# затем под deployagent: скелет из sandbox-source → /srv/opencode/sandbox, поправить пути/uid/PUBLIC_URL
cd /srv/opencode/sandbox
bash scripts/00-preflight.sh
bash scripts/20-sync-workspace.sh /home/deployagent/datasets
bash scripts/30-up.sh                 # build ~6–10 мин, образ 2.4 ГБ; либо из бандла 98-deploy-from-bundle.sh
# root: bash scripts/95-root-setup.sh  (квота 30 ГБ + ночная очистка + linger)

# приёмка
bash scripts/31-up-fast.sh --check    # зелёный
bash scripts/50-verify-isolation.sh   # 13/13
bash scripts/55-verify-stand.sh       # стенд жив, сессий 0
bash scripts/56-monitor.sh            # exit 0
```

Важно: `SANDBOX_UID=SANDBOX_GID=1000` (uid внутри образа, **не** 1001), свой TLS на стенде
(certbot в контейнере + таймер), ключ шлюза — только в контейнере `gateway`, не в песочнице.

---

## 6. PostgreSQL (если понадобится)

Без root не поставить, поэтому ставится тем же одноразовым скриптом (идемпотентный):

```bash
# root на новом хосте
PG_PASSWORD='...' bash ~/tmp/new-host-bootstrap.sh \
  --ssh-key "$(head -1 ~/.ssh/authorized_keys)" \
  --with-postgres --pg-db stand --pg-user stand
```

Что получится: PostgreSQL 18, `shared_buffers=384MB`, `effective_cache_size=1536MB`, `work_mem=8MB`,
`max_connections=20`, `log_min_duration_statement=500ms`, `MemoryMax=768M` (чтобы не выселить opencode),
роль и БД. Наружу порт **не** открывается — только локально.

```bash
sudo -u postgres psql -c '\l'                 # (от root)
psql "postgresql://stand:...@127.0.0.1:5432/stand" -c 'select version()'
```

---

## 7. Бэкапы

Сейчас автоматического бэкапа нет. Если нужен — сохранить как `~/bin/oc-db-backup.sh`, `chmod +x`
и повесить user-таймер.

```bash
#!/usr/bin/env bash
# ~/bin/oc-db-backup.sh — бэкап БД OpenCode через sqlite3 backup API (WAL-безопасно)
set -euo pipefail
D="$HOME/tmp/opencode-backups"; mkdir -p "$D"; chmod 700 "$D"
python3 - "$HOME/.local/share/opencode/opencode.db" "$D/opencode-$(date -u +%Y%m%d).db" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
d = sqlite3.connect(dst)
with d: s.backup(d)
print("quick_check:", d.execute("pragma quick_check").fetchone()[0])
d.close(); s.close()
PY
chmod 600 "$D"/*.db
find "$D" -name 'opencode-*.db' -mtime +7 -delete
```

```ini
# ~/.config/systemd/user/oc-db-backup.service
[Unit]
Description=Бэкап БД OpenCode
[Service]
Type=oneshot
ExecStart=%h/bin/oc-db-backup.sh

# ~/.config/systemd/user/oc-db-backup.timer
[Unit]
Description=Ежедневный бэкап БД OpenCode
[Timer]
OnCalendar=*-*-* 05:10:00
Persistent=true
[Install]
WantedBy=timers.target
```

`systemctl --user daemon-reload && systemctl --user enable --now oc-db-backup.timer`

Копию бэкапа стоит уносить **с сервера** (S3/другой хост) — диск один.

---

## 8. Аварийные сценарии

| Симптом | Что делать |
|---|---|
| `:4601` не открывается | `systemctl --user status caddy`; `ss -ltn \| grep 4601`; `journalctl --user -u caddy -n 50` |
| `/api/*` отдаёт 401 с паролем | пароль в `~/.config/opencode-web.env`; `systemctl --user restart opencode-web` |
| UI открывается, но пусто | `journalctl --user -u opencode-web -n 100`; проверить `~/projects` на месте |
| Сертификат истёк / не отдаётся | `systemctl --user restart caddy`, затем `bash ~/bin/oc-fix.sh --reissue` |
| Caddy не стартует после правки Caddyfile | `~/bin/caddy validate --config ~/.config/caddy/Caddyfile`; откат: `cp ~/.config/caddy/Caddyfile.known-good ~/.config/caddy/Caddyfile` |
| После ребута сервисов нет | `loginctl show-user deployagent \| grep Linger` (должно `yes`); `systemctl --user is-enabled opencode-web caddy` |
| Кончилось место | `df -h /`; `journalctl --disk-usage`; `du -sh ~/.cache ~/tmp/*` |
| Не хватает памяти | `free -m`; перезапустить `opencode-web` (RSS растёт за сутки); swap 2 ГБ уже есть |

---

## 9. Старый хост и откат

`94.141.97.249:4601` пока работает как точка отката — новый адрес уже боевой, старый можно гасить,
когда убедитесь, что всё устраивает.

Перед выключением старого хоста:

- исходники студенческого стенда уже в репозитории (`students/sandbox-source`);
- БД и секреты — в архиве `~/tmp/migration/main-stand-20261029-0604.tar.gz` (600) на старом хосте;
- больше ничего уникального там нет (bundles, `workspace.img`, `monitoring` — состояние, не исходники).

После выключения доступ к `/srv/opencode-student` не восстановить — это ожидаемо.

---

## 10. Где документация

| Документ | Что внутри |
|---|---|
| `~/projects/opencode-settings/AGENTS.md` | как устроен стенд, риски, правила правок, чек-лист «стенд жив» |
| `~/projects/opencode-settings/docs/snapshot-2026-10-28.md` | фактический снимок: порты, юниты, TLS, провайдеры, БД |
| `~/projects/opencode-settings/docs/migration-runbook-2026-10.md` | переезд с нуля: хост, OpenCode, TLS, проекты, студенческий стенд, проверки, откат |
| `~/projects/students/AGENTS.md` | студенческий стенд: изоляция, лимиты, режимы, грабли |
| `~/projects/students/DEPLOY_STAND.md`, `ROOT-STEPS.md` | подъём студенческого стенда на чистом VPS |
| `~/projects/README.md` | что в репозитории и где секреты |

---

<sub>Шпаргалка от 2026-10-29. Проверено на новом хосте: юниты после ребута поднимаются, сертификат
Let's Encrypt выпускается и продлевается автоматически, API отвечает 200/401 как надо.</sub>
