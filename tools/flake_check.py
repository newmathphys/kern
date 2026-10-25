#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Детектор ФЛЕЙКИ: одна цель, два разных вердикта при неизменном дереве = `B`.

ЗАЧЕМ. `determinism_check` проверяет детерминизм РЕШАТЕЛЯ (один SMT-вход —
один вердикт). Стабильность НАБОРА ГЕЙТОВ не проверялась ничем: цель, которая
сегодня зелёная, а завтра красная при том же дереве, обесценивает оба прогона —
и по нашей же семантике это НЕ «нестабильность», а ПРОТИВОРЕЧИЕ: два
противоречащих свидетельства складываются в `B(1,1)` (`joinK(T, F) = B`), и это
означает «нельзя доверять ни одному из прогонов», а не «флейк».

ЧТО ДЕЛАЕТ. Прогоняет набор целей N раз подряд и сравнивает вердикт КАЖДОЙ
цели между прогонами. Любое расхождение -> вердикт `B` для этой цели, ненулевой
код возврата и список расхождений.

ЧЕСТНАЯ ГРАНИЦА. Сравнивается вердикт ЦЕЛИ, а не отдельного теста: раннер Zig
не печатает построчный список тестов (общается с билд-раннером через
`--listen=-`), поэтому единица наблюдения — цель. Кейсы canfail построчны, но их
144, и N прогонов полного харнесса несовместимы с быстрым контуром.

Запуск:  python3 tools/flake_check.py [--runs 3] [--selftest]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Быстрый, но содержательный набор: цели, которые проверяют РАЗНЫЕ подсистемы.
# Специально не берём долгие (canfail, conformance): их нестабильность была бы
# шумом таймаутов, а не признаком флейки.
TARGETS = (
    "metrics-guard",
    "sync-check",
    "docs-parity",
    "status-check",
    "llms-check",
    "temp-isolation-check",
    "charter-check",
)


def run_target(name: str, timeout: int = 300) -> int:
    r = subprocess.run(["make", name], cwd=ROOT, capture_output=True,
                       text=True, timeout=timeout)
    return r.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        # Селфтест: классификатор обязан поймать поддельный флейк.
        verdicts = {"T": ["0", "0", "0"], "B": ["0", "2", "0"]}
        errs = []
        if classify(verdicts["T"]) != "T":
            errs.append("стабильная цель определена не как T")
        if classify(verdicts["B"]) != "B":
            errs.append("расхождение вердиктов не определено как B")
        if errs:
            print("SELFTEST FAILED:", "; ".join(errs))
            return 1
        print("SELFTEST PASSED: T и B различаются")
        return 0

    print(f"ДЕТЕКТОР ФЛЕЙКИ: {len(TARGETS)} целей x {args.runs} прогонов")
    obs: dict[str, list[str]] = {t: [] for t in TARGETS}
    for i in range(args.runs):
        for t in TARGETS:
            obs[t].append(str(run_target(t)))
        print(f"  прогон {i + 1}/{args.runs} завершён", flush=True)

    flaky = []
    broken = []
    for t in TARGETS:
        v = classify(obs[t])
        mark = "OK " if v == "T" else ("B  " if v == "B" else "F  ")
        print(f"  [{mark}] {t}: {'/'.join(obs[t])} -> {v}")
        if v == "B":
            flaky.append((t, obs[t]))
        elif v == "F":
            broken.append((t, obs[t]))

    print()
    # ДЕФЕКТ #357: раньше ЛЮБОЙ не-T вердикт назывался «флейком», включая F —
    # «стабильно нарушено». Это подмена: цель, красная ВО ВСЕХ прогонах, не
    # флейк, а СЛОМАННАЯ цель, и причина у неё другая (реальное расхождение, а
    # не недетерминизм). Смешение двух классов прятало диагноз: сообщение
    # «дала РАЗНЫЕ вердикты» было ЛОЖЬЮ при одинаковых кодах. Теперь классы
    # называются раздельно; красный вердикт гейта сохраняется в обоих случаях.
    if broken:
        print(f"СЛОМАННЫЕ ЦЕЛИ: {len(broken)} — красные во ВСЕХ прогонах "
              f"(коды {'/'.join(broken[0][1])} и т. п.).")
        print("Это НЕ флейк: причина детерминирована, ищите расхождение, "
              "а не недетерминизм.")
    if flaky:
        print(f"ФЛЕЙКИ: {len(flaky)} — цель дала РАЗНЫЕ вердикты при "
              f"неизменном дереве.")
        print("По семантике KERN это B(1,1): два противоречащих свидетельства,")
        print("и ни одному из прогонов нельзя доверять, пока причина не найдена.")
    if broken or flaky:
        return 1
    print(f"ФЛЕЙКОВ НЕТ: все {len(TARGETS)} целей дали одинаковый вердикт "
          f"во всех {args.runs} прогонах")
    return 0


def classify(codes: list[str]) -> str:
    """Вердикт цели по её кодам возврата в N прогонах.

    T — все прогоны зелёные (стабильно доказано); F — все красные (стабильно
    нарушено); B — РАСХОЖДЕНИЕ (противоречие: `joinK(T, F) = B`).
    """
    uniq = set(codes)
    if uniq == {"0"}:
        return "T"
    if len(uniq) == 1:
        return "F"
    return "B"


if __name__ == "__main__":
    sys.exit(main())
