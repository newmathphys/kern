#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the KERN Source License (see LICENSE).
"""ГЕЙТ ШАГА 7 ПЛАНА: ЗАМОК МУТАЦИЙ ХАРНЕССА.

ЗАЧЕМ. `tools/canfail.py` пишет ПРЯМО В РАБОЧИЕ ФАЙЛЫ, и однажды саботаж ушёл в
`main` (`3067a1b`): CI его поймал, но уже ПОСЛЕ пуша. flock защищает от второго
прогона, но НЕ от коммита, поэтому харнесс оставляет видимый след —
`.git/CANFAIL_ACTIVE_MUTATION` с PID, — а этот гейт его читает.

ТРИ состояния, и каждое НАЗВАНО, а не сведено к «красный/зелёный»:
  * маркера нет            -> OK (мутаций не в полёте);
  * маркер есть, PID ЖИВ   -> FAIL: мутация в полёте, коммитить НЕЛЬЗЯ;
  * маркер есть, PID МЁРТВ -> FAIL: замок остался после аварии (урок #50) —
                              удалить осознанно: rm .git/CANFAIL_ACTIVE_MUTATION.

ГРАНИЦА: гейт ничего не говорит о прогоне, который ещё не начался, и НЕ заменяет
flock (взаимное исключение делает ядро).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKER = ROOT / ".git" / "CANFAIL_ACTIVE_MUTATION"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def verdict(marker_exists: bool, pid, alive: bool) -> tuple:
    """ЧИСТАЯ функция вердикта — её и проверяет мета-тест."""
    if not marker_exists:
        return True, "маркера нет: мутаций в полёте не зафиксировано"
    if pid is None:
        return False, "маркер есть, но PID не разобран — замок повреждён"
    if alive:
        return False, (f"МУТАЦИЯ В ПОЛЁТЕ: процесс {pid} правит рабочие файлы. "
                       f"Коммитить НЕЛЬЗЯ — дождитесь конца прогона canfail")
    return False, (f"ЗАМОК ОСТАЛСЯ ПОСЛЕ АВАРИИ (PID {pid} мёртв). Удалите файл "
                   f"осознанно: rm .git/CANFAIL_ACTIVE_MUTATION")


def check() -> int:
    exists = MARKER.exists()
    pid = None
    if exists:
        try:
            m = re.search(r"pid=(\d+)", MARKER.read_text(encoding="utf-8",
                                                        errors="replace"))
            pid = int(m.group(1)) if m else None
        except OSError:
            pid = None
    ok, why = verdict(exists, pid, _pid_alive(pid) if pid is not None else False)
    print(f"[{'OK' if ok else 'FAIL'}] {why}")
    return 0 if ok else 1


def selftest() -> int:
    cases = [
        ((False, None, False), True, "маркера нет"),
        ((True, 1, True), False, "мутация в полёте (PID жив)"),
        ((True, 999999, False), False, "замок остался после аварии (PID мёртв)"),
        ((True, None, False), False, "PID не разобран"),
    ]
    bad = 0
    for args, want, name in cases:
        got, why = verdict(*args)
        mark = "OK" if got == want else "ПРОВАЛ"
        if got != want:
            bad += 1
        print(f"  [{mark}] {name}: verdict={got} ({why[:62]})")
    print(f"[{'OK' if bad == 0 else 'FAIL'}] mutation-lock selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    return check()


if __name__ == "__main__":
    sys.exit(main())
