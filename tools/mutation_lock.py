#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""ЛОК МУТАЦИОННЫХ ИНСТРУМЕНТОВ — НА РАБОЧЕЕ ДЕРЕВО (`#482`).

ЗАЧЕМ. `tools/canfail.py` и `tools/mutate_zig.py` оба ПРАВЯТ ИСХОДНИКИ, поэтому
обязаны исключать друг друга — иначе свидетельства становятся ложными (дефект
`#88b`: два разных механизма блокировки не мешали прогонам идти внахлёст).
Раньше у них был ОДИН ЖЁСТКИЙ путь `/tmp/kern_mutation.lock`, и это дало
побочный эффект: полный мутационный свип (40 минут) блокировал `canfail`, то
есть любую проверку гейтов, даже если она шла про СОВЕРШЕННО ДРУГОЙ код.

ЧТО ИЗМЕНЕНО. Лок защищает РАБОЧЕЕ ДЕРЕВО, а не «процесс на машине»: имя
выводится из абсолютного пути корня. Одно дерево — один лок (`#88b` цел:
`canfail` и `mutate_zig` в одном дереве по-прежнему не идут внахлёст), разные
деревья (git worktree) — разные локи, и фоновый свип больше не блокирует
проверки в основном дереве.

МЕХАНИЗМ: `fcntl.flock` — ядро снимает его даже при SIGKILL, поэтому класс
«мёртвый замок блокирует навсегда» (дефект `#50`) невозможен по построению.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK_DIR = "/tmp"


def lock_path(root: str | Path | None = None) -> str:
    """Путь лока ДЛЯ ЭТОГО дерева (детерминированно от абсолютного пути)."""
    r = str(Path(root or ROOT).resolve())
    tag = hashlib.sha256(r.encode("utf-8")).hexdigest()[:12]
    return f"{LOCK_DIR}/kern_mutation.{tag}.lock"


def acquire(root: str | Path | None = None):
    """Взять лок дерева. Возвращает дескриптор (держать!) либо строку `BUSY`."""
    try:
        import fcntl
    except ImportError:      # pragma: no cover - не POSIX
        return None
    path = lock_path(root)
    f = open(path, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        f.close()
        return "BUSY"
    f.write(f"pid={os.getpid()}\nroot={Path(root or ROOT).resolve()}\n")
    f.flush()
    return f


def _selftest() -> int:
    """Невакуумность: тот же корень — BUSY; ДРУГОЙ корень — свободен."""
    fails = 0

    def check(name: str, ok: bool, detail: str) -> None:
        nonlocal fails
        fails += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {name}: {detail}")

    import tempfile
    a = Path(tempfile.mkdtemp(prefix="lockA_"))
    b = Path(tempfile.mkdtemp(prefix="lockB_"))
    check("пути локов РАЗНЫЕ для разных деревьев", lock_path(a) != lock_path(b),
          f"{Path(lock_path(a)).name} vs {Path(lock_path(b)).name}")

    h1 = acquire(a)
    check("первый захват", h1 not in (None, "BUSY"), f"fd={bool(h1)}")
    h2 = acquire(a)
    check("ПОВТОРНЫЙ захват того же дерева — BUSY (#88b цел)", h2 == "BUSY", f"{h2}")
    h3 = acquire(b)
    check("ДРУГОЕ дерево НЕ блокируется (#482)", h3 not in (None, "BUSY"),
          f"fd={bool(h3)}")
    for h in (h1, h3):
        try:
            if h:
                h.close()
        except OSError as e:      # класс #198/#457: закрытие fd может упасть по ОС,
            print(f"  [i] закрытие лока: {e}")   # программные ошибки НЕ глушим
    h4 = acquire(a)
    check("после закрытия лок снова свободен", h4 not in (None, "BUSY"), f"fd={bool(h4)}")
    if h4:
        h4.close()
    print(f"[{'FAIL' if fails else 'OK'}] mutation-lock: провалов {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(_selftest())
