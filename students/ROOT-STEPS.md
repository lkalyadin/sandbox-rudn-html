# Root-шаги на VPS: что выполняет человек в Putty

Короткий список всего, что нужно сделать **под root** на VPS со стендом.
Всё остальное (образы, `.env`, TLS, датасеты, таймеры, проверки) делает агент
от `deployagent`. Полный разбор — `DEPLOY_STAND.md`, журнал — `HANDOFF_TO_NEXT_AGENT.md`.

Проверено вживую 28.10.2026 на голых VPS (Ubuntu 26.04, 2 vCPU, 3.4 ГБ) — два подъёма подряд.

---

## 1. Первый запуск на **новом** VPS: bootstrap (один раз)

Это единственный блок, который нужен на «чистой» машине, где есть только root.
Он создаёт `deployagent` с ключом агента, ставит docker + gVisor и каталог стенда.

```bash
export DEBIAN_FRONTEND=noninteractive

# 1. пользователь для агента + ключ
useradd -m -s /bin/bash deployagent
mkdir -p /home/deployagent/.ssh
echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICw0MyR3jrsEuqUownJABYgQHagsHChMn4hf+wyIjh5+ opencode-sandbox-deploy' > /home/deployagent/.ssh/authorized_keys
chmod 700 /home/deployagent/.ssh && chmod 600 /home/deployagent/.ssh/authorized_keys
chown -R deployagent:deployagent /home/deployagent/.ssh

# 2. docker + утилиты, deployagent в группу docker
apt-get update
apt-get install -y docker.io docker-compose-v2 openssl ca-certificates curl gpg
usermod -aG docker deployagent

# 3. gVisor (runsc) — без него не поднимется изоляция песочницы
curl -fsSL https://gvisor.dev/archive.key | gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" > /etc/apt/sources.list.d/gvisor.list
apt-get update && apt-get install -y runsc
runsc install
systemctl restart docker

# 4. каталог стенда
mkdir -p /srv/opencode && chown deployagent:deployagent /srv/opencode
```

Проверить, что агент может зайти (это уже моя сторона):

```bash
id deployagent; docker --version; docker compose version; runsc --version
```

Порты наружу: **22, 80, 443** (443 обязателен: сертификат Let's Encrypt на голый IP).

---

## 2. После подъёма стенда: квота + ночная очистка (один раз, root)

Выполняется **после** того, как я поднял стенд из бандла
(`98-deploy-from-bundle.sh`). Скрипт лежит в комплекте стенда.

```bash
bash /srv/opencode/sandbox/scripts/95-root-setup.sh
```

Что делает:

1. останавливает контейнеры (bind-mount нельзя накрыть работающим контейнером);
2. создаёт образ ext4 30 ГБ и монтирует его в `/srv/opencode/workspace`
   (квота: один студент не забивает диск сервера), прописывает `/etc/fstab` (`nofail`);
3. ставит root-таймер ночной очистки **03:30 UTC** (сносит содержимое `/work`);
4. `loginctl enable-linger deployagent` — чтобы user-таймеры (restore 03:40,
   продление сертификата ~04:17, каталог по воскресеньям) жили без залогиненной сессии;
5. поднимает контейнеры обратно и возвращает датасеты в `/work/data`.

Ожидаемый вывод в конце: `df` показывает ~30G на `/srv/opencode/workspace`,
`loginctl` → `Linger=yes`.

**Не запускать повторно без причины**: он каждый раз останавливает стенд.

---

## 3. Редкие сервисные команды (тоже root)

| Задача | Команда |
|---|---|
| Ночная очистка вручную (как таймер в 03:30) | `systemctl start opencode-student-cleanup.service` |
| Проверить/включить linger | `loginctl enable-linger deployagent && loginctl show-user deployagent \| grep -i linger` |
| Продлить LE-сертификат вручную | `su - deployagent -c 'cd /srv/opencode/sandbox && bash scripts/60-renew-cert.sh'` |
| Перезагрузить сервер | просто `reboot`; контейнеры и таймеры поднимаются сами, потом я проверяю `31-up-fast.sh --check` |
| Открыть порт (если стоит ufw) | `ufw allow 22,80,443/tcp` |
| Добавить swap на маленьком VPS (1–2 ГБ RAM) | см. §3.2 |

Всё, что **не** root (стенд, модели, изоляция, сброс между парами, мониторинг)
делаю я от `deployagent` — команды в `AGENTS.md`, раздел «Команды».

### 3.2. Swap на маленьком VPS (root, один раз)

Нужен, когда у сервера ≤ 2 ГБ RAM: песочница с браузером и `opencode` живёт близко
к пределу, без swap любая тяжёлая задача ловит OOM.

```bash
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
printf 'vm.swappiness=20\n' > /etc/sysctl.d/99-swap.conf
sysctl -w vm.swappiness=20
free -m | tail -2
```

Проверка: в выводе `free -m` строка `Swap:` не нулевая, файл в `/etc/fstab` есть
(переживёт перезагрузку). Если swap уже включён — повторять не нужно.

### 3.1. Разовая смена пароля только на одном стенде (это делаю я, не root)

Нужна, когда преподаватель просит другой пароль на конкретном демо-стенде
(например `demo`), не меняя общую инструкцию:

```bash
cd /srv/opencode/sandbox
sed -i 's/^SANDBOX_PASSWORD=.*/SANDBOX_PASSWORD=demo/' .env
printf 'opencode:%s\n' "$(openssl passwd -apr1 -stdin <<< demo)" > edge/htpasswd
chmod 644 edge/htpasswd
docker compose up -d sandbox          # пересоздаёт контейнер с новым OPENCODE_SERVER_PASSWORD
docker exec opencode-student-edge nginx -s reload
```

Проверка (старый пароль должен давать 401, новый — 200):

```bash
docker exec opencode-student-sandbox sh -lc \
  "curl -s -o /dev/null -w 'new=%{http_code} ' -u opencode:demo http://127.0.0.1:4096/api/model; \
   curl -s -o /dev/null -w 'old=%{http_code}\n' -u opencode:"$SANDBOX_PASSWORD" http://127.0.0.1:4096/api/model"
curl -s -o /dev/null -w 'upload=%{http_code}\n' -u opencode:demo https://<IP>/upload/
```

`30-up.sh` и `90-reset.sh` берут пароль из `.env`, поэтому замена переживает сброс.
`/` и `/files/` паролем не закрыты (так и задумано).

---

## 4. Что уже учтено в скриптах (чтобы не повторять грабли)

Найдено при подъёме первого 2-vCPU стенда и поправлено в
`sandbox/scripts/98-deploy-from-bundle.sh` (и на живом стенде, и на хосте разработки):

- **`alpine` в bundle нет** — скрипт звал `docker run … alpine` для `chown`, и на VPS
  без доступа к Docker Hub (или с IPv6 без маршрута) падал. Теперь используется
  уже загруженный `nginx:1.27-alpine`.
- **Ресурсы не под размер VPS** — в `.env` из бандла было `SANDBOX_CPUS=3.5`,
  `SANDBOX_MEMORY=6g`; на 2 vCPU контейнер не стартовал
  («range of CPUs is from 0.01 to 2.00»). Теперь скрипт выставляет
  `CPUS=nproc` и `MEMORY=60% RAM` (не больше 6 ГБ).

Если `50-verify-isolation.sh` показывает «домен моделей недоступен через прокси»,
а остальное зелёное — это не стенд, а DNS у провайдера/в контейнере `egress`
(встречалось на одном из VPS: с хоста `Resolving timed out`, через минуту проходит).
Лечится `docker restart opencode-student-egress`; если повторяется часто — менять VPS.
