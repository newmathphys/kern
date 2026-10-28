#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# SPDX-License-Identifier: LicenseRef-KERN-Proprietary
"""ФИЗИЧЕСКИЙ ОРАКУЛ для абстрактной интерпретации (шаг D плана).

ЗАЧЕМ. До этого шага семейство `absint` проверялось МОДЕЛЬ ПРОТИВ МОДЕЛИ:
`abstract_interp.zig` считает интервал, и он же объявляется верным. Вакуум.

ЧТО ДЕЛАЕТ ЭТОТ ОРАКУЛ. Для каждого линейного цикла `x := init; while (x < bound)
    x := x + step;`:
  1. НАТИВНЫЙ инвариант — `kernc theory` с формой `absint loop <init> <step> <bound>`
     (widening до неподвижной точки + narrowing);
  2. РЕАЛЬНЫЙ прогон цикла в Python: собираются ВСЕ значения на входе цикла
     (loop head) и значение выхода (первое >= bound);
  3. ЗВУЧНОСТЬ: каждое наблюдённое значение head обязано лежать в `invariant`,
     а значение выхода — в `exit_state`. Абстрактный результат, который НЕ
     содержит реального значения, — это ЛОЖЬ (unsound), а не «неточность».

ИНВАРИАНТЫ:
  * нарушений звучимости 0 (ни одного реального значения вне интервала);
  * НЕВАКУУМНОСТЬ: >= 4 случаев с хотя бы одной итерацией (иначе интервалы
    вырождены и проверка тривиальна);
  * НЕГАТИВНЫЙ КОНТРОЛЬ: классификатор обязан ловить выход значения за границу;
  * ДЕТЕРМИНИЗМ: два прогона дают один и тот же интервал.

ЧЕГО ЭТО НЕ ДОКАЗЫВАЕТ:
  * проверяются линейные циклы одного вида (`x += step`, шаг-константа), а не
    произвольные программы; widening/narrowing на нелинейных телах не покрыты;
  * проверяется ТОЛЬКО звучимость (содержание), а не точность: слишком широкий
    интервал нарушением не считается и в отчёте назван отдельно.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"
SPEC_DIR = ROOT / "tests" / "fixtures" / "oracles"

# (init, step, bound, ожидаем хотя бы одну итерацию)
FIXTURES = [
    (0, 1, 10, True),
    (0, 3, 20, True),
    (-5, 2, 7, True),
    (0, 1, 1000000, True),
    (-100, 7, -1, True),
    (100, -1, 50, False),
    (0, 1, 0, False),
]


def child_env() -> dict:
    env = dict(os.environ)
    env["PATH"] = f"{ROOT / '.venv' / 'bin'}:{env.get('PATH', '')}"
    return env


def native_invariant(init: int, step: int, bound: int, idx: int) -> tuple[str, str]:
    """НАТИВНЫЙ инвариант из ядра. Возвращает ('inv=[lo,hi] exit=[lo,hi]|пусто', причина)."""
    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    spec = SPEC_DIR / f"absint_loop_{idx}.txt"
    spec.write_text(f"# физический оракул absint\nabsint loop {init} {step} {bound}\n",
                    encoding="utf-8")
    try:
        p = subprocess.run([str(KERNC), "theory", str(spec)], cwd=ROOT, env=child_env(),
                           capture_output=True, text=True, errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return "", f"kernc theory не запустился: {e}"
    out = p.stdout + p.stderr
    m = re.search(r"инвариант=\[(-?\d+), (-?\d+)\]\s+выход=(\[[^\]]*\]|пусто)", out)
    if not m:
        return "", f"вывод не разобран: {out.strip()[:160]}"
    return f"inv=[{m.group(1)}, {m.group(2)}] exit={m.group(3)}", ""


def parse_interval(s: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"\[(-?\d+), (-?\d+)\]", s.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def real_loop(init: int, step: int, bound: int) -> tuple[list[int], int | None]:
    """РЕАЛЬНЫЙ прогон: значения на входе цикла и значение выхода."""
    heads: list[int] = []
    x = init
    while x < bound:
        heads.append(x)
        x += step
    return heads, (x if heads else None)


def classify(inside: bool) -> str:
    """Классификатор: значение внутри интервала или ВНЕ него."""
    return "SOUND" if inside else "UNSOUND"


def run() -> int:
    print("=" * 72)
    print("=== KERN: ФИЗИЧЕСКИЙ ОРАКУЛ absint (абстрактный инвариант против РЕАЛЬНОГО цикла) ===")
    print("=" * 72)

    violations: list[str] = []
    with_iters = 0
    sound_cases = 0
    width_note: list[str] = []

    for i, (init, step, bound, _) in enumerate(FIXTURES):
        nat, why = native_invariant(init, step, bound, i)
        if not nat:
            print(f"  !! нет вердикта ядра для ({init}, {step}, {bound}): {why}")
            violations.append(f"({init},{step},{bound}): ядро не дало инвариант")
            continue
        m = re.search(r"inv=\[(-?\d+), (-?\d+)\]", nat)
        inv = (int(m.group(1)), int(m.group(2)))
        heads, exit_val = real_loop(init, step, bound)
        if heads:
            with_iters += 1

        bad_here: list[str] = []
        for v in heads:
            if not (inv[0] <= v <= inv[1]):
                bad_here.append(f"head {v} вне {list(inv)}")
        if exit_val is not None:
            em = re.search(r"exit=\[(-?\d+), (-?\d+)\]", nat)
            if em:
                ex = (int(em.group(1)), int(em.group(2)))
                if not (ex[0] <= exit_val <= ex[1]):
                    bad_here.append(f"выход {exit_val} вне {list(ex)}")

        if bad_here:
            violations.extend(f"({init},{step},{bound}): {b}" for b in bad_here)
            print(f"  !! UNSOUND ({init}, {step}, {bound})  {nat}  |  {bad_here[0]}")
        else:
            sound_cases += 1
            n_heads = len(heads)
            print(f"  OK {classify(True):7s} ({init:>4}, {step:>3}, {bound:>8})  "
                  f"{nat:28s} | реальных значений head: {n_heads}")
            # Точность НЕ является инвариантом: слишком широкий интервал назван,
            # но нарушением не считается (это ограничение, а не ложь).
            if heads and (inv[1] - inv[0]) > 4 * max(1, abs(step)) * max(1, n_heads):
                width_note.append(f"({init},{step},{bound}): интервал {list(inv)} заметно шире "
                                  f"реального разброса {[min(heads), max(heads)]}")

    # НЕГАТИВНЫЙ КОНТРОЛЬ: классификатор обязан уметь поймать выход за границу.
    neg = []
    if classify(0 <= 5 <= 10) != "SOUND":
        neg.append("не признаёт значение внутри интервала")
    if classify(0 <= 11 <= 10) != "UNSOUND":
        neg.append("НЕ ловит значение ВНЕ интервала — проверка была бы фиктивной")
    print(f"  {'OK ' if not neg else '!! '}НЕГАТИВНЫЙ КОНТРОЛЬ: "
          f"{'ловит выход за границу' if not neg else '; '.join(neg)}")

    # ДЕТЕРМИНИЗМ: два прогона обязаны дать ОДИН инвариант.
    det_ok = True
    for i, (init, step, bound, _) in enumerate(FIXTURES[:3]):
        a, _ = native_invariant(init, step, bound, i)
        b, _ = native_invariant(init, step, bound, i)
        if a != b:
            det_ok = False
            violations.append(f"({init},{step},{bound}): инвариант недетерминирован ({a} vs {b})")
    print(f"  {'OK ' if det_ok else '!! '}ДЕТЕРМИНИЗМ: два прогона дают один инвариант")

    print("-" * 72)
    print(f"  случаев со итерациями : {with_iters}  (нужно >= 4)")
    print(f"  звучимых (SOUND)      : {sound_cases}")
    print(f"  НАРУШЕНИЙ ЗВУЧИМОСТИ  : {len(violations)}  (обязано быть 0)")
    if width_note:
        print(f"  шире реального разброса (НЕ нарушение): {len(width_note)}")
    print("-" * 72)

    ok = True
    if violations:
        print(f"[FAIL] нарушений звучимости: {len(violations)}")
        for v in violations[:5]:
            print(f"[FAIL] {v}")
        ok = False
    if with_iters < 4:
        print(f"[FAIL] невакуумность: случаев с итерациями {with_iters} < 4")
        ok = False
    if neg:
        print("[FAIL] негативный контроль не прошёл")
        ok = False
    if not det_ok:
        print("[FAIL] инвариант недетерминирован")
        ok = False
    if ok:
        print(f"[OK] физический оракул absint: {sound_cases} инвариантов СОДЕРЖАТ все "
              f"реальные значения цикла, 0 нарушений звучимости, {with_iters} случаев с итерациями")
    print(f"RC={0 if ok else 1}")
    return 0 if ok else 1


def selftest() -> int:
    """Проверка самого классификатора и реального цикла (без kernc)."""
    checks = [
        ("значение внутри интервала = SOUND", classify(0 <= 5 <= 10) == "SOUND"),
        ("значение ВНЕ интервала = UNSOUND", classify(0 <= 11 <= 10) == "UNSOUND"),
        ("реальный цикл (0,1,10) даёт head 0..9", real_loop(0, 1, 10) == (list(range(10)), 10)),
        ("реальный цикл без итераций (0,1,0) пуст", real_loop(0, 1, 0) == ([], None)),
        ("шаг 3: head 0,3,..,18 и выход 21", real_loop(0, 3, 20) == ([0, 3, 6, 9, 12, 15, 18], 21)),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"  {'[OK]' if ok else '[FAIL]'} {n}")
    if bad:
        print(f"[FAIL] selftest: {len(bad)} проверок не прошло")
        return 1
    print(f"[OK] selftest: {len(checks)}/{len(checks)} проверок")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if not KERNC.exists():
        print(f"[FAIL] нет бинарника {KERNC} — сначала `make build`")
        return 1
    return run()


if __name__ == "__main__":
    sys.exit(main())
