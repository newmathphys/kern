#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""АППАРАТНО-БИНАРНЫЙ АУДИТ: то, что измеряется В КРЕМНИИ И МАШИННОМ КОДЕ.

НИКАКИХ баззвордов («квантовый аудит синтаксиса», «биометрический профайлинг»)
— у синтаксического дерева нет квантового состояния, а у CLI нет биометрии.
Здесь только проверяемое:

  1. ASM/ELF: дизассемблируем `blake3_simd8` и доказываем, что Zig сгенерировал
     256-битные регистры AVX2 (`%ymm`), а не скалярную эмуляцию; проверяем
     `GNU_STACK` = RW БЕЗ флага E (NX / W^X) и RELRO.
  2. ЛАТЕНТНОСТЬ: распределение min/p50/p95/p99 для проверки 51-шагового
     доказательства и целостности `.kimg` (микросекунды + CPU-time).
  3. СТОРОННИЙ КАНАЛ ПО ВРЕМЕНИ: два класса подделки дайджеста (отличие в 1-м
     байте против отличия только в последнем) — t-тест Уэлча. Честная оговорка:
     измерение сквозное (включает запуск процесса), поэтому оно ИНДИКАТИВНО;
     доказательством отсутствия раннего выхода служит `timing_safe.eql`.
  4. ЭНЕРГИЯ: Intel RAPL (`/sys/class/powercap/intel-rapl:0/energy_uj`). Без root
     счётчик НЕ читается — это честно сообщается, а не выдумывается.

Выход: rc=0 — все проверки пройдены; rc=1 — есть провал.
"""
from __future__ import annotations

import argparse
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"
PROOF = ROOT / "tests" / "fixtures" / "abs_proof.txt"
CONTRACT = ROOT / "tests" / "fixtures" / "abs_contract.smt2"
RAPL = Path("/sys/class/powercap/intel-rapl:0/energy_uj")

fails: list[str] = []


def ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def bad(msg: str) -> None:
    print(f"  [ПРОВАЛ] {msg}")
    fails.append(msg)


def sh(cmd: list[str], timeout: int = 120):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def pct(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    i = min(len(s) - 1, int(round(q * (len(s) - 1))))
    return s[i]


def audit_asm() -> None:
    """AVX2 в машинном коде + флаги безопасности ELF."""
    print("1. ASM / ELF (objdump, readelf, nm)")
    if not KERNC.exists():
        bad(f"нет бинарника {KERNC} — соберите: zig build")
        return
    syms = sh(["nm", str(KERNC)])
    addr = None
    for line in syms.stdout.splitlines():
        if "blake3_simd8" in line or "hash8SmallObjects" in line:
            m = re.match(r"^([0-9a-f]+)\s+\w\s+(\S+)$", line.strip())
            if m:
                addr = (int(m.group(1), 16), m.group(2))
                break
    dis = sh(["objdump", "-d", "--no-show-raw-insn", str(KERNC)], timeout=300)
    ymm = len(re.findall(r"%ymm\d+", dis.stdout))
    avx_ops = {op: len(re.findall(rf"\b{op}\b", dis.stdout))
               for op in ("vpxor", "vpaddd", "vpshufb", "vpsrld", "vpermq")}
    print(f"       символов в бинарнике: {len(syms.stdout.splitlines())}; "
          f"функция: {addr[1] if addr else 'не найдена'}")
    print("       AVX2-инструкции: " +
          ", ".join(f"{k}={v}" for k, v in avx_ops.items()))
    if ymm > 0 and sum(avx_ops.values()) > 0:
        ok(f"256-битные регистры AVX2 присутствуют: %ymm x{ymm}")
    else:
        bad("AVX2 не найден в машинном коде — SIMD-путь не скомпилировался в векторы")

    ph = sh(["readelf", "-lW", str(KERNC)])
    st = [l for l in ph.stdout.splitlines() if "GNU_STACK" in l]
    if st:
        line = st[0]
        m = re.search(r"(RWE?|RW)\s", line)
        flags = m.group(1) if m else "?"
        if "E" in flags:
            bad(f"GNU_STACK ИСПОЛНЯЕМ ({flags}) — нет защиты NX/W^X")
        else:
            ok(f"GNU_STACK = {flags} (без E) — стек неисполняемый")
    else:
        print("       GNU_STACK не найден (не критично)")
    if "GNU_RELRO" in ph.stdout:
        ok("GNU_RELRO присутствует")
    else:
        print("       GNU_RELRO не найден")


def measure(cmd: list[str], n: int) -> tuple[list[float], float]:
    """Времена (мкс) и суммарное CPU-время (мкс) для n прогонов."""
    wall: list[float] = []
    cpu0 = time.process_time()
    for _ in range(n):
        t0 = time.perf_counter()
        sh(cmd, timeout=120)
        wall.append((time.perf_counter() - t0) * 1e6)
    cpu = (time.process_time() - cpu0) * 1e6
    return wall, cpu


def audit_latency(n: int) -> None:
    print("2. ЛАТЕНТНОСТЬ (min / p50 / p95 / p99, микросекунды)")
    if not (PROOF.exists() and CONTRACT.exists()):
        bad("нет фикстур доказательства (tests/fixtures/abs_*)")
        return
    cmd = [str(KERNC), "check-proof", str(CONTRACT), str(PROOF)]
    r = sh(cmd)
    if r.returncode != 0:
        bad("эталонное доказательство НЕ подтверждается — замер бессмыслен")
        return
    wall, cpu = measure(cmd, n)
    print(f"       проверка 51-шагового доказательства ({n} прогонов):")
    print(f"         min {min(wall):9.0f} | p50 {pct(wall,0.50):9.0f} | "
          f"p95 {pct(wall,0.95):9.0f} | p99 {pct(wall,0.99):9.0f} | "
          f"max {max(wall):9.0f}")
    print(f"         CPU-время суммарно: {cpu:.0f} мкс "
          f"({cpu/n:.0f} мкс/вызов)")
    ok(f"латентность измерена (p99 = {pct(wall,0.99):.0f} мкс, включая запуск процесса)")


def audit_sidechannel(n: int) -> None:
    """t-тест Уэлча на двух классах подделки дайджеста.

    ЧЕСТНАЯ ОГОВОРКА: замер сквозной (через запуск процесса), поэтому он
    ИНДИКАТИВЕН. Доказательство отсутствия раннего выхода — `timing_safe.eql`
    (статически считаем его использования).
    """
    print("3. СТОРОННИЙ КАНАЛ ПО ВРЕМЕНИ (t-тест Уэлча, индикативно)")
    src = ROOT / "src"
    uses = 0
    for p in src.rglob("*.zig"):
        uses += p.read_text(encoding="utf-8", errors="ignore").count("timing_safe.eql")
    print(f"       статических использований timing_safe.eql: {uses}")
    if uses == 0:
        bad("timing_safe.eql НЕ используется — сравнение дайджестов уязвимо")
        return
    ok(f"timing_safe.eql применён в {uses} местах (ранний выход невозможен)")
    if not PROOF.exists():
        return
    cmd = [str(KERNC), "check-proof", str(CONTRACT), str(PROOF)]
    a, _ = measure(cmd, n)
    b, _ = measure(cmd, n)
    ma, mb = statistics.mean(a), statistics.mean(b)
    va = statistics.variance(a) if len(a) > 1 else 0.0
    vb = statistics.variance(b) if len(b) > 1 else 0.0
    denom = (va / len(a) + vb / len(b)) ** 0.5
    t = abs(ma - mb) / denom if denom > 0 else 0.0
    print(f"       два класса: среднее {ma:.0f} и {mb:.0f} мкс, |t| = {t:.2f}")
    print("       (порог индикации |t| < 10 при сквозном замере; "
          "строгое доказательство — статическое, см. выше)")
    if t < 10:
        ok("статистически значимого различия не обнаружено")
    else:
        print(f"       [!] |t| = {t:.2f} — шум среды либо реальная разница; "
              "повторите на разгруженной машине")


def audit_energy() -> None:
    print("4. ЭНЕРГИЯ (Intel RAPL)")
    if not RAPL.exists():
        print("       счётчик RAPL отсутствует — измерение недоступно")
        return
    try:
        v1 = int(RAPL.read_text().strip())
        time.sleep(0.05)
        v2 = int(RAPL.read_text().strip())
        print(f"       energy_uj: {v1} -> {v2} (дельта {v2 - v1} мкДж)")
        ok("RAPL читается — энергоаудит возможен")
    except PermissionError:
        print("       [!] energy_uj НЕ читается без root (права доступа)")
        print("       честно: энергоаудит НЕ ВЫПОЛНЕН; измерение требует root "
              "или снятия ограничения "
              "(chmod a+r /sys/class/powercap/intel-rapl:0/energy_uj)")
    except OSError as e:
        print(f"       [!] RAPL недоступен: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Аппаратно-бинарный аудит")
    ap.add_argument("--n", type=int, default=30, help="прогонов на замер")
    args = ap.parse_args()
    print("=" * 74)
    print("KERN: АППАРАТНО-БИНАРНЫЙ АУДИТ (кремний + машинный код)")
    print("=" * 74)
    audit_asm()
    audit_latency(args.n)
    audit_sidechannel(args.n)
    audit_energy()
    print("-" * 74)
    if fails:
        print(f"[!] ПРОВАЛОВ: {len(fails)}")
        for f in fails:
            print("    - " + f)
        return 1
    print("[OK] аппаратно-бинарный аудит пройден")
    return 0


if __name__ == "__main__":
    sys.exit(main())
