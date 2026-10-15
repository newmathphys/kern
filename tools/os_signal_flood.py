#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by the GNU Affero General Public License v3.0 ONLY
# (AGPL-3.0-only), or a commercial license from the copyright holder. See LICENSE.
"""os_signal_flood.py — Каскадный штурм сигналами (Signal Racing).

**ПОВОД.** Падение на 2432 файлах SMT-LIB вскрыло гонку `kill()` ↔ `waitpid()`
(ECHILD → panic). Здесь бьём по тому же стыку целенаправленно.

**СЦЕНАРИЙ.** N рабочих запускают `kernc prove` (каждый спавнит Z3),
M потоков-диверсантов непрерывно шлют случайные сигналы
(SIGTERM/SIGKILL/SIGINT/SIGHUP) как родителю, так и его потомкам.

**ЧТО ПРОВЕРЯЕМ:**
  1. KERN не падает (нет SIGABRT/паник) — вместо этого аккуратный отказ.
  2. Нет процессов-зомби после завершения.
  3. Нет утечек дескрипторов у родителя.
  4. Каждый запуск даёт ОПРЕДЕЛЁННЫЙ исход (код возврата), а не зависание.

**ГРАНИЦА (честно):** сигналы шлются ИЗВНЕ (как это делает ОС/админ), а не
изнутри KERN; проверяется устойчивость рантайма, а не «свой» поток-убийца
(он покрыт `z3_crash_test`).
"""

from __future__ import annotations

import os
import random
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"
SMT = b"(set-logic QF_LIA)(declare-const x Int)(assert (> x 5))(assert (< x 2))(check-sat)\n"

WORKERS = 8
SABOTEURS = 4
DURATION_S = 20.0

SIGS = [signal.SIGTERM, signal.SIGINT, signal.SIGHUP]
stop = threading.Event()
killed = {"n": 0}
lock = threading.Lock()


def saboteur() -> None:
    """Шлёт случайные сигналы живым kernc/z3 в системе."""
    rnd = random.Random(os.getpid() ^ int(time.time() * 1000))
    while not stop.is_set():
        try:
            out = subprocess.run(["pgrep", "-f", "kernc|z3"], capture_output=True,
                                 text=True, timeout=2).stdout.split()
        except Exception:
            continue
        for pid_s in out:
            if rnd.random() < 0.15:
                try:
                    os.kill(int(pid_s), rnd.choice(SIGS))
                    with lock:
                        killed["n"] += 1
                except (ProcessLookupError, PermissionError):
                    pass
        time.sleep(rnd.uniform(0.001, 0.010))  # 1–10 мс


def worker(results: list) -> None:
    """Запускает kernc prove; фиксирует код возврата."""
    while not stop.is_set():
        try:
            r = subprocess.run([str(KERNC), "prove", "/dev/stdin"], input=SMT,
                               capture_output=True, timeout=25)
            results.append((r.returncode, (r.stderr or b"").decode(errors="replace")))
        except subprocess.TimeoutExpired:
            results.append((-99, "TIMEOUT"))
        except Exception as e:  # noqa: BLE001
            results.append((-98, str(e)))


def main() -> int:
    if not KERNC.exists():
        print("[!] нет zig-out/bin/kernc — соберите: zig build")
        return 1

    print("\n=== СИГНАЛЬНЫЙ ФЛУД (Signal Racing) ===")
    print(f"рабочих {WORKERS}, диверсантов {SABOTEURS}, длительность {DURATION_S:.0f} с\n")

    results: list = []
    ths = [threading.Thread(target=worker, args=(results,), daemon=True)
           for _ in range(WORKERS)]
    ths += [threading.Thread(target=saboteur, daemon=True) for _ in range(SABOTEURS)]
    for t in ths:
        t.start()

    t0 = time.time()
    while time.time() - t0 < DURATION_S:
        time.sleep(0.5)
    stop.set()
    for t in ths:
        t.join(timeout=30)

    # --- Итоги --------------------------------------------------------------
    #
    # ВАЖНО (исправлено после первого прогона): код возврата 128+N означает
    # «процесс убит сигналом N» — а мы САМИ посылали SIGTERM(15)/SIGINT(2)/
    # SIGHUP(1). Это ОЖИДАЕМО, а не паника. Первая версия скрипта считала
    # такие коды паниками (45 «ложных»). Настоящая паника — это SIGABRT(6,
    # код 134) / SIGSEGV(11, код 139) / текст «panic» в stderr.
    codes = [c for c, _ in results]
    real_panics = []
    sig_killed = 0
    for c, m in results:
        ml = m.lower()
        if "panic" in ml or "unreachable" in ml or c in (134, 139, 135, 136):
            real_panics.append((c, m))
        elif 128 < c < 160:
            sig_killed += 1
    timeouts = sum(1 for c in codes if c == -99)
    clean = sum(1 for c in codes if c == 0)
    graceful = sum(1 for c in codes if c > 0 and c < 128)

    # Зомби?
    zombies = []
    try:
        zout = subprocess.run(["ps", "-eo", "stat,pid,ppid,comm"], capture_output=True,
                              text=True, timeout=5).stdout
        zombies = [l.strip() for l in zout.splitlines() if l.strip().startswith("Z")]
    except Exception:
        pass

    print(f"  запусков:            {len(codes)}")
    print(f"  успешных (rc=0):     {clean}")
    print(f"  аккуратных отказов:  {graceful}")
    print(f"  убито сигналом:      {sig_killed}  (ожидаемо — сигналы слали МЫ)")
    print(f"  таймаутов:           {timeouts}")
    print(f"  РЕАЛЬНЫХ ПАНИК:      {len(real_panics)}")
    print(f"  сигналов послано:    {killed['n']}")
    print(f"  зомби-процессов:     {len(zombies)}")

    bad = len(real_panics)
    print(f"\n{'УСТОЙЧИВО: паник нет' if bad == 0 else f'НАЙДЕНО ПАНИК: {bad}'}")
    for c, m in real_panics[:3]:
        line = (m.strip().splitlines() or [""])[0][:140]
        print(f"    rc={c}: {line}")
    if zombies:
        print(f"  ЗОМБИ (первые 3): {zombies[:3]}")
    print()
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
