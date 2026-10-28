#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# SPDX-License-Identifier: LicenseRef-KERN-Proprietary
"""ФИЗИЧЕСКИЙ ОРАКУЛ для DTMC (шаг D плана).

ЗАЧЕМ. Семейство `dtmc` до этого шага проверялось МОДЕЛЬ ПРОТИВ МОДЕЛИ: KERN
считает вероятность по своей матрице и сам же её подтверждает. Это вакуум —
компьютер подтверждает себе, что его формулы непротиворечивы, и ничего не
говорит о реальности.

ЧТО ДЕЛАЕТ ЭТОТ ОРАКУЛ. Берёт ТУ ЖЕ матрицу переходов и **реально симулирует**
случайные блуждания (`random.random()`, фиксированный seed → детерминизм).
Эмпирическая частота обязана совпасть с аналитической вероятностью в пределах
статистического допуска. Это внешний арбитр: симуляция не знает формул KERN.

ТРИ СВОЙСТВА (без любого из них проверка бессмысленна):
  1. СОВПАДЕНИЕ: |эмпирика - аналитика| <= допуск (по сигме, а не «на глаз»);
  2. НЕВАКУУМНОСТЬ: аналитика НЕ 0 и НЕ 1 — иначе сравнение тривиально
     (для 0 и 1 любая симуляция «совпадёт» с точностью до одного исхода);
  3. НЕГАТИВНЫЙ КОНТРОЛЬ: заведомо неверное значение (0.5 при 0.01) обязано
     быть ОТВЕРГНУТО — иначе допуск настолько широк, что проверка фиктивна.
"""
from __future__ import annotations

import math
import random
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"

# Матрица: 0 = старт, 1 = ПРОВАЛ (поглощающий), 2 = успех (поглощающий).
# Строка i = переходы ИЗ состояния i.
N = 3
TARGET = 1          # «достичь ПРОВАЛА»
P_FAIL = 0.01
MATRIX = [
    [0.0, P_FAIL, 1.0 - P_FAIL],
    [0.0, 1.0, 0.0],
    [0.0, 0.0, 1.0],
]
WALKS = 10_000
SEED = 20261027      # фиксированный: два прогона обязаны дать ОДИН результат


def spec_text() -> str:
    vals = " ".join(f"{v:g}" for row in MATRIX for v in row)
    return ("# смещённая монета: 0=старт, 1=ПРОВАЛ (поглощающий), 2=успех\n"
            "# строка i = переходы ИЗ состояния i\n"
            f"dtmc reach {N} {TARGET} {vals}\n")


def analytic_probability() -> tuple[float | None, str]:
    """Аналитическая P из ЯДРА (`kernc theory`), не из Python."""
    spec = ROOT / "tests" / "fixtures" / "oracles" / "dtmc_coin.txt"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(spec_text(), encoding="utf-8")
    try:
        p = subprocess.run([str(KERNC), "theory", str(spec)], cwd=ROOT,
                           capture_output=True, text=True, errors="replace",
                           timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"kernc theory не запустился: {e}"
    out = p.stdout + p.stderr
    m = re.search(r"P\(достичь\s+(\d+)\s+из\s+(\d+)\)\s*=\s*([0-9.]+)", out)
    if not m:
        return None, f"не разобран вывод: {out.strip()[:200]}"
    if int(m.group(1)) != TARGET or int(m.group(2)) != 0:
        return None, f"ядро ответило про другую цель: {m.group(0)}"
    return float(m.group(3)), ""


def monte_carlo() -> float:
    """РЕАЛЬНАЯ симуляция: случайные блуждания по ТОЙ ЖЕ матрице."""
    rng = random.Random(SEED)
    hits = 0
    for _ in range(WALKS):
        s = 0
        for _step in range(1000):          # защита от незавершения
            if s == TARGET:
                hits += 1
                break
            if s == 2:                     # успех — поглощающий
                break
            r, acc, nxt = rng.random(), 0.0, s
            for j, pr in enumerate(MATRIX[s]):
                acc += pr
                if r <= acc:
                    nxt = j
                    break
            s = nxt
    return hits / WALKS


def main() -> int:
    print("=" * 74)
    print("ФИЗИЧЕСКИЙ ОРАКУЛ DTMC: реальная симуляция против аналитики ядра")
    print("=" * 74)
    p_analytic, err = analytic_probability()
    if p_analytic is None:
        print(f"[!] {err}")
        return 2
    p_emp = monte_carlo()
    sigma = math.sqrt(max(p_analytic * (1 - p_analytic), 1e-12) / WALKS)
    tol = max(4 * sigma, 0.004)
    diff = abs(p_emp - p_analytic)
    print(f"  аналитика ядра : P(достичь {TARGET} из 0) = {p_analytic:.6f}")
    print(f"  симуляция      : {WALKS} блужданий, seed={SEED} -> {p_emp:.6f}")
    print(f"  |разница|      : {diff:.6f}   допуск 4*sigma = {tol:.6f} (sigma={sigma:.6f})")
    bad = 0

    # 1. СОВПАДЕНИЕ
    if diff <= tol:
        print("  [OK] 1/3 совпадение: симуляция подтверждает аналитику")
    else:
        print(f"  [FAIL] 1/3 РАСХОЖДЕНИЕ: {p_emp:.6f} vs {p_analytic:.6f} > {tol:.6f}")
        bad += 1

    # 2. НЕВАКУУМНОСТЬ
    if 0.0 < p_analytic < 1.0:
        print("  [OK] 2/3 невакуумность: аналитика не 0 и не 1 (сравнение осмысленно)")
    else:
        print(f"  [FAIL] 2/3 ВАКУУМ: аналитика {p_analytic} тривиальна -> сравнение фиктивно")
        bad += 1

    # 3. НЕГАТИВНЫЙ КОНТРОЛЬ: заведомо неверное значение обязано быть отвергнуто
    wrong = 0.5
    if abs(wrong - p_analytic) > tol:
        print(f"  [OK] 3/3 негативный контроль: неверное {wrong} отвергается (|{wrong}-{p_analytic:.4f}|>{tol:.4f})")
    else:
        print("  [FAIL] 3/3 допуск настолько широк, что неверное значение принимается -> проверка фиктивна")
        bad += 1

    print("-" * 74)
    print(f"ИТОГ: {3 - bad}/3 свойств | провалов {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
