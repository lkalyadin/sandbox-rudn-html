#!/usr/bin/env python3
"""Архивация неактуальных проектов в БД OpenCode (:4601).

Проекты в OpenCode — это просто папки: запись в таблице `project` создаётся
автоматически при старте сессии в каталоге и НЕ удаляется, если папку убрали.
Отсюда строки вида `/demo/opencode-sandbox/...` (пути с прежнего хоста),
`/tmp/opencode` (старый TMPDIR) и дубли одного и того же пути.

Скрипт делает мягкую архивацию — выставляет `time_archived` (мс). Строка и её
сессии остаются в БД; запись просто уходит из списка проектов и оживает, если
снова открыть эту папку (`resolve()` в OpenCode ставит `time_archived = NULL`).

Безопасность:
  * перед записью делается полный бэкап через sqlite3 backup API (не `cp` —
    в БД активен WAL);
  * проверяется `pragma quick_check`;
  * служебный проект `global` (id = 'global') не трогается никогда;
  * дубли путей сводятся к одной записи — остаётся самая свежая;
  * по умолчанию только показывает план, запись — с `--apply`.

Запуск:
    python3 scripts/archive-projects.py            # план
    python3 scripts/archive-projects.py --apply    # применить
"""

from __future__ import annotations

import argparse
import datetime
import os
import sqlite3
import sys
import time

DB = os.path.expanduser("~/.local/share/opencode/opencode.db")
BACKUP_DIR = os.path.expanduser("~/tmp/opencode-backups")

# Актуальные проекты: всё остальное архивируется.
KEEP = [
    "/home/deployagent/projects/gameconnect",
    "/home/deployagent/projects/students",
    "/home/deployagent/projects/adventuremazes",
    "/home/deployagent/projects/opencode-settings",
]

GLOBAL_ID = "global"


def fmt(ms: int | None) -> str:
    if not ms:
        return "—"
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).strftime("%Y-%m-%d %H:%M")


def norm(path: str | None) -> str:
    if not path:
        return ""
    return os.path.realpath(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="записать изменения в БД")
    ap.add_argument("--db", default=DB)
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"нет файла БД: {args.db}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(args.db, timeout=15)
    conn.row_factory = sqlite3.Row

    rows = [dict(r) for r in conn.execute(
        "select id, worktree, name, time_created, time_updated, time_archived "
        "from project order by time_updated desc"
    )]
    print(f"всего проектов в БД: {len(rows)}\n")

    keep_set = {norm(p) for p in KEEP}
    now_ms = int(time.time() * 1000)

    keep_ids: set[str] = set()
    to_archive: list[tuple[dict, str]] = []

    # 1) служебный global — всегда оставляем
    by_path: dict[str, list[dict]] = {}
    for r in rows:
        if r["id"] == GLOBAL_ID:
            keep_ids.add(r["id"])
            continue
        by_path.setdefault(norm(r["worktree"]), []).append(r)

    # 2) актуальные пути: оставляем самую свежую запись, дубли — в архив
    for path, group in by_path.items():
        if path in keep_set:
            group.sort(key=lambda r: r["time_updated"] or 0, reverse=True)
            keep_ids.add(group[0]["id"])
            for dup in group[1:]:
                if dup["time_archived"]:
                    continue  # уже в архиве (повторный прогон)
                to_archive.append((dup, "дубль актуального пути"))

    # 3) всё остальное — неактуальное
    for path, group in by_path.items():
        if path in keep_set:
            continue
        for r in group:
            if r["time_archived"]:
                continue  # уже в архиве
            to_archive.append((r, "неактуальный путь"))

    if not to_archive:
        print("нечего архивировать — всё уже в порядке")
        return 0

    print("к архивации:")
    for r, why in to_archive:
        print(f"  {r['worktree']}")
        print(f"     id={r['id'][:12]}…  updated={fmt(r['time_updated'])}  причина: {why}")

    print("\nостаются:")
    for r in rows:
        if r["id"] in keep_ids and not r["time_archived"]:
            print(f"  {r['worktree']:<52} (id={r['id'][:12]}…)")

    if not args.apply:
        print("\nэто план. применить: --apply")
        return 0

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d-%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"opencode-{stamp}.db")
    bck = sqlite3.connect(backup_path)
    with bck:
        conn.backup(bck)
    bck.close()
    os.chmod(backup_path, 0o600)

    check = conn.execute("pragma quick_check").fetchone()[0]
    print(f"\nбэкап: {backup_path} ({os.path.getsize(backup_path) / 1e6:.1f} МБ)")
    print(f"quick_check бэкапа-источника: {check}")
    if check != "ok":
        print("БД не в порядке — запись отменена", file=sys.stderr)
        return 1

    with conn:
        for r, _ in to_archive:
            conn.execute("update project set time_archived = ? where id = ?", (now_ms, r["id"]))
    conn.close()

    print(f"заархивировано записей: {len(to_archive)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
