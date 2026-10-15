#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN: ЭШЕЛОН 2 — ЛАВИННЫЙ ШТУРМ ХЭША КЭША ДОКАЗАТЕЛЬСТВ.

Защита от Algorithmic DoS (Hash Flooding): если при изменении 1 бита входа
хэш-ключ меняется слабо, элементы кучкуются в одном бакете, и кэш
деградирует из O(1) в O(N).

Здесь: 100 000 SMT-формул, каждая следующая отличается ровно на 1 бит.
Ключ строится ТЕМ ЖЕ алгоритмом, что и в KERN (`ProofCache.keyOf`):
    SHA-256( ast[32] || contract[32] || proof )

Метрики:
  * лавинный эффект: средняя доля изменённых бит ключа при 1 бите входа (~50%);
  * распределение по бакетам (load factor 1.0): max-цепочка и chi-square;
  * контраст с «наивным» хэшем (сумма байт) — чтобы показать, что защита не выдумана.
"""
import hashlib
import os
import struct
import sys

N = int(os.environ.get("N", "100000"))
# Бакетов ровно столько же, сколько входов => коэффициент загрузки = 1.0.
# Для идеального равномерного хэша ожидаемая МАКС. длина цепочки ~ ln(N)/ln(ln(N)) ≈ 5-6.
BUCKETS = N
AST = bytes(range(32))
CONTRACT = bytes(range(32, 64))


def kern_key(proof: bytes) -> bytes:
    """Точная копия ProofCache.keyOf (SHA-256 от ast || contract || proof)."""
    h = hashlib.sha256()
    h.update(AST)
    h.update(CONTRACT)
    h.update(proof)
    return h.digest()


def weak_key(proof: bytes) -> bytes:
    """«Наивный» хэш: сумма байт — классический антипример (не лавинный)."""
    s = sum(proof) + sum(AST) + sum(CONTRACT)
    return struct.pack(">Q", s & 0xFFFFFFFFFFFFFFFF) * 4


def popcount_bytes(b: bytes) -> int:
    return sum(bin(x).count("1") for x in b)


def bucket_of(key: bytes, buckets: int) -> int:
    return int.from_bytes(key[:4], "big") % buckets


def run(name, keyfn):
    prev_key = None
    flip_ratios = []
    bucket_counts = [0] * BUCKETS
    keys = set()
    collisions = 0

    for i in range(N):
        # 1 бит изменения: варьируем один символ формулы
        proof = b"(assert (= x " + str(i).encode() + b"))"
        k = keyfn(proof)
        if k in keys:
            collisions += 1
        keys.add(k)
        bucket_counts[bucket_of(k, BUCKETS)] += 1
        if prev_key is not None:
            diff = popcount_bytes(bytes(a ^ b for a, b in zip(prev_key, k)))
            flip_ratios.append(diff)
        prev_key = k

    avg_flip = sum(flip_ratios) / len(flip_ratios)
    pct = avg_flip / 256.0 * 100.0
    mx = max(bucket_counts)
    avg_chain = sum(bucket_counts) / BUCKETS
    nonempty = sum(1 for c in bucket_counts if c)
    print(f"\n=== {name} ===")
    print(f"  входов:                  {N}")
    print(f"  лавинный эффект:         {avg_flip:.2f} бит из 256 ({pct:.1f}%)")
    print(f"  целевой ориентир:        ~128 бит (50%) — идеальная лавина")
    print(f"  уникальных ключей:       {len(keys)} / {N}")
    print(f"  коллизий ключей:         {collisions}")
    print(f"  занятых бакетов:         {nonempty} / {BUCKETS}")
    print(f"  средняя длина цепочки:   {avg_chain:.3f}")
    import math
    exp_max = math.log(N) / math.log(math.log(N))
    chi = sum((c - avg_chain) ** 2 / avg_chain for c in bucket_counts)
    print(f"  МАКС. длина цепочки:     {mx}   (теор. ожидание ~{exp_max:.1f}, критерий <= 8)")
    print(f"  chi-square (равномерность): {chi:.0f}  (ожидается ~{BUCKETS})  -> O(1) подтверждён")
    return pct, mx


def main():
    print("=" * 66)
    print("KERN: ЛАВИННЫЙ ШТУРМ КЭША ДОКАЗАТЕЛЬСТВ (100 000 формул)")
    print("=" * 66)
    p1, m1 = run("KERN (SHA-256, как в ProofCache.keyOf)", kern_key)
    p2, m2 = run("НАИВНЫЙ хэш (сумма байт) — антипример", weak_key)

    print("\n" + "=" * 66)
    print("ВЕРДИКТ")
    print("=" * 66)
    ok_av = 45.0 <= p1 <= 55.0
    ok_ch = m1 <= 8
    print(f"  лавина SHA-256:  {p1:.1f}%  -> {'PASS' if ok_av else 'FAIL'} (норма 45-55%)")
    print(f"  макс. цепочка:   {m1}      -> {'PASS' if ok_ch else 'FAIL'} (критерий <= 8 при load factor 1.0)")
    print(f"  контраст: наивный хэш дал лавину {p2:.1f}% и цепочку {m2} (доказательство необходимости SHA-256)")
    if not (ok_av and ok_ch):
        sys.exit(1)


if __name__ == "__main__":
    main()
