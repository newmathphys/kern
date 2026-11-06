#!/usr/bin/env python3
"""ЕДИНЫЙ ШЛЮЗ ЗАПУСКА ПОДПРОЦЕССОВ (#477): таймаут ОБЯЗАТЕЛЕН, решатель — в PATH.

ЗАЧЕМ. Класс дефектов «подпроцесс без таймаута/лимита» выстрелил уже ТРИЖДЫ:
`#464` (таймаут решателя ронял инструмент и рождал сироту в снимке), `#466`
(`z3` не в PATH -> молчаливые SKIP), `#470` (потолок памяти отсутствовал,
`kernc prove` рос до 5.4 ГБ). ИЗМЕРЕНО `make spawn-check`: **170** вызовов
`subprocess.*` в `tools/*.py`, из них **51 без `timeout=`** — то есть 51 место,
где зависший бинарник вешает проверку НАВСЕГДА и без причины.

ЗДЕСЬ — правильный способ. Новый код обязан звать `spawn.run(...)`, а не
`subprocess` напрямую: тогда таймаут есть ВСЕГДА (по умолчанию), путь к `z3`
добавляется из единого источника правды (`z3bin.find_z3`, урок #353), а исход
называется кодом (`124` таймаут, `125` лимит памяти), а не трейсбеком.
Ратчет `spawn-check` следит, чтобы число «голых» вызовов НЕ РОСЛО.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

DEFAULT_TIMEOUT = 900          # секунд; НИ ОДИН вызов не бывает без него
DEFAULT_MEM_MB = 4096          # потолок адресного пространства на подпроцесс
RC_TIMEOUT = 124
RC_MEMORY = 125


def _limiter(mem_mb: int | None):
    """`preexec_fn`: RLIMIT_AS в ДОЧЕРНЕМ процессе (наследуется внуками)."""
    try:
        import resource
    except ImportError:      # pragma: no cover - не-POSIX
        return None
    if mem_mb is None:
        return None
    cap = mem_mb * 1024 * 1024

    def _set() -> None:      # pragma: no cover - выполняется в ребёнке
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))

    return _set


def env_with_solver() -> dict[str, str]:
    """Окружение с каталогом `z3` в `PATH` (единый источник — `z3bin.find_z3`)."""
    env = dict(os.environ)
    try:
        from z3bin import find_z3
        z3 = find_z3()
    except Exception:        # pragma: no cover - z3bin отсутствует
        z3 = None
    if z3:
        env["PATH"] = str(Path(z3).parent) + os.pathsep + env.get("PATH", "")
    return env


def run(cmd: list[str], timeout: int = DEFAULT_TIMEOUT, mem_mb: int | None = DEFAULT_MEM_MB,
        cwd: str | Path | None = None) -> tuple[int, str]:
    """Запустить команду БЕЗОПАСНО. Возвращает `(rc, объединённый вывод)`.

    `rc` в терминах вызывающего: `124` — таймаут, `125` — исчерпан лимит памяти
    (в т.ч. смерть по сигналу `SIGSEGV/SIGABRT/SIGKILL`), иначе код процесса.
    """
    try:
        p = subprocess.run(cmd, cwd=str(cwd or ROOT), capture_output=True, text=True,
                           timeout=timeout, env=env_with_solver(),
                           preexec_fn=_limiter(mem_mb))
    except subprocess.TimeoutExpired:
        return RC_TIMEOUT, f"[!] ТАЙМАУТ {timeout} с — исход НЕ вердикт (#477)"
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        low = out.lower()
        if any(s in low for s in ("out of memory", "outofmemory", "memoryerror",
                                  "cannot allocate memory")):
            return RC_MEMORY, f"[!] ЛИМИТ ПАМЯТИ {mem_mb} МБ исчерпан (#477)\n{out}"
        if p.returncode < 0:
            _sig = {4: "SIGILL", 6: "SIGABRT", 9: "SIGKILL", 11: "SIGSEGV"}.get(-p.returncode,
                                                                               f"signal {-p.returncode}")
            return RC_MEMORY, f"[!] ПАДЕНИЕ ПО СИГНАЛУ {_sig} (#477)\n{out}"
    return p.returncode, out


def _selftest() -> int:
    """Три исхода НАСТОЯЩИМИ подпроцессами: норма / таймаут / лимит памяти.

    Без этого `spawn.run` был бы «правильным советом», который никто не
    проверял: таймаут мог бы не срабатывать, а код возврата — теряться.
    """
    fails = 0

    def check(name: str, ok: bool, detail: str) -> None:
        nonlocal fails
        fails += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {name}: {detail}")

    rc, out = run([sys.executable, "-c", "print('hi')"], timeout=60, mem_mb=512)
    check("A норма", rc == 0 and "hi" in out, f"rc={rc}")

    rc, out = run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=2,
                  mem_mb=512)
    check("B таймаут", rc == RC_TIMEOUT and "ТАЙМАУТ" in out, f"rc={rc}")

    rc, out = run([sys.executable, "-c", "x = bytearray(2*1024**3)"], timeout=120,
                  mem_mb=64)
    check("C лимит памяти", rc == RC_MEMORY, f"rc={rc}")

    rc, out = run(["sh", "-c", "kill -SEGV $$"], timeout=60, mem_mb=512)
    check("D сигнал", rc == RC_MEMORY and "SIGSEGV" in out, f"rc={rc}")

    rc, out = run(["sh", "-c", "exit 7"], timeout=60, mem_mb=512)
    check("E чужой код не подменяется", rc == 7, f"rc={rc}")

    print(f"[{'FAIL' if fails else 'OK'}] spawn: провалов {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(_selftest())
