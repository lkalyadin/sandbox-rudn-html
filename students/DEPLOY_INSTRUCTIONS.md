# Инструкция по развёртыванию студенческого стенда OpenCode на текущем сервере

> **Исторический документ (до 29.10.2026).** Описывает развёртывание студенческого стенда
> на старом основном хосте `94.141.97.249` (там же, где работал `:4601`). С 29.10.2026
> основной стенд — `https://45.159.173.65:4601`, а студенческий стенд живёт только на
> отдельной одноразовой VPS (актуальный адрес — в `.env` стенда; на 29.10 это
> `https://45.159.173.29`). Инструкция оставлена как разбор старой схемы.

> **Контекст**: На сервере уже работает OpenCode v2 (systemd + Caddy) на `https://94.141.97.249:4601/`.
> Нужно: оставить его **только** на порту 4601, и развернуть **новый** изолированный стенд для студентов
> на `https://94.141.97.249/` (порт 443) с Docker + gVisor + egress-прокси + nginx.
> Добавить возможность загрузки HTML-визуализаций студентами (файлы в `work/`, удаление через 24ч).

---

## 0. Что уже есть на сервере

| Компонент | Статус |
|-----------|--------|
| OpenCode v2 (systemd) | Работает на `127.0.0.1:4600` |
| Caddy (HTTPS) | Проксирует `:4601` → `127.0.0.1:4600` |
| Пользователь | `deployagent` (uid 1001), **без sudo** |
| Docker | **НЕ установлен** |
| gVisor (runsc) | **НЕ установлен** |
| Данные для студентов | `/home/deployagent/projects/datasets/` |
| Каркас нового стенда | `/home/deployagent/projects/demo/opencode-sandbox/` |

---

## 1. Подготовка (выполняет пользователь с root)

### 1.1. Установка Docker + Compose + gVisor

```bash
# 1) Обновление и базовые пакеты
apt-get update
apt-get install -y docker.io docker-compose-v2 openssl ca-certificates curl gnupg

# 2) Добавить deployagent в группу docker (ВНИМАНИЕ: это фактически root на хосте)
usermod -aG docker deployagent

# 3) Установка gVisor (runsc)
curl -fsSL https://gvisor.dev/archive.key | gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" > /etc/apt/sources.list.d/gvisor.list
apt-get update && apt-get install -y runsc
runsc install
systemctl restart docker
runsc --version
```

> **После этого**: `deployagent` должен **выйти и зайти заново** по SSH.

### 1.2. Создание каталога стенда и квота на диск (60 ГБ)

```bash
mkdir -p /srv/opencode-student
chown deployagent:deployagent /srv/opencode-student

truncate -s 60G /srv/opencode-student/workspace.img
mkfs.ext4 -q -F /srv/opencode-student/workspace.img
mkdir -p /srv/opencode-student/workspace
mount -o loop /srv/opencode-student/workspace.img /srv/opencode-student/workspace
echo '/srv/opencode-student/workspace.img /srv/opencode-student/workspace ext4 loop,defaults 0 2' >> /etc/fstab

chown 1000:1000 /srv/opencode-student/workspace
```

### 1.3. Ночная очистка (systemd timer)

```bash
cat > /etc/systemd/system/opencode-student-cleanup.service <<'EOF'
[Unit]
Description=Ночная очистка рабочей папки студенческого стенда OpenCode

[Service]
Type=oneshot
ExecStart=/usr/bin/find /srv/opencode-student/workspace -mindepth 1 -delete
EOF

cat > /etc/systemd/system/opencode-student-cleanup.timer <<'EOF'
[Unit]
Description=Запуск очистки студенческого стенда ночью

[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true
Unit=opencode-student-cleanup.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now opencode-student-cleanup.timer
```

### 1.4. Открыть порты 80 и 443

```bash
ufw allow 80/tcp
ufw allow 443/tcp
```

---

## 2. Развёртывание нового стенда (deployagent после релогина)

### 2.1. Копирование каркаса

```bash
cd /home/deployagent/projects
cp -r demo/opencode-sandbox /srv/opencode-student/sandbox
cd /srv/opencode-student/sandbox
```

### 2.2. Создание `.env`

```bash
cp .env.example .env
# Отредактируйте .env:
#   SANDBOX_PASSWORD=<сильный_пароль_для_студентов>
#   EDGE_PORT=80
#   EDGE_HTTPS_PORT=443
#   ENABLE_TLS=true
#   PUBLIC_URL=https://94.141.97.249
#   SANDBOX_UID=1000
#   SANDBOX_GID=1000
#   OPENCODE_IMAGE=ghcr.io/anomalyco/opencode:2.0.32
```

### 2.3. Подготовка workspace

```bash
bash scripts/20-sync-workspace.sh
```

### 2.4. Навык (skill) для студентов-экономистов

```bash
mkdir -p /srv/opencode-student/sandbox/skills/economist-sandbox
cat > /srv/opencode-student/sandbox/skills/economist-sandbox/SKILL.md <<'EOF'
# Кто ты

Ты — песочница агентной разработки для студентов экономического факультета.
Урок называется «Визуализация данных с помощью AI». Твоя задача — помогать
студенту загружать учебные данные, считать по ним статистику и делать понятные
визуализации. Объясняй шаги простым языком: студенты экономисты, а не программисты.

# Что тебе доступно в интернете

Только эти ресурсы (остальное заблокировано на уровне сети, бесполезно пытаться):
- GitHub-репозиторий учебных датасетов: https://github.com/prasertcbs/basic-dataset
  (в нём готовые CSV: superstore, bike_sharing, netflix_titles, world_happiness,
   seattle_airbnb, video_games, airline_satisfaction, flight_delay и другие)
- openml.org — репозиторий датасетов
- archive.ics.uci.edu — классические датасеты UCI
- huggingface.co и datasets-server.huggingface.co — датасеты Hugging Face

Если чего-то нет в списке — считай, что этого нет вовсе. Не предлагай студенту
источники, которые не откроются. Доступ идёт через прокси: используй стандартные
клиенты (requests, urllib, pandas.read_csv) — они уважают HTTP_PROXY сами.

# Чего делать НЕЛЬЗЯ

- Подключать внешние JS/CSS с CDN. cdn.jsdelivr.net, unpkg.com и подобные
  заблокированы. Графики в HTML делай самодостаточными: PNG в base64
  (matplotlib) или inline SVG. Один HTML-файл, никаких внешних зависимостей.
- Выполнять sudo, ssh, mount, ставить пакеты, ходить в интернет куда-то ещё.
- Пытаться выйти за пределы рабочей папки.

# Как отдавать результат студенту

1. Складывай результат в `output/`.
2. Давай студенту готовую ссылку: `https://94.141.97.249/files/output/<имя файла>`
   → клик по ней скачивает файл в его браузер. Других способов получить файл
   у студента нет: к файловой системе он доступа не имеет.
3. В конце ответа напиши, что сделал, простыми словами.

# Как готовить файлы

Главное правило: **HTML обязан быть самодостаточным**. Никаких ссылок на внешние
JS/CSS: они не загрузятся, и страница у студента будет пустой.

- График через matplotlib: PNG в base64 или inline SVG, подписанные оси, заголовок,
  подписи на русском. Самый надёжный путь, всегда работает.
- График через plotly: **только** `fig.write_html(path, include_plotlyjs=True)`.
  По умолчанию plotly пишет `include_plotlyjs='cdn'`, и график не появится вовсе.
- Интерактив через Chart.js или D3: вставь содержимое файла из `/opt/viz/` прямо
  внутрь `<script>...</script>` в HTML.
- Altair не используй: он по умолчанию тянет vega с CDN.
- Таблица: маленькая — прямо в HTML; большая — отдельным CSV в `output/`.
- Данные из xlsx/parquet сначала приводи к CSV, чтобы не гонять тяжёлые форматы.
- Если датасет большой — не грузи его целиком в контекст, считай через pandas
  в скрипте и показывай студенту только итог.
EOF
```

### 2.5. Обновление `docker-compose.yml`

Замените содержимое `/srv/opencode-student/sandbox/docker-compose.yml`:

```yaml
name: opencode-student

services:
  sandbox:
    build:
      context: .
      dockerfile: docker/Dockerfile
      args:
        OPENCODE_IMAGE: ${OPENCODE_IMAGE:-ghcr.io/anomalyco/opencode:2.0.32}
        SANDBOX_UID: ${SANDBOX_UID:-1000}
        SANDBOX_GID: ${SANDBOX_GID:-1000}
    image: opencode-student-sandbox:local
    container_name: opencode-student-sandbox
    restart: unless-stopped
    working_dir: /work
    runtime: ${SANDBOX_RUNTIME:-runsc}
    user: "${SANDBOX_UID:-1000}:${SANDBOX_GID:-1000}"
    read_only: true
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
    pids_limit: ${SANDBOX_PIDS:-512}
    mem_limit: ${SANDBOX_MEMORY:-6g}
    cpus: ${SANDBOX_CPUS:-3.5}
    shm_size: 256m
    environment:
      HOME: /home/sandbox
      XDG_CONFIG_HOME: /home/sandbox/.config
      XDG_DATA_HOME: /home/sandbox/.local/share
      XDG_STATE_HOME: /home/sandbox/.local/state
      XDG_CACHE_HOME: /home/sandbox/.cache
      HTTP_PROXY: http://egress:8888
      HTTPS_PROXY: http://egress:8888
      NO_PROXY: localhost,127.0.0.1,::1,sandbox
      OPENCODE_SERVER_PASSWORD: ${SANDBOX_PASSWORD:?SANDBOX_PASSWORD is required}
      PUBLIC_URL: ${PUBLIC_URL:-https://94.141.97.249}
    tmpfs:
      - /tmp:size=256m,mode=1777
    volumes:
      - sandbox-home:/home/sandbox
      - /srv/opencode-student/workspace:/work
      - ./config/opencode.json:/etc/opencode/opencode.json:ro
      - ./skills/economist-sandbox:/etc/opencode/skills/economist-sandbox:ro
    networks: [sandbox_net]
    expose:
      - "4096"
    depends_on: [egress]

  egress:
    build:
      context: ./egress
      dockerfile: Dockerfile
    image: opencode-student-egress:local
    container_name: opencode-student-egress
    restart: unless-stopped
    user: "65534:65534"
    read_only: true
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
    tmpfs:
      - /tmp:size=16m
    networks:
      - sandbox_net
      - egress_out

  upload-handler:
    image: python:3.12-slim-bookworm
    container_name: opencode-upload-handler
    restart: unless-stopped
    user: "1000:1000"
    read_only: true
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
    tmpfs:
      - /tmp:size=64m
    volumes:
      - /srv/opencode-student/workspace:/srv/files:rw
    working_dir: /app
    command: >
      sh -c "pip install --no-cache-dir flask gunicorn &&
             python3 -c '
import os, uuid
from flask import Flask, request, jsonify

app = Flask(__name__)
UPLOAD_DIR = "/srv/files/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.route("/", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400
    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error": "No selected file"}), 400
    if not f.filename.lower().endswith((".html", ".htm")):
        return jsonify({"error": "Only .html/.htm files allowed"}), 400
    ext = os.path.splitext(f.filename)[1]
    fname = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, fname)
    f.save(path)
    url = f"https://94.141.97.249/files/uploads/{fname}"
    return jsonify({"url": url, "filename": fname}), 200

@app.route("/health", methods=["GET"])
def health():
    return "ok", 200

app.run(host="0.0.0.0", port=8080)
' "
    networks: [sandbox_net, edge_out]
    expose: ["8080"]
    depends_on: [edge]

  edge:
    image: nginx:1.27-alpine
    container_name: opencode-student-edge
    restart: unless-stopped
    environment:
      ENABLE_TLS: ${ENABLE_TLS:-true}
      EDGE_HTTPS_PORT: ${EDGE_HTTPS_PORT:-443}
    volumes:
      - ./edge/entrypoint.sh:/docker-entrypoint.d/10-sandbox.sh:ro
      - ./edge/site.http.conf:/etc/nginx/templates/site.http.conf:ro
      - ./edge/site.tls.conf:/etc/nginx/templates/site.tls.conf:ro
      - ${TLS_CERT_DIR:-./edge/certs}:/etc/nginx/certs:ro
      - /srv/opencode-student/workspace:/srv/files:ro
      - ./edge/htpasswd:/etc/nginx/htpasswd:ro
    ports:
      - "80:80"
      - "443:443"
    networks:
      - sandbox_net
      - edge_out
    depends_on: [sandbox, upload-handler]

networks:
  sandbox_net:
    internal: true
  egress_out: {}
  edge_out: {}

volumes:
  sandbox-home:
```

### 2.6. Полный `config/opencode.json`

Замените `/srv/opencode-student/sandbox/config/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "update": "disable",
  "model": "opencode/deepseek-v4.1-flash-free",
  "share": "disabled",
  "tool_output": {
    "max_lines": 400,
    "max_bytes": 32768
  },
  "media": {
    "image": {
      "auto_resize": true,
      "max_width": 1600,
      "max_height": 1600,
      "max_base64_bytes": 2097152
    }
  },
  "permissions": [
    { "action": "external_directory", "resource": "*", "effect": "deny" },
    { "action": "webfetch",  "resource": "*", "effect": "deny" },
    { "action": "websearch", "resource": "*", "effect": "deny" },
    { "action": "shell", "resource": "*", "effect": "ask" },
    { "action": "shell", "resource": "python3 *", "effect": "allow" },
    { "action": "shell", "resource": "python *",  "effect": "allow" },
    { "action": "shell", "resource": "uv *",      "effect": "allow" },
    { "action": "shell", "resource": "ls *",      "effect": "allow" },
    { "action": "shell", "resource": "cat *",     "effect": "allow" },
    { "action": "shell", "resource": "head *",    "effect": "allow" },
    { "action": "shell", "resource": "tail *",    "effect": "allow" },
    { "action": "shell", "resource": "wc *",      "effect": "allow" },
    { "action": "shell", "resource": "grep *",    "effect": "allow" },
    { "action": "shell", "resource": "find *",    "effect": "allow" },
    { "action": "shell", "resource": "sort *",    "effect": "allow" },
    { "action": "shell", "resource": "uniq *",    "effect": "allow" },
    { "action": "shell", "resource": "cut *",     "effect": "allow" },
    { "action": "shell", "resource": "sed *",     "effect": "allow" },
    { "action": "shell", "resource": "awk *",     "effect": "allow" },
    { "action": "shell", "resource": "mkdir *",   "effect": "allow" },
    { "action": "shell", "resource": "cp *",      "effect": "allow" },
    { "action": "shell", "resource": "mv *",      "effect": "allow" },
    { "action": "shell", "resource": "touch *",   "effect": "allow" },
    { "action": "shell", "resource": "echo *",    "effect": "allow" },
    { "action": "shell", "resource": "git status *", "effect": "allow" },
    { "action": "shell", "resource": "git diff *",   "effect": "allow" },
    { "action": "shell", "resource": "git log *",    "effect": "allow" },
    { "action": "shell", "resource": "rm *", "effect": "ask" },
    { "action": "read", "resource": "**/.env",     "effect": "deny" },
    { "action": "read", "resource": "**/.env.*",   "effect": "deny" },
    { "action": "read", "resource": "**/.ssh/**",  "effect": "deny" },
    { "action": "read", "resource": "**/.aws/**",  "effect": "deny" },
    { "action": "read", "resource": "**/.config/opencode/**", "effect": "deny" },
    { "action": "read", "resource": "**/opencode.db",          "effect": "deny" },
    { "action": "read", "resource": "/etc/**",     "effect": "deny" },
    { "action": "edit", "resource": "/etc/**",     "effect": "deny" },
    { "action": "edit", "resource": "**/.config/opencode/**", "effect": "deny" }
  ],
  "policies": [
    { "action": "provider.use", "resource": "*",           "effect": "deny"  },
    { "action": "provider.use", "resource": "opencode",    "effect": "allow" },
    { "action": "provider.use", "resource": "opencode-go", "effect": "allow" },
    { "action": "tool.use", "resource": "webfetch:*",  "effect": "deny" },
    { "action": "tool.use", "resource": "websearch:*", "effect": "deny" },
    { "action": "tool.use", "resource": "external_directory:*", "effect": "deny" },
    { "action": "tool.use", "resource": "shell:sudo *",      "effect": "deny" },
    { "action": "tool.use", "resource": "shell:su *",        "effect": "deny" },
    { "action": "tool.use", "resource": "shell:ssh *",       "effect": "deny" },
    { "action": "tool.use", "resource": "shell:scp *",       "effect": "deny" },
    { "action": "tool.use", "resource": "shell:sftp *",      "effect": "deny" },
    { "action": "tool.use", "resource": "shell:curl *",      "effect": "deny" },
    { "action": "tool.use", "resource": "shell:wget *",      "effect": "deny" },
    { "action": "tool.use", "resource": "shell:nc *",        "effect": "deny" },
    { "action": "tool.use", "resource": "shell:ncat *",      "effect": "deny" },
    { "action": "tool.use", "resource": "shell:telnet *",    "effect": "deny" },
    { "action": "tool.use", "resource": "shell:nmap *",      "effect": "deny" },
    { "action": "tool.use", "resource": "shell:mount *",     "effect": "deny" },
    { "action": "tool.use", "resource": "shell:umount *",    "effect": "deny" },
    { "action": "tool.use", "resource": "shell:docker *",    "effect": "deny" },
    { "action": "tool.use", "resource": "shell:systemctl *", "effect": "deny" },
    { "action": "tool.use", "resource": "shell:pip install *", "effect": "deny" },
    { "action": "tool.use", "resource": "shell:apt *",       "effect": "deny" },
    { "action": "tool.use", "resource": "shell:git push *",   "effect": "deny" },
    { "action": "tool.use", "resource": "shell:git remote *", "effect": "deny" }
  ],
  "skills": [
    "economist-sandbox"
  ],
  "default_agent": "economist",
  "agents": {
    "economist": {
      "model": "opencode/deepseek-v4.1-flash-free",
      "instructions": [
        "/etc/opencode/skills/economist-sandbox/SKILL.md"
      ]
    }
  }
}
```

### 2.7. Обновление `docker/Dockerfile`

Замените `/srv/opencode-student/sandbox/docker/Dockerfile`:

```dockerfile
ARG OPENCODE_IMAGE=ghcr.io/anomalyco/opencode:2.0.32
FROM ${OPENCODE_IMAGE}

USER root

RUN set -eux; \
    if command -v apt-get >/dev/null 2>&1; then \
        apt-get update; \
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            ca-certificates git python3 python3-pip python3-venv sqlite3 \
            jq less nano curl; \
        rm -rf /var/lib/apt/lists/*; \
    elif command -v apk >/dev/null 2>&1; then \
        apk add --no-cache ca-certificates git python3 py3-pip sqlite jq less nano curl; \
    else \
        echo "!! Неизвестный пакетный менеджер в базовом образе" >&2; \
        exit 1; \
    fi

RUN set -eux; \
    pip3 install --no-cache-dir --break-system-packages \
        pandas numpy matplotlib seaborn scipy \
        openpyxl pyarrow statsmodels plotly 2>/dev/null \
    || pip3 install --no-cache-dir \
        pandas numpy matplotlib seaborn scipy \
        openpyxl pyarrow statsmodels plotly

RUN set -eux; \
    mkdir -p /opt/viz; \
    curl -fsSL "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js" \
      -o /opt/viz/chart.umd.min.js; \
    curl -fsSL "https://cdn.jsdelivr.net/npm/plotly.js@2.32.0/dist/plotly-basic.min.js" \
      -o /opt/viz/plotly-basic.min.js; \
    curl -fsSL "https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js" \
      -o /opt/viz/d3.v7.min.js; \
    ls -lh /opt/viz/

COPY workspace.template/inline_chart.py /opt/viz/inline_chart.py
RUN chmod 644 /opt/viz/inline_chart.py

ARG SANDBOX_UID=1000
ARG SANDBOX_GID=1000
RUN set -eux; \
    if ! getent group "${SANDBOX_GID}" >/dev/null; then \
        (command -v addgroup >/dev/null 2>&1 && addgroup -g "${SANDBOX_GID}" sandbox) \
        || groupadd -g "${SANDBOX_GID}" sandbox; \
    fi; \
    if ! getent passwd "${SANDBOX_UID}" >/dev/null; then \
        (command -v adduser >/dev/null 2>&1 && adduser -D -u "${SANDBOX_UID}" -G sandbox -h /home/sandbox -s /bin/sh sandbox) \
        || useradd -u "${SANDBOX_UID}" -g sandbox -m -d /home/sandbox -s /bin/sh sandbox; \
    fi; \
    mkdir -p /home/sandbox/.config /home/sandbox/.local /home/sandbox/.cache \
             /home/sandbox/.local/share /home/sandbox/.local/state \
             /work /etc/opencode; \
    chown -R "${SANDBOX_UID}:${SANDBOX_GID}" /home/sandbox /work /opt/viz

COPY config/opencode.json /etc/opencode/opencode.json
COPY docker/entrypoint.sh /usr/local/bin/sandbox-entrypoint.sh
RUN chmod 0755 /usr/local/bin/sandbox-entrypoint.sh

LABEL org.opencontainers.image.title="opencode-student-sandbox" \
      org.opencontainers.image.description="Демо-стенд OpenCode для студентов-экономистов: изолированная песочница"

USER ${SANDBOX_UID}:${SANDBOX_GID}
WORKDIR /work
EXPOSE 4096
ENTRYPOINT ["/usr/local/bin/sandbox-entrypoint.sh"]
```

### 2.8. Обновление `docker/entrypoint.sh`

Добавьте в `/srv/opencode-student/sandbox/docker/entrypoint.sh` перед `exec opencode serve`:

```bash
# Подстановка PUBLIC_URL в навык
if [ -n "${PUBLIC_URL:-}" ] && [ -f /etc/opencode/skills/economist-sandbox/SKILL.md ]; then
  sed -i "s|http://<IP>|${PUBLIC_URL}|g" /etc/opencode/skills/economist-sandbox/SKILL.md
  log "PUBLIC_URL подставлен в навык: ${PUBLIC_URL}"
fi
```

### 2.9. Обновление `edge/site.tls.conf`

Добавьте в начало файла (перед `map`):

```nginx
upstream upload-handler {
  server upload-handler:8080;
}
```

Внутри `server` блока (после `location /files/`):

```nginx
  # ── Загрузка HTML-визуализаций студентами ──────────────────────────────────
  location /upload/ {
    auth_basic "opencode";
    auth_basic_user_file /etc/nginx/htpasswd;

    client_max_body_size 50m;
    client_body_temp_path /tmp/nginx_upload;

    proxy_pass http://upload-handler;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
```

### 2.10. Страница загрузки

```bash
mkdir -p /srv/opencode-student/workspace/uploads
cat > /srv/opencode-student/workspace/uploads/index.html <<'EOF'
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Загрузка визуализаций — OpenCode Sandbox</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; }
    .drop-zone { border: 2px dashed #ccc; border-radius: 8px; padding: 3rem; text-align: center; transition: border-color .2s; }
    .drop-zone.drag { border-color: #0066cc; background: #f0f7ff; }
    .drop-zone input { display: none; }
    .btn { display: inline-block; padding: .75rem 1.5rem; background: #0066cc; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1rem; }
    .btn:disabled { background: #99bbdd; cursor: not-allowed; }
    .progress { display: none; margin-top: 1rem; }
    .progress-bar { height: 8px; background: #eee; border-radius: 4px; overflow: hidden; }
    .progress-bar div { height: 100%; background: #0066cc; width: 0%; transition: width .3s; }
    .result { margin-top: 1.5rem; display: none; }
    .result a { display: inline-block; padding: .5rem 1rem; background: #28a745; color: white; text-decoration: none; border-radius: 4px; }
    .error { color: #dc3545; margin-top: 1rem; }
    .info { font-size: .9rem; color: #666; margin-top: 1rem; }
  </style>
</head>
<body>
  <h1>📤 Загрузка HTML-визуализации</h1>
  <p>Перетащите сюда файл <code>.html</code> или <code>.htm</code> с готовой визуализацией.</p>
  <p class="info">⚠️ Файл будет доступен по ссылке <strong>24 часа</strong>. Ночью (03:30) папка очищается полностью.</p>

  <div class="drop-zone" id="dropZone">
    <input type="file" id="fileInput" accept=".html,.htm">
    <p>Перетащите файл сюда или <button type="button" class="btn" onclick="document.getElementById('fileInput').click()">выберите файл</button></p>
    <p class="info">Максимальный размер: 50 МБ</p>
  </div>

  <div class="progress" id="progress">
    <div class="progress-bar"><div id="progressFill"></div></div>
    <p id="progressText">Загрузка...</p>
  </div>

  <div class="result" id="result"></div>
  <div class="error" id="error"></div>

  <script>
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const progress = document.getElementById('progress');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');
    const result = document.getElementById('result');
    const error = document.getElementById('error');

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(evt => {
      dropZone.addEventListener(evt, e => { e.preventDefault(); e.stopPropagation(); });
    });
    ['dragenter', 'dragover'].forEach(evt => dropZone.addEventListener(evt, () => dropZone.classList.add('drag')));
    ['dragleave', 'drop'].forEach(evt => dropZone.addEventListener(evt, () => dropZone.classList.remove('drag')));

    dropZone.addEventListener('drop', e => {
      const file = e.dataTransfer.files[0];
      if (file) uploadFile(file);
    });
    fileInput.addEventListener('change', e => {
      if (e.target.files[0]) uploadFile(e.target.files[0]);
    });

    async function uploadFile(file) {
      if (!file.name.toLowerCase().match(/\.(html|htm)$/)) {
        error.textContent = '❌ Только файлы .html или .htm';
        return;
      }
      if (file.size > 50 * 1024 * 1024) {
        error.textContent = '❌ Файл слишком большой (макс. 50 МБ)';
        return;
      }

      error.textContent = '';
      result.style.display = 'none';
      progress.style.display = 'block';
      progressFill.style.width = '0%';
      progressText.textContent = 'Загрузка...';

      const formData = new FormData();
      formData.append('file', file);

      try {
        const xhr = new XMLHttpRequest();
        xhr.upload.addEventListener('progress', e => {
          if (e.lengthComputable) {
            const pct = Math.round((e.loaded / e.total) * 100);
            progressFill.style.width = pct + '%';
            progressText.textContent = `Загрузка: ${pct}%`;
          }
        });
        xhr.addEventListener('load', () => {
          progress.style.display = 'none';
          if (xhr.status === 200) {
            const data = JSON.parse(xhr.responseText);
            result.innerHTML = `
              <p>✅ Файл загружен!</p>
              <a href="${data.url}" target="_blank">${data.url}</a>
              <p class="info">Ссылка действительна 24 часа. Поделитесь ею с преподавателем или одногруппниками.</p>
            `;
            result.style.display = 'block';
          } else {
            const data = JSON.parse(xhr.responseText || '{}');
            error.textContent = '❌ ' + (data.error || `Ошибка ${xhr.status}`);
          }
        });
        xhr.addEventListener('error', () => {
          progress.style.display = 'none';
          error.textContent = '❌ Ошибка сети';
        });
        xhr.open('POST', '/upload/');
        xhr.setRequestHeader('Authorization', 'Basic ' + btoa('opencode:' + prompt('Введите пароль:')));
        xhr.send(formData);
      } catch (e) {
        progress.style.display = 'none';
        error.textContent = '❌ ' + e.message;
      }
    }
  </script>
</body>
</html>
EOF
```

---

## 3. Настройка старого стенда (Caddy) — только порт 4601

```bash
# У deployagent:
cat > ~/.config/caddy/Caddyfile <<'EOF'
{
	auto_https disable_redirects
	default_sni 94.141.97.249
}

https://94.141.97.249:4601 {
	tls internal
	reverse_proxy 127.0.0.1:4600
}
EOF

systemctl --user restart caddy
```

---

## 4. TLS-сертификат для нового стенда (Let's Encrypt на IP)

```bash
# С root:
apt-get install -y certbot
mkdir -p /var/www/acme
certbot certonly --webroot -w /var/www/acme -d 94.141.97.249 \
  --preferred-profile shortlived --agree-tos -m your-email@example.com --non-interactive

mkdir -p /srv/opencode-student/sandbox/edge/certs
cp /etc/letsencrypt/live/94.141.97.249/fullchain.pem /srv/opencode-student/sandbox/edge/certs/
cp /etc/letsencrypt/live/94.141.97.249/privkey.pem /srv/opencode-student/sandbox/edge/certs/
chown -R deployagent:deployagent /srv/opencode-student/sandbox/edge/certs

cat > /usr/local/bin/renew-opencode-cert.sh <<'EOF'
#!/bin/bash
certbot renew --quiet --deploy-hook "cp /etc/letsencrypt/live/94.141.97.249/fullchain.pem /srv/opencode-student/sandbox/edge/certs/ && cp /etc/letsencrypt/live/94.141.97.249/privkey.pem /srv/opencode-student/sandbox/edge/certs/ && docker compose -f /srv/opencode-student/sandbox/docker-compose.yml exec edge nginx -s reload"
EOF
chmod +x /usr/local/bin/renew-opencode-cert.sh

echo '0 */12 * * * root /usr/local/bin/renew-opencode-cert.sh' > /etc/cron.d/opencode-cert-renew
```

---

## 5. Запуск нового стенда

```bash
# От deployagent (после релогина)
cd /srv/opencode-student/sandbox
bash scripts/30-up.sh
bash scripts/50-verify-isolation.sh
bash scripts/40-info.sh
```

---

## 6. Проверка

```bash
docker compose exec -u sandbox sandbox \
  opencode run --model opencode/deepseek-v4.1-flash-free \
  "Какие внешние ресурсы тебе доступны?"
```

Проверка загрузки: откройте `https://94.141.97.249/files/uploads/`, загрузите `.html`, получите ссылку, перейдите — файл скачается.

---

## 7. Итоговая схема доступов

| URL | Что там | Пароль |
|-----|---------|--------|
| `https://94.141.97.249/` | Новый стенд для студентов | `opencode` / `SANDBOX_PASSWORD` |
| `https://94.141.97.249/files/` | Скачивание результатов (`output/`) | Тот же |
| `https://94.141.97.249/files/uploads/` | Страница загрузки HTML | Тот же |
| `https://94.141.97.249:4601/` | Старый стенд (только для вас) | Старый пароль |

---

## 8. Эксплуатация

| Задача | Команда |
|--------|---------|
| Логи | `docker compose -f /srv/opencode-student/sandbox/docker-compose.yml logs -f sandbox` |
| Что режет прокси | `docker compose ... logs egress | grep -i blocked` |
| Перезапуск | `docker compose ... restart sandbox` |
| Сброс папки | `find /srv/opencode-student/workspace -mindepth 1 -delete` |
| Остановка | `docker compose ... down` |
| Проверка сертификата | `openssl x509 -in /srv/opencode-student/sandbox/edge/certs/fullchain.pem -text -noout | grep -A2 Validity` |

---

## 9. Риски и ограничения

1. **Один пароль на всех, общая папка** — студенты видят и могут удалить чужие файлы.
2. **Файлы живут 24 часа** — ночная очистка в 03:30 удаляет всё из `workspace/`.
3. **Бесплатные модели — общая квота** — 20–30 студентов могут получить `429`.
4. **Сертификат Let's Encrypt на IP** — живёт ~6.7 суток, продление обязательно.
5. **gVisor не панацея** — защищает от побега, но не от глупостей агента внутри.
6. **CDN заблокированы** — графики только самодостаточные.

---

## 10. Чек-лист перед выдачей студентам

- [ ] Старый стенд только на `:4601`
- [ ] Новый стенд на `https://94.141.97.249/` (порт 443)
- [ ] TLS сертификат валиден
- [ ] `/files/` отдаёт на скачивание
- [ ] `/files/uploads/` — загрузка работает
- [ ] Изоляция проверена (`scripts/50-verify-isolation.sh`)
- [ ] Ночная очистка работает
- [ ] Квота 60 ГБ работает
- [ ] Пароль задан и не дефолтный
