#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
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
    out = ctypes.create_string_buffer(256)
    verdict = lib.kern_localize(
        b"(>= x 0)", 8, b"(>= x 0)", 8, out, 256)
    print("  localize  :", verdict, "-> виновники:", out.value.decode() or "(нет)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
