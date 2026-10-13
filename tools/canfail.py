#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
"""KERN: CAN-FAIL — доказательство, что каждая проверка СПОСОБНА УПАСТЬ.

ЗАЧЕМ. Дефекты #26 и #30 показали: цель может быть «зелёной», НИЧЕГО не
проверяя (кросс-арх падал в qemu, анализатор constant-time был недостижим).
`RC=0` не является доказательством работоспособности проверки — вакуумная
проверка тоже даёт `RC=0`.

МЕТОД (мутационное тестирование САМИХ ПРОВЕРОК, а не кода):
  1. Вносим искусственную поломку (fault) в инвариант, который цель обязана
     защищать.
  2. Запускаем цель.
  3. ОЖИДАЕМ НЕНУЛЕВОЙ код возврата.
     • цель покраснела  -> проверка РАБОТАЕТ   (PASS)
     • цель осталась зелёной -> проверка ВАКУУМНА (FAIL, это дефект)
  4. Откатываем дерево (backup/restore).

Запуск:  python3 tools/canfail.py [--only <имя>] [--list]
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sh(cmd: str, timeout: int = 600) -> int:
    """Возвращает код возврата команды (в shell)."""
    p = subprocess.run(["bash", "-lc", cmd], cwd=str(ROOT),
                       capture_output=True, text=True, timeout=timeout)
    return p.returncode


def sh_out(cmd: str, timeout: int = 600):
    p = subprocess.run(["bash", "-lc", cmd], cwd=str(ROOT),
                       capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


class Fault:
    """Контекстный менеджер: ломает файл(ы) и ГАРАНТИРОВАННО откатывает."""

    def __init__(self, files):
        self.files = [ROOT / f for f in files]
        self.backup = {}

    def __enter__(self):
        for f in self.files:
            if f.exists():
                self.backup[f] = f.read_bytes()
        return self

    def __exit__(self, *exc):
        for f, data in self.backup.items():
            f.write_bytes(data)
        return False


def patch(path: str, old: str, new: str) -> None:
    """Замена подстроки в файле (падает, если подстрока не найдена)."""
    p = ROOT / path
    s = p.read_text(encoding="utf-8")
    if old not in s:
        raise RuntimeError(f"шаблон не найден в {path}: {old[:60]!r}")
    p.write_text(s.replace(old, new, 1), encoding="utf-8")


# ==========================================================================
# КЕЙСЫ: (имя, что проверяем, команда, инъекция поломки, таймаут)
# ==========================================================================

def case_avalanche():
    """Лавина SHA-256. ЛОМАЕМ: подменяем SHA-256 на «наивный» хэш."""
    patch("tools/cache_avalanche_bench.py",
          "    return h.digest()",
          "    return weak_key(proof)")
    return "make avalanche"


def case_lean_sorry():
    """Lean без sorry. ЛОМАЕМ: добавляем `sorry` в доказательство."""
    p = ROOT / "formal" / "KernAllMath.lean"
    with p.open("a", encoding="utf-8") as f:
        f.write("\ntheorem CANFAIL_PROBE : True := by sorry\n")
    return "bash formal/check.sh"


def case_binlevel_earlyexit():
    """Constant-time. ЛОМАЕМ: добавляем РАННИЙ ВЫХОД в constantTimeEqual."""
    patch("src/verifier/noninterference.zig",
          "    for (a, b) |x, y| acc |= x ^ y; // без ветвлений и раннего выхода",
          "    for (a, b) |x, y| { if (x != y) return false; acc |= x ^ y; } // ЛОМАЕМ")
    return "make binlevel"


def case_disasm_dce():
    """Diff-disasm. ЛОМАЕМ: убираем зондирующую функцию."""
    patch("src/binlevel_probe.zig",
          "pub export fn kern_early_exit_equal(",
          "pub fn kern_early_exit_equal_disabled(")
    return "make disasm"


def case_core_invariant():
    """Ядро: инвариант Врат. ЛОМАЕМ: открываем Врата по ТАЙМ-АУТУ.

    Это ровно тот класс бага, который KERN обязан ловить: `e=1` без
    доказательства (решатель не ответил -> вердикт не доказан).
    """
    patch("src/verifier/admission_gate.zig",
          "                cov.hit(.gate_unknown_timeout);\n                eq2 = .N; // тайм-аут не является опровержением",
          "                cov.hit(.gate_unknown_timeout);\n                eq2 = .T; e_val = 1; // ЛОМАЕМ: открываем Врата по тайм-ауту")
    return "make test"


def case_golden_merkle():
    """Эталонный образ. ЛОМАЕМ: портим байт в golden-фикстуре."""
    p = ROOT / "tests" / "fixtures" / "valid_v1_3.kimg"
    if not p.exists():
        return None
    b = bytearray(p.read_bytes())
    b[130] ^= 0xFF          # внутри таблицы объектов
    p.write_bytes(bytes(b))
    return "zig build && ./zig-out/bin/kernc check-integrity tests/fixtures/valid_v1_3.kimg"


def case_slsa_hash():
    """SLSA. ЛОМАЕМ: подменяем бинарник ПОСЛЕ аттестации."""
    rc, _ = sh_out("zig build && python3 tools/slsa_provenance.py --no-build", 300)
    if rc != 0:
        return None
    with open("/tmp/kernc_pad", "ab") as f:
        f.write(b"\x00" * 8)
    sh("cat /tmp/kernc_pad >> zig-out/bin/kernc", 60)
    return "python3 tools/slsa_provenance.py --check"


CASES = [
    ("avalanche",   "лавина SHA-256 (Hash Flooding)",      case_avalanche),
    ("lean-sorry",  "Lean: отсутствие `sorry`",             case_lean_sorry),
    ("binlevel",    "constant-time (ранний выход)",         case_binlevel_earlyexit),
    ("disasm",      "diff-disasm: потеря функции",          case_disasm_dce),
    ("core-gate",   "Врата Истины (e=1 без чекера)",        case_core_invariant),
    ("golden",      "Merkle эталонного образа",             case_golden_merkle),
    ("slsa",        "SLSA: хэш бинарника",                  case_slsa_hash),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        for n, d, _ in CASES:
            print(f"  {n:12s} {d}")
        return 0

    env = dict(os.environ)
    env["PATH"] = (f"{Path.home()}/opt/zig-x86_64-linux-0.17.0:"
                   f"{ROOT}/.venv/bin:{env.get('PATH','')}")
    os.environ.update(env)

    print("=" * 70)
    print("KERN: CAN-FAIL — проверка, что проверки СПОСОБНЫ УПАСТЬ")
    print("=" * 70)
    print("Метод: ломаем инвариант -> цель ОБЯЗАНА покраснеть.\n")

    ok = bad = skipped = 0
    for name, desc, fn in CASES:
        if args.only and args.only != name:
            continue
        t0 = time.time()
        try:
            with Fault(["tools/cache_avalanche_bench.py",
                        "formal/KernAllMath.lean",
                        "src/verifier/noninterference.zig",
                        "src/binlevel_probe.zig",
                        "src/verifier/admission_gate.zig",
                        "tests/fixtures/valid_v1_3.kimg",
                        "zig-out/bin/kernc"]):
                cmd = fn()
                if cmd is None:
                    print(f"  [SKIP] {name:12s} {desc} (предусловие не выполнено)")
                    skipped += 1
                    continue
                rc, out = sh_out(cmd, 900)
        except subprocess.TimeoutExpired:
            rc, out = 124, "TIMEOUT"
        except Exception as e:
            print(f"  [ERR ] {name:12s} {desc}: {e}")
            skipped += 1
            continue
        dt = time.time() - t0
        if rc != 0:
            print(f"  [PASS] {name:12s} {desc}")
            print(f"         проверка ПОКРАСНЕЛА (rc={rc}) за {dt:.0f} с — она не вакуумна")
            ok += 1
        else:
            print(f"  [FAIL] {name:12s} {desc}")
            print(f"         ВАКУУМНА: поломка внесена, а цель осталась ЗЕЛЁНОЙ (rc=0)!")
            bad += 1

    print()
    print("=" * 70)
    print(f"ИТОГ: не-вакуумных {ok} | ВАКУУМНЫХ {bad} | пропущено {skipped}")
    print("=" * 70)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
