#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by the GNU Affero General Public License v3.0 ONLY
# (AGPL-3.0-only), or a commercial license from the copyright holder. See LICENSE.
"""Демонстрация C-ABI KERN: вызов ядра из Python БЕЗ запуска CLI-процесса.

Сборка библиотеки:  zig build lib
Запуск:             python3 examples/capi_demo.py
"""
import ctypes
import os
import sys

LIB = os.path.join(os.path.dirname(__file__), "..", "zig-out", "lib", "libkern.so")
KIMG = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "valid_v1_3.kimg")


def main() -> int:
    lib = ctypes.CDLL(os.path.abspath(LIB))
    lib.kern_version.restype = ctypes.c_char_p
    lib.kern_author.restype = ctypes.c_char_p
    lib.kern_kimg_object_count.restype = ctypes.c_long

    print("=== KERN C-ABI (вызов из Python через ctypes) ===")
    print("  version   :", lib.kern_version().decode())
    print("  author    :", lib.kern_author().decode())
    print("  ownership :", lib.kern_ownership_ok(), "(1 = ключ-замок валиден)")

    # 1. SMT: доказанный контракт (контрпримеров нет) и опровергнутый.
    ok = b"(set-logic ALL)(declare-const x Int)(assert (and (> x 0) (not (> (+ x 1) 1))))(check-sat)"
    bad = b"(set-logic ALL)(declare-const x Int)(assert (and (> x 0) (not (> (+ x 1) 5))))(check-sat)"
    print("  smt prove :", lib.kern_smt_verify(ok, len(ok)), "(0 = ДОКАЗАНО)")
    print("  smt refut :", lib.kern_smt_verify(bad, len(bad)), "(1 = КОНТРПРИМЕР)")

    # 2. Образ .kimg: целостность (zero-copy, без выделения памяти).
    with open(KIMG, "rb") as f:
        img = f.read()
    buf = ctypes.create_string_buffer(img)
    print("  kimg valid:", lib.kern_kimg_valid(buf, len(img)), "(1 = валиден)")
    print("  kimg objs :", lib.kern_kimg_object_count(buf, len(img)))

    # 3. Подмена байта -> образ отвергается.
    tampered = bytearray(img)
    tampered[64] ^= 0xFF
    tbuf = ctypes.create_string_buffer(bytes(tampered))
    print("  tampered  :", lib.kern_kimg_valid(tbuf, len(tampered)), "(0 = отвергнут)")

    # 4. Локализация виновника (UNSAT core).
    # ABI: decls (объявления) | pre (предусловие) | goal (цель).
    # Скрипт: decls + pre + ¬goal. UNSAT означает, что ЦЕЛЬ СЛЕДУЕТ из pre,
    # а ядро показывает, какие именно утверждения для этого нужны.
    decls = b"(declare-const x Int)"
    pre = b"(>= x 0)"
    goal = b"(>= x -1)"  # pre ∧ ¬goal = (>= x 0) ∧ (< x -1) — НЕВЫПОЛНИМО
    out = ctypes.create_string_buffer(256)
    verdict = lib.kern_localize(
        decls, len(decls), pre, len(pre), goal, len(goal), out, 256)
    names = {"0": "ДОКАЗАНО", "1": "КОНТРПРИМЕР", "2": "НЕИЗВЕСТНО",
             "-1": "РЕШАТЕЛЬ НЕДОСТУПЕН"}
    print("  localize  :", verdict, names.get(str(verdict), "?"),
          "-> виновники:", out.value.decode() or "(нет)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
