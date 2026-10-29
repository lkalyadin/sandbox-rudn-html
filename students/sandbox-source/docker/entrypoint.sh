#!/bin/sh
# Точка входа песочницы: готовим каталоги состояния и поднимаем сервер OpenCode.
#
# Задача — сделать так, чтобы у студента был ровно ОДИН вход
# (логин `opencode` + пароль из .env), а не цепочка паролей.
#
# Написан на POSIX sh намеренно: базовый образ OpenCode может быть как
# Debian, так и Alpine. Не используйте здесь bash-измы.
set -eu

log() { printf '[sandbox] %s\n' "$*" >&2; }

: "${OPENCODE_SERVER_PASSWORD:?OPENCODE_SERVER_PASSWORD не задан — задайте SANDBOX_PASSWORD в .env}"

# Тома могут быть пустыми при первом запуске.
mkdir -p \
  "${HOME}/.config/opencode" \
  "${HOME}/.local/share/opencode" \
  "${HOME}/.local/state/opencode" \
  "${HOME}/.cache/opencode"

# ── Диагностика окружения ────────────────────────────────────────────────────
# Если в UI «нет доступных моделей» — смотрим сюда и в лог egress-прокси:
# скорее всего домен каталога моделей не в allowlist.
log "opencode: $(opencode --version 2>/dev/null || echo 'не найден')"
log "kernel  : $(uname -r) (gVisor отдаёт 4.4.0)"
log "egress  : ${HTTPS_PROXY:-не задан} NO_PROXY=${NO_PROXY:-не задан}"

# ── PUBLIC_URL ───────────────────────────────────────────────────────────────
# Навык смонтирован read-only, поэтому НЕ мутируем его (раньше `sed -i` ронял
# контейнер в рестарт-цикл). Публичный URL уже указан в SKILL.md. Если он
# меняется — правьте SKILL.md и .env вместе; здесь только диагностика.
if [ -n "${PUBLIC_URL:-}" ]; then
  if [ -f /etc/opencode/skills/economist-sandbox/SKILL.md ]; then
    log "PUBLIC_URL=${PUBLIC_URL} (навык только для чтения, не изменяется)"
  else
    log "ВНИМАНИЕ: PUBLIC_URL=${PUBLIC_URL}, но SKILL.md не найден по ожидаемому пути"
  fi
fi

# ── Пароль единственного входа ───────────────────────────────────────────────
# Проверено на живом сервере (см. docs/previous-deployment-runbook.md, §3.3):
# v2 всегда требует пароль и берёт его из OPENCODE_SERVER_PASSWORD.
# Без переменной пароль генерируется и печатается в лог.
# Логин всегда `opencode`. Директиву `opencode service set password` не
# используем: она не нужна, а в foreground-режиме бессмысленна.
log "пароль сервера взят из OPENCODE_SERVER_PASSWORD (логин: opencode)"

# ── Старт ────────────────────────────────────────────────────────────────────
# --print-logs: логи идут в stdout, то есть в `docker compose logs`.
#
# Запускаем через tini (если он есть): он перехватывает сигналы и, главное,
# забирает «осиротевшие» процессы. Без него осиротевшие дочерние процессы
# chromium (а агент запускает браузер для проверки страниц) превращаются в
# зомби и копятся до лимита pids_limit.
log "запускаю opencode serve на 0.0.0.0:4096"
if command -v tini >/dev/null 2>&1; then
  exec tini -- opencode serve --hostname 0.0.0.0 --port 4096 --print-logs
fi
exec opencode serve --hostname 0.0.0.0 --port 4096 --print-logs
