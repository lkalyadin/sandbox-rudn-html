ARG OPENCODE_IMAGE=ghcr.io/anomalyco/opencode:2.0.32
FROM ${OPENCODE_IMAGE}

USER root

# Браузер для самопроверки страницы агентом (см. /opt/viz/check_page.py).
# Без него агент выдаёт ссылку вслепую: страница может не отрисоваться,
# а студент видит пустую вкладку. Отключается: --build-arg WITH_BROWSER=false
ARG WITH_BROWSER=true

RUN set -eux; \
    if command -v apt-get >/dev/null 2>&1; then \
        apt-get update; \
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            ca-certificates git python3 python3-pip python3-venv sqlite3 \
            jq less nano curl tini; \
        rm -rf /var/lib/apt/lists/*; \
    elif command -v apk >/dev/null 2>&1; then \
        apk add --no-cache ca-certificates git python3 py3-pip sqlite jq less nano curl tini; \
    else \
        echo "!! Неизвестный пакетный менеджер в базовом образе" >&2; \
        exit 1; \
    fi

# Браузер — отдельным слоем: пакет тяжёлый (~660 МБ), и так его не приходится
# качать заново при правках других слоёв.
RUN set -eux; \
    if [ "${WITH_BROWSER}" != "true" ]; then echo "браузер не ставим (WITH_BROWSER=${WITH_BROWSER})"; exit 0; fi; \
    if command -v apt-get >/dev/null 2>&1; then \
        apt-get update; \
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            chromium fonts-dejavu-core; \
        rm -rf /var/lib/apt/lists/*; \
    elif command -v apk >/dev/null 2>&1; then \
        apk add --no-cache chromium-headless-shell fontconfig ttf-dejavu; \
    fi; \
    command -v chromium-headless-shell || command -v chromium

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
COPY docker/check_page.py /opt/viz/check_page.py
COPY docker/screenshot.py /opt/viz/screenshot.py
# Kit — готовый конструктор дашборда: движок, темы, сборщик, примеры и
# автопроверка интерактива. См. /opt/viz/kit/README.md.
COPY docker/kit /opt/viz/kit
# Копия текста навыка рядом с kit: конструктор встраивает его в страницу (§7).
# Смонтированный /etc/opencode/skills/... имеет приоритет — см. dashboard.py.
COPY skills/economist-sandbox/SKILL.md /opt/viz/kit/SKILL.md
RUN chmod 644 /opt/viz/inline_chart.py /opt/viz/check_page.py /opt/viz/screenshot.py \
    && chmod -R a+rX /opt/viz/kit

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
