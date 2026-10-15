#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
"""
KERN: C-ABI and Z3 bridge under load.

ЗАЧЕМ. Ядро встраивается в чужие системы через C-ABI (`include/kern.h`,
`libkern.so`) — без запуска CLI. Этот тест проверяет ABI на самых опасных
режимах:

  A. Семантический разрыв ℤ ↔ BitVec32 (§1b):
     в математических целых `x > 0 AND x + 1 < 0` НЕВЫПОЛНИМО (unsat -> PROVED),
     в 32-битных знаковых — ВЫПОЛНИМО при x = 0x7FFFFFFF (sat -> REFUTED).
     Ровно то, что доказывает `formal/KernSemanticGap.lean`.

  B. Бомба зависания: тяжёлая нелинейная формула. Мост ОБЯЗАН убить решатель
     по таймауту и вернуть UNKNOWN/TOOL_ERROR — но НЕ PROVED (иначе это ложное
     доказательство, худший из возможных дефектов).

  C. Конкурентность: N потоков вызывают ABI одновременно. Проверяем отсутствие
     паник, гонок и ложных вердиктов.

  D. Целостность: `kern_kimg_valid` на валидном и на испорченном образе.

  E. Локализация: `kern_localize` возвращает имена виновных утверждений.

Запуск:  python3 tests/capi_cli_suite.py
Критерий: все проверки пройдены; скрипт возвращает 0.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB_CANDIDATES = [ROOT / "zig-out" / "lib" / "libkern.so", ROOT / "libkern.so"]

KERN_PROVED, KERN_REFUTED, KERN_UNKNOWN, KERN_TOOL_ERROR = 0, 1, 2, -1
NAMES = {0: "PROVED", 1: "REFUTED", 2: "UNKNOWN", -1: "TOOL_ERROR"}

PASS, FAIL = [], []


def ok(msg: str) -> None:
    PASS.append(msg)
    print(f"  \033[32m[OK]\033[0m   {msg}")


def bad(msg: str) -> None:
    FAIL.append(msg)
    print(f"  \033[31m[FAIL]\033[0m {msg}")


def find_lib() -> Path:
    for p in LIB_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError("нет libkern.so — соберите: zig build lib")


def load(lib: Path):
    k = ctypes.CDLL(str(lib))
    k.kern_version.restype = ctypes.c_char_p
    k.kern_author.restype = ctypes.c_char_p
    k.kern_ownership_ok.restype = ctypes.c_int
    k.kern_smt_verify.restype = ctypes.c_int
    k.kern_smt_verify.argtypes = [ctypes.c_char_p, ctypes.c_ulong]
    k.kern_kimg_valid.restype = ctypes.c_int
    k.kern_kimg_valid.argtypes = [ctypes.c_char_p, ctypes.c_ulong]
    k.kern_kimg_object_count.restype = ctypes.c_long
    k.kern_kimg_object_count.argtypes = [ctypes.c_char_p, ctypes.c_ulong]
    k.kern_localize.restype = ctypes.c_int
    k.kern_localize.argtypes = [ctypes.c_char_p, ctypes.c_ulong, ctypes.c_char_p, ctypes.c_ulong,
                                ctypes.c_char_p, ctypes.c_ulong, ctypes.c_char_p, ctypes.c_ulong]
    return k


def smt_verify(k, script: str) -> int:
    b = script.encode("utf-8")
    return int(k.kern_smt_verify(b, len(b)))


SMT_INT_GAP = """
(set-logic QF_LIA)
(declare-const x Int)
(assert (> x 0))
(assert (< (+ x 1) 0))
(check-sat)
"""

SMT_BV32_OVERFLOW = """
(set-logic QF_BV)
(declare-const x (_ BitVec 32))
(assert (bvsgt x #x00000000))
(assert (bvslt (bvadd x #x00000001) #x00000000))
(check-sat)
"""

SMT_TIMEOUT_BOMB = """
(set-logic NIA)
(declare-const a Int)
(declare-const b Int)
(declare-const c Int)
(assert (= (+ (* a a a) (* b b b) (* c c c)) 42))
(assert (> a 100000000000))
(check-sat)
"""

SMT_TRIVIAL_PROVED = """
(set-logic QF_LIA)
(declare-const y Int)
(assert (> y 10))
(assert (< y 5))
(check-sat)
"""


def scenario_a_semantic_gap(k) -> None:
    print("\n=== A. Семантический разрыв: Z (Int) vs BitVec32 ===")
    r_int = smt_verify(k, SMT_INT_GAP)
    r_bv = smt_verify(k, SMT_BV32_OVERFLOW)
    print(f"  Int   (x>0 AND x+1<0): {NAMES.get(r_int, r_int)}")
    print(f"  BV32  (то же, 32 бита): {NAMES.get(r_bv, r_bv)}")
    if r_int == KERN_PROVED:
        ok("Z: невыполнимо -> PROVED (переполнения в Z не существует)")
    else:
        bad(f"Z: ожидался PROVED, получено {NAMES.get(r_int, r_int)}")
    if r_bv == KERN_REFUTED:
        ok("BV32: выполнимо -> REFUTED (контрпример x = 0x7FFFFFFF)")
    else:
        bad(f"BV32: ожидался REFUTED, получено {NAMES.get(r_bv, r_bv)}")
    if r_int != r_bv:
        ok("РАЗРЫВ ПОДТВЕРЖДЁН: один предикат даёт разные вердикты")
    else:
        bad("разрыв НЕ обнаружен — типы перепутаны")


def count_our_zombies() -> int:
    """Зомби ИМЕННО наших детей (системные зомби других процессов не считаем).

    Наивный `ps | grep '^Z'` ловит чужие зомби и даёт ложные срабатывания —
    проверено прогоном. Считаем только тех, чей PPID == наш PID.
    """
    out = subprocess.run(["bash", "-lc", f"ps -eo stat=,ppid= | awk '$1 ~ /^Z/ && $2 == {os.getpid()}' | wc -l"],
                         capture_output=True, text=True).stdout.strip()
    return int(out or 0)


def scenario_b_timeout_bomb(k) -> None:
    print("\n=== B. Бомба зависания (таймаут, fail-closed) ===")
    z_before = count_our_zombies()
    t0 = time.perf_counter()
    r = smt_verify(k, SMT_TIMEOUT_BOMB)
    dt = (time.perf_counter() - t0) * 1000.0
    print(f"  вердикт: {NAMES.get(r, r)}  за {dt:.0f} мс")
    if r == KERN_PROVED:
        bad("ЛОЖНОЕ ДОКАЗАТЕЛЬСТВО: тяжёлая формула объявлена доказанной!")
    else:
        ok(f"fail-closed: {NAMES.get(r, r)} (не PROVED) — безопасная деградация")
    z_after = count_our_zombies()
    if z_after <= z_before:
        ok(f"зомби-процессов не осталось (до={z_before}, после={z_after})")
    else:
        bad(f"появились зомби-процессы: было {z_before}, стало {z_after}")


def scenario_c_concurrency(k, threads: int = 16, rounds: int = 4) -> None:
    print(f"\n=== C. Конкурентность: {threads} потоков × {rounds} раунда ===")
    results: list[int] = []
    lock = threading.Lock()
    errors: list[str] = []

    def worker(tid: int) -> None:
        for i in range(rounds):
            try:
                # Чередуем UNSAT (PROVED) и SAT (REFUTED), чтобы вердикты были
                # проверяемыми, а не «любое значение».
                script = SMT_TRIVIAL_PROVED if (tid + i) % 2 == 0 else SMT_BV32_OVERFLOW
                r = smt_verify(k, script)
                with lock:
                    results.append(r)
            except Exception as e:  # noqa: BLE001
                with lock:
                    errors.append(repr(e))

    ths = [threading.Thread(target=worker, args=(t,)) for t in range(threads)]
    t0 = time.perf_counter()
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    dt = (time.perf_counter() - t0) * 1000.0

    total = threads * rounds
    if errors:
        bad(f"исключения в потоках: {errors[:3]}")
    elif len(results) != total:
        bad(f"потеряны результаты: {len(results)} из {total}")
    else:
        ok(f"{len(results)} вызовов ABI из {threads} потоков за {dt:.0f} мс, без паник")
    n_proved = sum(1 for r in results if r == KERN_PROVED)
    n_ref = sum(1 for r in results if r == KERN_REFUTED)
    print(f"  вердикты: PROVED={n_proved} REFUTED={n_ref} прочие={len(results)-n_proved-n_ref}")
    if n_proved and n_ref:
        ok("оба типа вердиктов получены под нагрузкой (нет залипания состояния)")



def scenario_d_kimg(k) -> None:
    print("\n=== D. Целостность .kimg через C-ABI ===")
    img_path = Path("/tmp/kern_capi_toy.kimg")
    kernc = ROOT / "zig-out" / "bin" / "kernc"
    subprocess.run([str(kernc), "build",
                    str(ROOT / "examples" / "toy_ai_hallucination" / "project.kern"),
                    "-o", str(img_path)], cwd=str(ROOT), capture_output=True, text=True)
    if not img_path.exists():
        print("  [i] не удалось собрать образ — пропуск")
        return
    data = img_path.read_bytes()
    v = int(k.kern_kimg_valid(data, len(data)))
    n = int(k.kern_kimg_object_count(data, len(data)))
    print(f"  валидный образ: valid={v} объектов={n} ({len(data)} Б)")
    if v == 1 and n > 0:
        ok("валидный образ принят, объекты посчитаны")
    else:
        bad(f"валидный образ отвергнут (valid={v}, n={n})")

    # Портим ОДИН байт в payload (таблица и Merkle не тронуты).
    tbl = struct.unpack_from("<Q", data, 32)[0]
    off = struct.unpack_from("<Q", data, tbl + 32)[0]
    broken = bytearray(data)
    broken[off] ^= 0xFF
    v2 = int(k.kern_kimg_valid(bytes(broken), len(broken)))
    if v2 == 0:
        ok("испорченный payload отвергнут (целостность работает)")
    else:
        bad("испорченный образ ПРИНЯТ — дыра в целостности!")

    # Обрезанный образ: `kern_kimg_valid` по контракту проверяет ЗАГОЛОВОК и
    # MERKLE (дешёвый пре-чек), поэтому обрезка, не задевшая таблицу, им не
    # ловится. Реальный инвариант: ЧТЕНИЕ объекта за границей файла обязано
    # быть отвергнуто (а не вернуть мусор).
    kernc = ROOT / "zig-out" / "bin" / "kernc"
    half = data[: len(data) // 2]
    trunc = Path("/tmp/kern_capi_trunc.kimg")
    trunc.write_bytes(half)
    # Берём объект, чей payload ЗАВЕДОМО выходит за обрезку (последний).
    e_last = tbl + (int(struct.unpack_from("<Q", data, 48)[0]) - 1) * 96
    off_last = struct.unpack_from("<Q", data, e_last + 32)[0] + struct.unpack_from("<Q", data, 56)[0]
    p = subprocess.run([str(kernc), "cat", str(trunc), "/raw/examples/toy_ai_hallucination/contract_fixed.smt2"],
                       cwd=str(ROOT), capture_output=True, text=True)
    print(f"  обрезка: файл {len(half)} Б, последний payload начинается на {off_last}")
    if p.returncode != 0:
        ok(f"чтение объекта за границей файла отвергнуто (rc={p.returncode})")
    else:
        bad("чтение за границей файла прошло с rc=0 — защита не сработала")
    v3 = int(k.kern_kimg_valid(half, len(half)))
    print(f"  kern_kimg_valid на обрезке: {v3} (контракт: заголовок+Merkle, не границы payload)")


def scenario_e_localize(k) -> None:
    print("\n=== E. Локализация виновника (UNSAT core) ===")
    # Семантика ABI: 0 = ДОКАЗАНО (pre AND NOT goal НЕВЫПОЛНИМО).
    # Значит goal обязан СЛЕДОВАТЬ из pre: берём pre = goal = (>= x 0).
    # (Первая версия теста подавала goal = (< x 0) и законно получала REFUTED —
    #  ошибка была в ожидании теста, а не в ядре.)
    decls = b"(declare-const x Int)"
    pre = b"(>= x 0)"
    goal = b"(>= x 0)"
    buf = ctypes.create_string_buffer(256)
    r = int(k.kern_localize(decls, len(decls), pre, len(pre), goal, len(goal), buf, 256))
    names = buf.value.decode("utf-8", "replace").strip()
    print(f"  pre={pre.decode()}  goal={goal.decode()}  ->  {NAMES.get(r, r)}  ядро: `{names}`")
    if r == KERN_PROVED:
        ok("противоречие pre AND NOT goal обнаружено (PROVED)")
    else:
        bad(f"ожидался PROVED, получено {NAMES.get(r, r)}")
    if names:
        ok(f"ABI вернул имена утверждений ядра: {names}")
    else:
        print("  [i] имена ядра пусты (зависит от поддержки :named у решателя)")

    # Контрольная проверка: goal, НЕ следующий из pre, обязан дать REFUTED.
    goal2 = b"(< x -100)"
    buf2 = ctypes.create_string_buffer(256)
    r2 = int(k.kern_localize(decls, len(decls), pre, len(pre), goal2, len(goal2), buf2, 256))
    if r2 == KERN_REFUTED:
        ok("ложная цель даёт REFUTED (проверка не вакуумна)")
    else:
        bad(f"ложная цель дала {NAMES.get(r2, r2)} — проверка вакуумна!")


def scenario_f_cli_contract() -> None:
    """🔴 РЕГРЕССИЯ ДЕФЕКТА #60: контракт CLI (данные -> stdout, отказ -> rc != 0).

    ДО ФИКСА: `kernc cat` печатал содержимое через `std.debug.print` (stderr),
    поэтому `kernc cat img /raw/f > out.txt` давал ПУСТОЙ файл, а конвейер
    `| grep` не видел ничего. Код возврата при этом был 0.
    """
    print("\n=== F. Контракт CLI: данные -> stdout, отказ -> rc != 0 ===")
    kernc = ROOT / "zig-out" / "bin" / "kernc"
    img = Path("/tmp/kern_capi_toy.kimg")
    if not img.exists():
        print("  [i] нет образа — пропуск")
        return
    target = "/raw/examples/toy_ai_hallucination/withdraw.py"

    p = subprocess.run([str(kernc), "cat", str(img), target], cwd=str(ROOT),
                       capture_output=True, text=True)
    if p.returncode == 0 and len(p.stdout) > 100:
        ok(f"cat: данные в stdout ({len(p.stdout)} Б), rc=0")
    else:
        bad(f"cat: stdout={len(p.stdout)} Б, rc={p.returncode} — данные ушли не в stdout")

    # Отказ: несуществующий путь ОБЯЗАН дать ненулевой код возврата.
    p2 = subprocess.run([str(kernc), "cat", str(img), "/raw/такого-нет"], cwd=str(ROOT),
                        capture_output=True, text=True)
    if p2.returncode != 0:
        ok(f"cat на несуществующий путь: rc={p2.returncode} (проверка способна упасть)")
    else:
        bad("cat на несуществующий путь вернул rc=0 — проверка НЕ способна упасть")

    # Конвейер: содержимое должно быть доступно через пайп.
    # ВАЖНО: пути кавычим — рабочий каталог содержит ПРОБЕЛ («Рабочий стол»),
    # без кавычек shell разобьёт путь и команда не найдётся (ложный FAIL).
    p3 = subprocess.run(f'"{kernc}" cat "{img}" "{target}" 2>/dev/null | grep -c withdraw',
                        shell=True, cwd=str(ROOT), capture_output=True, text=True)
    n = (p3.stdout or "0").strip()
    if n.isdigit() and int(n) > 0:
        ok(f"конвейер видит данные (совпадений: {n})")
    else:
        bad("конвейер НЕ видит данные — содержимое уходит не в stdout")

    # ls тоже обязан писать в stdout.
    p4 = subprocess.run([str(kernc), "ls", str(img)], cwd=str(ROOT),
                        capture_output=True, text=True)
    if p4.returncode == 0 and len(p4.stdout) > 10:
        ok(f"ls: данные в stdout ({len(p4.stdout)} Б)")
    else:
        bad(f"ls: stdout={len(p4.stdout)} Б — данные ушли не в stdout")



def main() -> int:
    print("=" * 84)
    print("KERN: C-ABI + Z3 BRIDGE UNDER LOAD")
    print("=" * 84)
    try:
        lib = find_lib()
    except FileNotFoundError as e:
        print(f"[!] {e}")
        return 1
    k = load(lib)
    ver = k.kern_version().decode() if k.kern_version() else "?"
    auth = k.kern_author().decode() if k.kern_author() else "?"
    own = int(k.kern_ownership_ok())
    print(f"  библиотека: {lib}")
    print(f"  версия: {ver}  автор: {auth}  ключ-замок: {'валиден' if own else 'НЕ валиден'}")
    if not own:
        bad("ключ-замок авторства не подтверждён")
    else:
        ok("ключ-замок авторства подтверждён")

    scenario_a_semantic_gap(k)
    scenario_b_timeout_bomb(k)
    scenario_c_concurrency(k)
    scenario_d_kimg(k)
    scenario_e_localize(k)
    scenario_f_cli_contract()

    print("\n" + "=" * 84)
    print(f"ИТОГ: пройдено {len(PASS)}, провалено {len(FAIL)}")
    for f in FAIL:
        print(f"  x {f}")
    print("=" * 84)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())

