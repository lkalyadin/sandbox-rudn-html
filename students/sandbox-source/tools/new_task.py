#!/usr/bin/env python3
"""Создаёт уникальную папку задачи в общей рабочей папке стенда.

Зачем: все студенты работают в одном /work, и без разделения они перезаписывают
файлы друг друга (одинаковые output/dashboard.html). Поэтому каждая задача
живёт в своей папке: /work/sessions/<уникальный id>.

Запуск (первый шаг любой задачи):
    python3 /opt/tools/new_task.py

Печатает путь к созданной папке:
    /work/sessions/task-20261027-160512-a1b2

Запускается через python3, потому что правило песочницы разрешает `python3 *`
без вопросов, а `sh <скрипт>` уходит в «спросить разрешение у студента».
Папка никогда не переиспользуется: повторный вызов создаст новую.
"""

import os
import secrets
import sys
from datetime import datetime, timezone

WORKSPACE = os.environ.get("SANDBOX_WORKSPACE", "/work")


def main() -> int:
    prefix = os.environ.get("TASK_PREFIX", "task")
    session_id = os.environ.get("OPENCODE_SESSION_ID")
    if session_id:
        ident = f"{prefix}-{session_id}"
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        ident = f"{prefix}-{stamp}-{secrets.token_hex(2)}"

    directory = os.path.join(WORKSPACE, "sessions", ident)
    os.makedirs(os.path.join(directory, "output"), exist_ok=True)

    readme = os.path.join(directory, "README.txt")
    if not os.path.exists(readme):
        with open(readme, "w", encoding="utf-8") as fh:
            fh.write(
                "Папка одной задачи. Здесь лежат скрипты, промежуточные файлы\n"
                "и результат. Файлы из output/ открываются по ссылке\n"
                "/files/sessions/<эта папка>/output/<файл>.\n"
                "Папка удаляется ночной очисткой стенда.\n"
            )

    print(directory)
    return 0


if __name__ == "__main__":
    sys.exit(main())
