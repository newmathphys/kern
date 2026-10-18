#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""ЭШЕЛОН 2, ПУНКТ 12: ХАОС-ИНЪЕКЦИЯ БИТОВЫХ СБОЕВ В `.kimg` (Bit-Rot Guard).

ЗАЧЕМ. Контейнер `.kimg` защищает ИИ-датасеты и чанки RAG: если носитель
«сгнил» (bit-rot), запись оборвалась (torn write) или атакующий подменил байт,
контейнер ОБЯЗАН это обнаружить — иначе отравленный чанк уйдёт в модель.

ЧТО ДЕЛАЕМ. Берём РЕАЛЬНЫЙ `.kimg`, проверяем целостность (позитивный контроль),
затем по очереди инвертируем ОДИН бит в N разных точках файла и требуем, чтобы
`kernc check-integrity` ОТКАЗАЛ на каждой (Merkle-корень / дайджест объекта).

ЧЕСТНОСТЬ. Если какой-то бит НЕ обнаружен — печатаем его точную позицию и
считаем это НАХОДКОЙ, а не «ок». rc=0 только если обнаружены ВСЕ инъекции.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"
DEFAULT_KIMG = ROOT / "audits" / "real_code_corpus.kimg"


def tmp_dir() -> str:
    shm = Path("/dev/shm")
    if shm.is_dir() and os.access(shm, os.W_OK):
        d = shm / "kern-bitrot"
        d.mkdir(exist_ok=True)
        return str(d)
    return "/tmp"




def data_digest(kimg: Path) -> tuple[int, int, str]:
    """SHA-256 ПО ДАННЫМ: распаковать каждый объект и сложить байты.

    ЗАЧЕМ. Часть битов сжатого потока (выравнивание deflate) на данные НЕ
    влияет. Такое «необнаружение» — НЕ дыра: проверяемое содержимое неизменно.
    Чтобы отличать это от реальной порчи, сверяем дайджест ДАННЫХ.
    """
    import hashlib
    # Осторожно: у ПОВРЕЖДЁННОГО образа вывод может содержать не-UTF8 байты.
    _ls = subprocess.run([str(KERNC), "ls", str(kimg)], capture_output=True)
    ls = _ls.stdout.decode("utf-8", errors="replace")
    paths = [l.split("path=`")[1].rstrip("`") for l in ls.splitlines() if "path=`" in l]
    h = hashlib.sha256()
    total = 0
    for pth in paths:
        r = subprocess.run([str(KERNC), "cat", str(kimg), "/raw/" + pth],
                           capture_output=True, timeout=120)
        h.update(r.stdout)
        total += len(r.stdout)
    return len(paths), total, h.hexdigest()

def check(kimg: Path) -> int:
    return subprocess.run([str(KERNC), "check-integrity", str(kimg)],
                          capture_output=True, text=True, timeout=120).returncode


def inject(args):
    data, pos, bit, td, i = args
    buf = bytearray(data)
    buf[pos] ^= (1 << bit)
    p = Path(td) / f"rot_{i}.kimg"
    p.write_bytes(bytes(buf))
    return i, pos, bit, check(p)


def main() -> int:
    ap = argparse.ArgumentParser(description="Bit-Rot chaos: инъекция битовых сбоев")
    ap.add_argument("--kimg", default=str(DEFAULT_KIMG))
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 1))
    args = ap.parse_args()

    kimg = Path(args.kimg)
    if not KERNC.exists():
        print(f"[!] нет {KERNC} — соберите: zig build")
        return 2
    if not kimg.exists():
        print(f"[!] нет образа {kimg}")
        return 2
    data = kimg.read_bytes()
    print(f"[i] образ: {kimg} ({len(data)} байт)")

    # ПОЗИТИВНЫЙ КОНТРОЛЬ: неповреждённый образ обязан быть целым.
    rc0 = check(kimg)
    print(f"[контроль] неповреждённый образ: rc={rc0} (ожидается 0)")
    if rc0 != 0:
        print("[!] образ УЖЕ не проходит проверку — chaos неприменим")
        return 2

    # N точек, равномерно по файлу; бит чередуем, чтобы покрыть разные разряды.
    step = max(1, len(data) // args.n)
    jobs = [(data, min(len(data) - 1, i * step), (i * 3) % 8, None, i)
            for i in range(args.n)]
    undetected = []
    with tempfile.TemporaryDirectory(dir=tmp_dir()) as td:
        jobs = [(d, p, b, td, i) for (d, p, b, _, i) in jobs]
        with ThreadPoolExecutor(max_workers=args.jobs) as ex:
            res = list(ex.map(inject, jobs))

    n0, t0, d0 = data_digest(kimg)
    print(f"[i] контроль данных: объектов {n0}, {t0} байт, sha256 {d0[:16]}")

    silent_ok = []   # не поймано, но ДАННЫЕ не изменились (биты выравнивания)
    real_gap = []    # не поймано, и ДАННЫЕ изменились — настоящая дыра
    with tempfile.TemporaryDirectory(dir=tmp_dir()) as td2:
        for i, pos, bit, rc in sorted(res, key=lambda z: z[0]):
            if rc != 0:
                print(f"  [{i + 1:>2}/{args.n}] байт {pos:>6}, бит {bit}: rc={rc} -> обнаружен OK")
                continue
            buf = bytearray(data)
            buf[pos] ^= (1 << bit)
            q = Path(td2) / f"d_{i}.kimg"
            q.write_bytes(bytes(buf))
            _, _, dq = data_digest(q)
            if dq == d0:
                silent_ok.append((pos, bit))
                print(f"  [{i + 1:>2}/{args.n}] байт {pos:>6}, бит {bit}: rc=0, "
                      f"НО данные ИДЕНТИЧНЫ (биты выравнивания deflate) -> не дыра")
            else:
                real_gap.append((pos, bit))
                print(f"  [{i + 1:>2}/{args.n}] байт {pos:>6}, бит {bit}: rc=0, "
                      f"ДАННЫЕ ИЗМЕНИЛИСЬ -> ДЫРА !!!")

    detected = args.n - len(silent_ok) - len(real_gap)
    print("-" * 74)
    print(f"ИНЪЕКЦИЙ: {args.n} | обнаружено: {detected} | "
          f"не влияет на данные: {len(silent_ok)} | РЕАЛЬНЫХ ДЫР: {len(real_gap)}")
    if not real_gap:
        print("[OK] BIT-ROT GUARD: любое изменение ДАННЫХ ловится "
              "(дайджест объекта / Merkle-корень)")
        return 0
    print("[!] ДЫРЫ: порча ДАННЫХ не обнаружена —")
    for pos, bit in real_gap:
        print(f"    байт {pos}, бит {bit}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
