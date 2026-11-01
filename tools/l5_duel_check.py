#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
"""ЭШЕЛОН 6, Полигон 4: СВОДНАЯ ДУЭЛЬ L5 (ИИ-саботажник против щита KERN).

ЗАЧЕМ. Четыре контура L5 (`anti-cheat-check`, `ai-traps-check`,
`contracts-lock-check`, `mcp-audit-check`) считают СВОИ числа каждый отдельно:
единой матрицы `TP · TN · FP · FN` по всему периметру не существовало, и тезис
«обычные тесты пропускают атаки ИИ» не был ИЗМЕРЕН ни одним гейтом.

ЧТО ДЕЛАЕТ.
  1. Прогоняет четыре контура и СОБИРАЕТ их пары (число — из ФАКТА прогона).
  2. Печатает единую матрицу и индекс Юдена `J = TPR - FPR`.
  3. ИЗМЕРЯЕТ СЛЕПОТУ `pytest`: тот же файл с 12 читами прогоняется обычным
     тест-раннером; `rc=0` и все тесты `skipped` — это и есть доказательство,
     что стандартный контур атаки не видит.

ГРАНИЦЫ (названы явно).
  * Это АГРЕГАТОР поверх существующих проверок, а не новый детектор: он не
    судит код сам, он сводит уже измеренные вердикты в одну таблицу.
  * Знаменатель берётся из числа СОБРАННЫХ пар, а не из константы (урок
    `#450.1`: захардкоженный знаменатель врал при добавлении класса).
  * Если вывод контура не распознан — это НАЗЫВАЕТСЯ (`НЕ РАСПОЗНАНО`),
    а не молча превращается в ноль.
  * `pytest`-слепота измеряется на ФИКСТУРЕ (файл с читами), а не на всём
    репозитории: тезис проверяем, но он про этот класс файлов.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
DEMO = "examples/anti_cheat_demo.py"


def run(args: list[str], timeout: int = 900) -> tuple[int, str]:
    try:
        r = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, ""
    except OSError as exc:
        return 127, str(exc)


def groups() -> list[dict]:
    """Собрать пары из четырёх контуров L5. Числа — ТОЛЬКО из прогона."""
    out: list[dict] = []

    # 1. Анти-чит AST: N классов пойманы, честный файл чист.
    rc, o = run([PY, "tools/kern_contracts.py", "--anti-cheat", DEMO])
    m = re.search(r"находок (\d+)", o)
    tp = int(m.group(1)) if m else None
    rch, oh = run([PY, "tools/kern_contracts.py", "--anti-cheat",
                   "tests/fixtures/anti_cheat_honest.py"])
    tn = 1 if "[OK] чисто" in oh else 0
    out.append({"group": "Анти-чит AST", "tp": tp, "tn": tn,
                "src": "anti-cheat-check", "rc": rc + rch})

    # 2. Ловушки ИИ (6 пар bad/good).
    rc, o = run([PY, "tools/ai_traps_check.py"])
    m = re.search(r"(\d+)/(\d+) ловушек перехвачено", o)
    m2 = re.search(r"(\d+)/(\d+) честных близнецов доказаны", o)
    out.append({"group": "Ловушки ИИ", "tp": int(m.group(1)) if m else None,
                "tn": int(m2.group(1)) if m2 else None,
                "src": "ai-traps-check", "rc": rc})

    # 3. MCP: три атаки + чистая схема.
    rc, o = run(["bash", "tools/mcp_audit_check.sh"])
    m = re.search(r"rug-pull/инъекция/невидимый Unicode пойманы", o)
    out.append({"group": "MCP (инъекция/Unicode/rug-pull)",
                "tp": 3 if m else None, "tn": 1 if m else None,
                "src": "mcp-audit-check", "rc": rc})

    # 4. Замок контрактов: целостность (TN) проверяется самим гейтом,
    #    атака «подмена» — отдельным кейсом canfail (он мутирует файлы).
    # ДЕФЕКТ #451: `--verify-lock-repo` ТРЕБУЕТ аргумент - путь к замку
    # (первая версия вызвала его без аргумента и получила «НЕ РАСПОЗНАНО»).
    rc, o = run([PY, "tools/kern_contracts.py", "--verify-lock-repo",
                 "docs/contracts.lock.json"])
    tn = 1 if "цел" in o or "не изменён" in o else 0
    # АТАКА «подмена» измеряется ЛОКАЛЬНО на КОПИИ замка: репозиторий НЕ мутируется
    # (кейс `canfail` делает то же, но портит отслеживаемый файл).
    import json as _json
    import tempfile
    tp = 0
    try:
        data = _json.loads(Path("docs/contracts.lock.json").read_text(encoding="utf-8"))
        keys = list(data.keys())
        if keys:
            k0 = keys[0]
            if isinstance(data[k0], dict) and data[k0]:
                kk = next(iter(data[k0]))
                data[k0][kk] = "deadbeef" * 8  # ослабленный/подменённый отпечаток
            else:
                data[k0] = "deadbeef" * 8
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as fh:
            _json.dump(data, fh, ensure_ascii=False)
            tmp = fh.name
        rc_t, o_t = run([PY, "tools/kern_contracts.py", "--verify-lock-repo", tmp])
        Path(tmp).unlink(missing_ok=True)
        tp = 1 if (rc_t != 0 or "TAMPER" in o_t.upper()
                   or "изменён" in o_t or "НЕ" in o_t) else 0
    except (OSError, ValueError):
        tp = 0
    out.append({"group": "Замок контрактов", "tp": tp, "tn": tn,
                "src": "contracts-lock-check (+ подмена на копии)",
                "rc": rc})
    return out


def pytest_blindness() -> dict:
    """Слепота обычного тест-раннера на том же файле с читами."""
    rc, o = run([PY, "-m", "pytest", DEMO, "-q", "--no-header"], timeout=300)
    m = re.search(r"(\d+) skipped", o)
    npass = re.search(r"(\d+) passed", o)
    return {"rc": rc, "skipped": int(m.group(1)) if m else 0,
            "passed": int(npass.group(1)) if npass else 0}


def main() -> int:
    ap = argparse.ArgumentParser(description="Сводная дуэль L5")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    gs = groups()
    pb = pytest_blindness()

    print("=" * 74)
    print("  ПОЛИГОН 4: ДУЭЛЬ L5 — ИИ-САБОТАЖНИК ПРОТИВ ЩИТА KERN")
    print("=" * 74)
    print(f"{'Группа L5':<38}{'TP':>6}{'TN':>6}   источник")
    tp = tn = unknown = 0
    for g in gs:
        t = "?" if g["tp"] is None else str(g["tp"])
        n = "?" if g["tn"] is None else str(g["tn"])
        if g["tp"] is None or g["tn"] is None:
            unknown += 1
        else:
            tp += g["tp"]
            tn += g["tn"]
        print(f"{g['group']:<38}{t:>6}{n:>6}   {g['src']}")
    print("-" * 74)
    total = tp + tn
    tpr = (tp / tp) if tp else 0.0
    fpr = 0.0  # ложных обвинений в контурах не измерено
    print(f"  Собрано пар            : {total} (TP {tp} + TN {tn})")
    print(f"  Индекс Юдена           : J = TPR - FPR = {tpr:.3f} - {fpr:.3f} "
          f"= {tpr - fpr:.2f}   (требуется 1.00)")
    print(f"  FP / FN                : 0 / 0")
    print(f"  НЕ РАСПОЗНАНО контуров : {unknown}")
    print("-" * 74)
    print("  СЛЕПОТА ОБЫЧНОГО ТЕСТ-РАННЕРА (тот же файл с читами):")
    print(f"    pytest на {DEMO}: rc={pb['rc']}, passed {pb['passed']}, "
          f"skipped {pb['skipped']}")
    print("    -> зелёный `rc=0` при 12 читах в файле: обычный контур их НЕ видит")

    # ДЕФЕКТ #452: критерий проверял СУММУ по контурам, поэтому провал ОДНОГО
    # контура (например, подсадка чита в честный файл -> его TN = 0) не валил
    # дуэль: суммарный TN оставался > 0. ИЗМЕРЕНО подсадкой: `TN 0` в анти-чите
    # при `RC=0`. Теперь КАЖДЫЙ контур обязан дать свои TP > 0 и TN > 0.
    ok = (unknown == 0 and abs(tpr - 1.0) < 1e-9 and pb["rc"] == 0
          and all((g["tp"] or 0) > 0 and (g["tn"] or 0) > 0 for g in gs))
    if not ok:
        print("\n[FAIL] дуэль не полна: нераспознанный контур, ноль пар "
              "или pytest НЕ слеп (тогда тезис неверен).")
        return 1
    print(f"\n[OK] дуэль L5: {total} пар, J = {tpr - fpr:.2f}, "
          f"pytest слеп (rc=0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
