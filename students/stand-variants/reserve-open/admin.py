#!/usr/bin/env python3
"""Админ-хелпер песочницы: пароль стенда и SSH-ключи прямо из UI.

Агент работает внутри контейнера от root и пишет в смонтированные файлы:

  /host/env             ← /srv/opencode/sandbox/.env          (пароль стенда)
  /host/htpasswd        ← /srv/opencode/sandbox/edge/htpasswd  (basic auth)
  /host/admin           ← /srv/opencode/admin                 (очередь для хоста)
  /host/ssh/authorized_keys ← /home/deployagent/.ssh (только чтение, для отчёта)

Прямо в authorized_keys писать нельзя: sshd требует 600 и владельца, а из
контейнера права не сохранить. Поэтому ключ кладётся в очередь
/host/admin/ssh-keys.append, а root-таймер хоста (opencode-student-keys.path)
дописывает его в файл с правильными правами.

Использование:
  python3 /opt/tools/admin.py show
  python3 /opt/tools/admin.py password <новый-пароль>
  python3 /opt/tools/admin.py ssh-key "ssh-ed25519 AAAA... комментарий"
"""
import base64
import hashlib
import os
import sys

ENV = "/host/env"
HTPASSWD = "/host/htpasswd"
ADMIN = "/host/admin"
KEY_QUEUE = os.path.join(ADMIN, "ssh-keys.append")
RESTART = os.path.join(ADMIN, "restart.request")
AUTH_RO = "/host/ssh/authorized_keys"
LOGIN = "opencode"


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return default


def write(path, data):
    with open(path, "w") as f:
        f.write(data)


def write_atomic(path, data):
    tmp = path + ".tmp"
    write(tmp, data)
    os.replace(tmp, path)


def sha_password(pw):
    # nginx понимает {SHA}<base64(sha1)>; пароль открытым текстом не храним
    return "{SHA}" + base64.b64encode(hashlib.sha1(pw.encode()).digest()).decode()


def show():
    pw = ""
    for line in read(ENV).splitlines():
        if line.startswith("SANDBOX_PASSWORD="):
            pw = line.split("=", 1)[1]
    keys = [l for l in read(AUTH_RO).splitlines() if l.strip() and not l.startswith("#")]
    print("логин:  %s" % LOGIN)
    print("пароль: %s" % (pw or "(не найден)"))
    print("SSH-ключей в authorized_keys: %d" % len(keys))


def set_password(pw):
    if len(pw) < 4:
        sys.exit("пароль короче 4 символов")
    env = read(ENV)
    lines, found = [], False
    for line in env.splitlines():
        if line.startswith("SANDBOX_PASSWORD="):
            lines.append("SANDBOX_PASSWORD=" + pw)
            found = True
        else:
            lines.append(line)
    if not found:
        lines.append("SANDBOX_PASSWORD=" + pw)
    write(ENV, "\n".join(lines) + "\n")
    write(HTPASSWD, "%s:%s\n" % (LOGIN, sha_password(pw)))
    os.makedirs(ADMIN, exist_ok=True)
    write_atomic(RESTART, "restart\n")
    print("пароль изменён: %s / %s" % (LOGIN, pw))
    print("страница /upload/ работает сразу; вход в UI — через ~10 секунд "
          "(перезапуск делает хост)")


def add_ssh_key(key):
    key = key.strip()
    if not key.startswith(("ssh-", "ecdsa-", "sk-", "sk-ssh-")):
        sys.exit("это не похоже на публичный SSH-ключ")
    if key in read(AUTH_RO) or key in read(KEY_QUEUE):
        print("такой ключ уже есть")
        return
    os.makedirs(ADMIN, exist_ok=True)
    with open(KEY_QUEUE, "a") as f:
        f.write(key + "\n")
    print("ключ поставлен в очередь, через пару секунд будет добавлен")
    print("проверка: ssh deployagent@<адрес стенда>")
    print("важно: deployagent на этом стенде имеет sudo без пароля")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "show":
        show()
    elif cmd == "password":
        if len(sys.argv) < 3:
            sys.exit("укажите новый пароль: admin.py password <пароль>")
        set_password(sys.argv[2])
    elif cmd == "ssh-key":
        if len(sys.argv) < 3:
            sys.exit('укажите ключ: admin.py ssh-key "ssh-ed25519 AAAA..."')
        add_ssh_key(sys.argv[2])
    else:
        sys.exit("использование: admin.py show | password <новый> | ssh-key \"<ключ>\"")


if __name__ == "__main__":
    main()
