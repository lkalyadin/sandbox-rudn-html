# Песочница для демо-стенда.
#
# База — официальный образ OpenCode (тег задаётся в .env). Поверх ставим только
# то, что нужно студентам-экономистам для работы с данными: python, pandas,
# matplotlib. Всё остальное делает сам OpenCode.
#
# ВАЖНО: на этапе сборки у контейнера ЕСТЬ интернет (это build, а не run).
# Во время работы стенда интернета не будет — только egress-прокси.
#
# Образ собирается «защищённо»: логика ниже сама определяет пакетный менеджер,
# потому что точная база официального образа может отличаться между версиями.

ARG OPENCODE_IMAGE=ghcr.io/anomalyco/opencode:2.0.0
FROM ${OPENCODE_IMAGE}

USER root

# ── Пакеты для дата-анализа ──────────────────────────────────────────────────
# Делаем это до создания пользователя, чтобы не тащить sudo в рантайм.
RUN set -eux; \
    if command -v apt-get >/dev/null 2>&1; then \
        apt-get update; \
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            ca-certificates git python3 python3-pip python3-venv sqlite3 \
            jq less nano; \
        rm -rf /var/lib/apt/lists/*; \
    elif command -v apk >/dev/null 2>&1; then \
        apk add --no-cache ca-certificates git python3 py3-pip sqlite jq less nano; \
    else \
        echo "!! Неизвестный пакетный менеджер в базовом образе. Установите" >&2; \
        echo "!! python3 и git вручную и уберите этот блок." >&2; \
        exit 1; \
    fi

# ── Дата-стек ────────────────────────────────────────────────────────────────
# --break-system-packages нужен на Debian/Ubuntu 24.04+ (PEP 668).
RUN set -eux; \
    pip3 install --no-cache-dir --break-system-packages \
        pandas numpy matplotlib openpyxl 2>/dev/null \
    || pip3 install --no-cache-dir pandas numpy matplotlib openpyxl

# ── Пользователь песочницы ───────────────────────────────────────────────────
# uid 1000 фиксирован: он же указан в docker-compose (user: "1000:1000").
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
    chown -R "${SANDBOX_UID}:${SANDBOX_GID}" /home/sandbox /work

# ── Guardrails и точка входа ─────────────────────────────────────────────────
COPY config/opencode.json /etc/opencode/opencode.json
COPY docker/entrypoint.sh /usr/local/bin/sandbox-entrypoint.sh
RUN chmod 0755 /usr/local/bin/sandbox-entrypoint.sh

# Напоминание для будущего себя: это контейнер-песочница, не прод.
LABEL org.opencontainers.image.title="opencode-sandbox" \
      org.opencontainers.image.description="Демо-стенд OpenCode для студентов: изолированная песочница без выхода в интернет"

USER ${SANDBOX_UID}:${SANDBOX_GID}
WORKDIR /work

EXPOSE 4096

ENTRYPOINT ["/usr/local/bin/sandbox-entrypoint.sh"]
