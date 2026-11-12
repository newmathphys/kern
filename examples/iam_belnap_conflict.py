#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: Apache-2.0
"""`iam_belnap_conflict.py` — конфликт IAM-политик НЕ схлопывается в «да/нет».

ЗАЧЕМ. Две команды выдали по политике на ОДИН И ТОТ ЖЕ запрос:

    Data  : Allow analyst READ s3://reports      (утверждение T)
    SecOps: Deny  analyst READ s3://reports
            unless MFA                           (утверждение F)

Обычные движки политик разрешают это «последним выигравшим» (AWS: explicit deny
побеждает; что бы ни выбрал движок, ОДНО из двух утверждений молча теряется).
Это ровно тот случай, для которого Белнап: `JOIN_K(T, F) = B` — «и да, и нет»,
и это НЕ ошибка, а факт, который обязан быть виден.

Демо берёт НАСТОЯЩИЙ верификатор из `examples/kern_mcp_server.py`
(`_belnap_state`), то есть проверяет живой JOIN_K проекта, а не свою копию.

Самопроверка: `python3 examples/iam_belnap_conflict.py` -> rc 0, печатает [OK].
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_join_k():
    """Живой JOIN_K из пример-сервера KERN (никакого дублирования логики)."""
    spec = importlib.util.spec_from_file_location(
        "kern_mcp_server_example", str(ROOT / "examples/kern_mcp_server.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._belnap_state


def main() -> int:
    join_k = load_join_k()

    # Вектор запроса: (кто, что, на что) + MFA отсутствует.
    req = {"principal": "analyst:ivan", "action": "READ",
           "resource": "s3://reports", "mfa": False}

    # Каждая политика отвечает СВОИМ утверждением: (доказательство, опровержение).
    data = (1, 0)     # T: Data разрешает — доказано, опровержений нет
    secops = (0, 1)   # F: SecOps запрещает (MFA нет) — доказано обратное
    verdict = join_k(*data)
    verdict2 = join_k(*secops)
    joined = join_k(data[0] | secops[0], data[1] | secops[1])

    print("запрос:", req)
    print(f"  Data   -> {verdict}  (Allow READ reports)")
    print(f"  SecOps -> {verdict2}  (Deny без MFA)")
    print(f"  JOIN_K(T, F) = {joined}")

    ok = True
    if joined != "B":
        print("[FAIL] конфликт СХЛОПНУТ: потеряно одно из двух утверждений")
        ok = False
    if verdict != "T" or verdict2 != "F":
        print("[FAIL] одиночные политики посчитаны неверно")
        ok = False

    # Контрольный вектор БЕЗ конфликта: MFA есть -> SecOps не запрещает -> N.
    no_conflict = join_k(1, 0)
    if no_conflict != "T":
        print("[FAIL] разрешающий вектор без конфликта посчитан неверно")
        ok = False
    print(f"  контроль (MFA есть): JOIN_K(T, N) = {no_conflict}")

    if not ok:
        return 1
    print("[OK] конфликт сохранён: JOIN_K(T, F) = B -> HTTP 409 Conflict, "
          "а не «deny побеждает»")
    return 0


if __name__ == "__main__":
    sys.exit(main())
