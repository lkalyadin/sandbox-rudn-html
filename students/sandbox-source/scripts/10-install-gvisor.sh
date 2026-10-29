#!/usr/bin/env bash
# Ставит gVisor (runsc) и регистрирует его как docker runtime.
#
# Зачем это на демо-стенде: контейнер — не виртуальная машина. Если студент
# найдёт kernel-exploit, он получит root на хосте и уронит стенд для всей
# группы. gVisor вставляет между приложением и ядром собственное ядро на
# userspace, и такой сценарий становится на порядок сложнее.
#
# Стоимость: операции с файлами чуть медленнее. Для демо это незаметно.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  if sudo -n true 2>/dev/null; then
    exec sudo -E bash "$0" "$@"
  fi
  echo "Нужен root. Запустите: sudo $0" >&2
  exit 1
fi

if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q 'runsc'; then
  echo "runsc уже зарегистрирован — ничего не делаю"
  exit 0
fi

echo "==> Ставлю пакет runsc"
apt-get update -qq
apt-get install -y -qq curl gnupg ca-certificates

curl -fsSL https://gvisor.dev/archive.key \
  | gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" \
  > /etc/apt/sources.list.d/gvisor.list

apt-get update -qq
apt-get install -y -qq runsc

echo "==> Регистрирую runtime в Docker"
# runsc install правит /etc/docker/daemon.json. Сохраняем копию: там могут
# быть ваши настройки (логирование, реестры, userns).
if [ -f /etc/docker/daemon.json ]; then
  cp -n /etc/docker/daemon.json "/etc/docker/daemon.json.backup.$(date +%s)"
  echo "    бэкап: /etc/docker/daemon.json.backup.*"
fi
runsc install

echo "==> Перезапускаю Docker"
systemctl restart docker
sleep 3

if docker info --format '{{json .Runtimes}}' | grep -q 'runsc'; then
  echo "==> Готово. runsc: $(runsc --version | head -1)"
  echo
  echo "Проверка (должно быть 'GenuineIntel'/'gVisor' в kernel, т.е. 4.4.0):"
  echo "  docker run --rm --runtime=runsc alpine uname -r"
else
  echo "!! runsc не появился в docker info. Смотрите: journalctl -u docker -n 50" >&2
  exit 1
fi
