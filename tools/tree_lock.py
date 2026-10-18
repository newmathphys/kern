#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
"""ЕДИНЫЙ ЗАМОК ДЛЯ ВСЕГО, ЧТО ПАТЧИТ РАБОЧЕЕ ДЕРЕВО.

ЗАЧЕМ (дефект #126). `tools/mutate_zig.py` и `tools/canfail.py` УЖЕ брали общий
`flock` на `/tmp/kern_mutation.lock`. Но ad-hoc скрипты проверки мутаций
(написанные «на бегу» в /tmp) этот замок НЕ брали — два таких скрипта
одновременно правили ОДИН файл, восстанавливая его каждый из своей копии.
Гонка ОСТАВИЛА ДВЕ МУТАЦИИ В ДЕРЕВЕ (`if (n != 0)` и `if (n == 3)`).

ПРАВИЛО: любой скрипт, который пишет в `src/`, `tools/` или `docs/` рабочего
дерева, ОБЯЗАН брать этот замок. Ядро снимает `flock` даже при SIGKILL
(в отличие от файла-флага — дефект #50).

Использование:

    from tree_lock import tree_lock
    with tree_lock("мой скрипт"):
        ...правки дерева...

При занятом замке: печатает причину и выходит с rc = 2, НЕ ТРОНУВ НИ ОДНОГО
ФАЙЛА (проверено тестом `--selftest`).
"""
from __future__ import annotations

import contextlib
import os
import sys

LOCK_PATH = "/tmp/kern_mutation.lock"


@contextlib.contextmanager
def tree_lock(what: str = "скрипт"):
    """Эксклюзивный доступ к рабочему дереву. rc=2 при занятом замке."""
    try:
        import fcntl
    except ImportError:  # не POSIX — блокировки нет
        yield None
        return
    f = open(LOCK_PATH, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        print(f"[LOCKED] Другой экземпляр ({what}) уже модифицирует дерево!")
        print("         Замок: " + LOCK_PATH + " — дождитесь завершения.")
        print("         НИ ОДИН ФАЙЛ НЕ ИЗМЕНЁН.")
        sys.exit(2)
    try:
        yield f
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def _selftest() -> int:
    """ДОКАЗАТЕЛЬСТВО взаимного исключения: второй держатель получает rc=2.

    Проверяем в ОТДЕЛЬНОМ процессе, что при УЖЕ удерживаемом замке попытка
    взять его снова завершается rc=2 и не трогает файлы.
    """
    import subprocess
    import tempfile
    from pathlib import Path

    probe = Path(tempfile.mkdtemp()) / "probe.txt"
    probe.write_text("нетронуто", encoding="utf-8")
    code = (
        "import sys; sys.path.insert(0, 'tools');\n"
        "from tree_lock import tree_lock;\n"
        "from pathlib import Path;\n"
        "p = Path(sys.argv[1]);\n"
        "with tree_lock('второй экземпляр'):\n"
        "    p.write_text('ИЗМЕНЁН', encoding='utf-8')\n"
    )
    with tree_lock("selftest-держатель"):
        r = subprocess.run([sys.executable, "-c", code, str(probe)],
                           capture_output=True, text=True, timeout=60)
    unchanged = probe.read_text(encoding="utf-8") == "нетронуто"
    print(f"  второй экземпляр: rc={r.returncode} (ожидается 2)")
    print(f"  файл НЕ тронут:  {unchanged}")
    print(f"  сообщение:       {r.stdout.strip().splitlines()[0] if r.stdout.strip() else '(нет)'}")
    ok = r.returncode == 2 and unchanged
    # После освобождения замок обязан снова браться.
    with tree_lock("после освобождения"):
        pass
    print(f"  замок освобождается и берётся снова: True")
    print("[OK] взаимное исключение РАБОТАЕТ" if ok else "[!] ЗАМОК НЕ РАБОТАЕТ")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
