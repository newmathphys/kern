#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""ДЕФЕКТ #317: ВАЛИДАЦИЯ АДАПТЕРОВ ДЕЛЕНИЯ ПО НЕЗАВИСИМОМУ ЭТАЛОНУ ZIG.

ЗАЧЕМ. Починка #317 (Python floor / C-подобные — усечение) подтверждалась
собственными тестами и отчётом Массимилиано. Собственный тест — слабое
подтверждение: он проверяет, что код совпадает сам с собой. Здесь эталон
ВНЕШНИЙ и уровня компилятора: встроенные операции Zig `@divTrunc`, `@divFloor`,
`@divCeil` (lib/std/math.zig:874,898,922 оборачивают именно их).

ФИКСТУРА. `tests/fixtures/zig_div_reference.tsv` — вывод программы
`tests/fixtures/zig_div_reference.zig` на домене a,b в [-20,20], b != 0
(1640 пар, 5 столбцов: a b trunc floor ceil). Фикстура ЗАКОММИЧЕНА, поэтому
гейт не требует Zig в момент проверки; пересобрать — `--regenerate`.

ЧТО ПРОВЕРЯЕТСЯ. `_floor_div_smt` обязан совпасть со столбцом `floor`,
`_trunc_div_smt` — со столбцом `trunc`. Плюс контроль: Python `a // b` обязан
совпасть с `floor` — это подтверждает САМ ДИАГНОЗ #317 (Python — floor), а не
только починку.

Запуск: python3 tools/arith_zig_ref_check.py [--selftest|--regenerate]
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "zig_div_reference.tsv"
GENERATOR = ROOT / "tests" / "fixtures" / "zig_div_reference.zig"


def _translator():
    spec = importlib.util.spec_from_file_location(
        "kc", ROOT / "tools" / "kern_contracts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _z3_eval(smt: str) -> int | None:
    try:
        import z3
    except ImportError:
        return None
    try:
        node = z3.parse_smt2_string(
            "(declare-const r Int)(assert (= r " + smt + "))")[0]
        return z3.simplify(node.arg(1)).as_long()
    except (z3.Z3Exception, AttributeError, ValueError):
        # Z3 не смог упростить/разобрать терм: значение не вычислить.
        # Явный список (класс #198): программная ошибка обязана быть видна.
        return None


def _rows() -> list[tuple[int, int, int, int, int]]:
    out = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split()
        if len(parts) == 5:
            out.append(tuple(int(x) for x in parts))  # type: ignore[arg-type]
    return out


def regenerate() -> int:
    """Пересобрать фикстуру из Zig (нужен zig в PATH)."""
    import shutil
    zig = shutil.which("zig")
    if zig is None:
        print("[!] zig не найден в PATH — фикстуру пересобрать нельзя")
        return 2
    tmp = ROOT / ".zig-ref-tmp"
    tmp.mkdir(exist_ok=True)
    try:
        r = subprocess.run([zig, "build-exe", str(GENERATOR), "-O", "ReleaseSafe",
                            "-femit-bin=" + str(tmp / "ref")],
                           capture_output=True, text=True, cwd=str(tmp), timeout=300)
        if r.returncode != 0:
            print("[FAIL] сборка эталона:", (r.stderr or "")[-400:])
            return 1
        run = subprocess.run([str(tmp / "ref")], capture_output=True, text=True,
                             timeout=300)
        text = run.stderr or run.stdout
        FIXTURE.write_text(text, encoding="utf-8")
        print(f"[OK] фикстура пересобрана: {len(text.splitlines())} строк")
    finally:
        import shutil as _sh
        _sh.rmtree(tmp, ignore_errors=True)
    return 0



def check(sabotage_naive: bool = False) -> int:
    """Сравнить адаптеры с эталоном Zig. `sabotage_naive` — selftest."""
    if not FIXTURE.exists():
        print(f"[FAIL] нет фикстуры {FIXTURE} — запустите --regenerate")
        return 2
    kc = _translator()
    if _z3_eval("1") is None:
        print("[!] нет z3 — проверка невозможна (это не «зелено»)")
        return 2

    bad_f = bad_t = bad_py = total = 0
    examples: list[str] = []
    for a, b, t, fl, _c in _rows():
        total += 1
        if sabotage_naive:
            # ЛОМАЕМ: наивный `div` вместо адаптеров — ровно состояние до #317.
            my_f = my_t = _z3_eval(f"(div {a} {b})")
        else:
            my_f = _z3_eval(kc._floor_div_smt(a, b))
            my_t = _z3_eval(kc._trunc_div_smt(a, b))
        if my_f != fl:
            bad_f += 1
            if len(examples) < 3:
                examples.append(f"    floor a={a} b={b}: zig={fl} адаптер={my_f}")
        if my_t != t:
            bad_t += 1
            if len(examples) < 6:
                examples.append(f"    trunc a={a} b={b}: zig={t} адаптер={my_t}")
        bad_py += (a // b) != fl

    print(f"[i] пар из эталона Zig: {total} "
          f"(a,b в [-20,20], b != 0; @divTrunc/@divFloor/@divCeil)")
    print(f"[i] _floor_div_smt vs Zig @divFloor : расхождений {bad_f}")
    print(f"[i] _trunc_div_smt vs Zig @divTrunc : расхождений {bad_t}")
    print(f"[i] Python `a // b` vs Zig @divFloor: расхождений {bad_py} "
          f"(контроль диагноза #317)")
    for e in examples:
        print(e)

    bad = 0
    if sabotage_naive:
        if bad_f == 0 and bad_t == 0:
            print("[FAIL] подсадка наивного div не дала расхождений — тест слеп")
            return 1
        print("\n[OK] selftest: наивный `div` расходится с Zig — тест способен упасть")
        return 0
    if bad_py != 0:
        print(f"[FAIL] Python `//` разошёлся с Zig @divFloor ({bad_py}) — "
              f"диагноз #317 неверен")
        bad += 1
    if bad_f or bad_t:
        print(f"\n[FAIL] адаптеры расходятся с Zig: floor {bad_f}, trunc {bad_t}")
        bad += 1
    if bad:
        return 1
    print(f"\n[OK] адаптеры #317 подтверждены НЕЗАВИСИМЫМ эталоном Zig: "
          f"{total} пар, 0 расхождений (floor и trunc)")
    return 0


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--regenerate" in args:
        return regenerate()
    if "--selftest" in args:
        return check(sabotage_naive=True)
    return check()


if __name__ == "__main__":
    sys.exit(main())
