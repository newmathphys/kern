#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN gate: NIST Juliet-style PAIRED benchmark (bad vs good) for MITRE CWE classes.

ЧТО ЭТО. Эталон NIST SARD (Juliet Test Suite) проверяет инструмент ПАРОЙ
близнецов: `bad` — уязвимый код, `good` — ТОТ ЖЕ код с правильным защитным
гардом. Инструмент обязан поймать `bad` И НЕ обвинить `good`. Одиночный
`bad`-пример доказывает только чувствительность; пару — точность.

ЗАЧЕМ ПАРА, А НЕ ОДИНОЧНЫЙ ПРИМЕР. Дефект #178/#322: детектор, который
обвиняет ВСЕГДА, «находит» все уязвимости и бесполезен; детектор, который не
обвиняет НИКОГДА, бесполезен иначе. Пара ловит оба вырождения сразу: за
каждое пойманное `bad` и каждое НЕобвинённое `good` отвечает один и тот же
прогон движка.

ДВЕ МИРОВЫЕ МЕТРИКИ (обе обязаны быть идеальными, иначе гейт красный):

  1. ИНДЕКС ЮДЕНА (NIST SARD):  J = TPR - FPR, где TPR = TP/(TP+FN),
     FPR = FP/(FP+TN). Требуется J = 1.00: TP = 9/9, TN = 9/9, FP = 0, FN = 0.
  2. СЧЁТ SV-COMP: +1 за пойманный `bad`, +2 за ДОКАЗАННЫЙ `good`,
     -16 за ложную тревогу (FP), -32 за ложное доказательство (FN).
     Требуется 27 / 27 очков, штраф = 0.

ЧТО ИМЕННО СЧИТАЕТСЯ «ПОЙМАЛ» И «ДОКАЗАЛ» (без этого метрика — украшение):

  * `contracts`        — `bad`: строка `[FAIL]` (нарушение с контрпримером);
                         `good`: строка `[PASS]` и слово `ДОКАЗАНО`.
                         «ВНЕ ПОДМНОЖЕСТВА» и «НЕ РЕШЕНО» — НЕ доказательство
                         и НЕ оправдание: они считаются ПРОВАЛОМ `good`.
  * `xray`             — `bad`: есть `[BOUNDS PATH]`; `good`: его нет.
  * `kernc-prove`      — `bad`: `НЕ доказано`; `good`: `ДОКАЗАНО`.
  * `verify-sql`       — по ИМЕНИ функции: `[FAIL] <fn>:` / `[PASS] <fn>:`.
  * `noninterference`  — по ИМЕНИ функции: `[FAIL] <fn>:` / `[PASS] <fn>:`.

ЧЕГО ГЕЙТ НЕ УТВЕРЖДАЕТ (границы названы явно):

  * 🔴 ЭТО НЕ ОФИЦИАЛЬНЫЙ ДАТАСЕТ NIST SARD. Фикстуры — НАШИ собственные
    синтетические пары-близнецы (`audits/cwe_twins/`), моделирующие девять
    классов MITRE CWE. Официальные файлы NIST SARD (`CWE190_*_bad.c` /
    `_good.c` с их собственной разметкой) НЕ скачивались и в прогоне не
    участвуют. Поэтому слово «Juliet» из названия гейта УБРАНО: раньше
    `cwe-juliet-check` можно было прочитать как «мы прогнали Juliet», и это
    завышало бы заявку. Метрики (индекс Юдена, счёт SV-COMP) считаются по
    формулам этих наборов, но на НАШИХ парах — и это сказано здесь прямо.
  * Это НЕ полный NIST Juliet Suite (тысячи тестов). Это девять классов
    MITRE CWE, каждый — одной парой `bad`/`good` на НАШИХ боевых движках.
    Числа «9/9» относятся к этим девяти классам и не переносятся на весь SARD.
  * CWE-680 и CWE-190 используют ОДНО обязательство типа (диапазон типа); их
    различает КОНТЕКСТ (результат уходит в размер аллокации). NIST SARD
    разделяет их так же; пересечение названо, а не спрятано.
  * Гейт не проверяет КАЧЕСТВО гарда в `good` — только то, что движок его
    доказал. Плохой, но доказуемый гард пройдёт.

Запуск:  python3 tools/cwe_twins_check.py [--selftest]
Код возврата: 0 — J = 1.00 и счёт 27/27; 1 — иначе.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "audits" / "cwe_twins"

# Цена по официальному счёту SV-COMP.
PTS_BAD_CAUGHT = 1
PTS_GOOD_PROVEN = 2
PENALTY_FP = 16
PENALTY_FN = 32

# Класс: (CWE, короткое имя, движок, плохой вход, хороший вход)
# Для движков, где ОДИН файл содержит обе функции, bad/good — имена функций.
CLASSES = [
    ("CWE-190", "Integer Overflow", "contracts",
     "cwe190_bad.c", "cwe190_good.c"),
    ("CWE-191", "Integer Underflow", "contracts",
     "cwe191_bad.c", "cwe191_good.c"),
    ("CWE-369", "Divide By Zero", "contracts",
     "cwe369_bad.py", "cwe369_good.py"),
    ("CWE-682", "Hardware idiv trap (INT_MIN / -1, INT_MIN % -1)", "contracts",
     "cwe682_bad.c", "cwe682_good.c"),
    ("CWE-680", "Integer Overflow to Buffer Size", "contracts",
     "cwe680_bad.c", "cwe680_good.c"),
    ("CWE-125/193", "Out-of-Bounds / Off-by-One", "xray",
     "cwe125_bad.py", "cwe125_good.py"),
    ("CWE-22", "Path Traversal", "kernc-prove",
     "cwe22_bad.smt2", "cwe22_good.smt2"),
    ("CWE-89/285", "SQL / RLS tenant bypass", "verify-sql",
     "cwe89_sql.py", "cwe89_sql.py"),
    ("CWE-208", "Timing side-channel on a secret", "noninterference",
     "cwe208_timing.py", "cwe208_timing.py"),
]

# Функции для движков, работающих по имени (SQL, non-interference).


def run(engine: str, path: Path) -> str:
    py = sys.executable
    if engine == "kernc-prove":
        cmd = [str(ROOT / "zig-out" / "bin" / "kernc"), "prove", str(path)]
    elif engine == "xray":
        cmd = [py, str(ROOT / "tools" / "kern_contracts.py"), "--xray", str(path)]
    elif engine == "verify-sql":
        cmd = [py, str(ROOT / "tools" / "kern_contracts.py"),
               "--verify-sql", str(path)]
    elif engine == "noninterference":
        cmd = [py, str(ROOT / "tools" / "kern_contracts.py"),
               "--noninterference", str(path)]
    else:
        cmd = [py, str(ROOT / "tools" / "kern_contracts.py"), str(path)]
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                       timeout=900)
    return r.stdout + r.stderr


def verdict_contracts(bad_out: str, good_out: str) -> tuple[bool, bool]:
    """(bad пойман, good ДОКАЗАН). «ВНЕ ПОДМНОЖЕСТВА» — НЕ доказательство.

    ДЕФЕКТ собственной реализации, найденный ПЕРВЫМ прогоном гейта: обе ветви
    считались по `bad_out`, поэтому `good` «доказывался» выводом уязвимого
    файла (матрица показала `TP/FP` на всех контрактных классах при живых
    `[PASS]`). Исправлено: `caught` — из вывода `bad`, `proven` — из вывода
    `good`. Это ровно та ошибка, против которой гейт и построен: метрика,
    считающая не то, что заявляет.
    """
    caught = "[FAIL]" in bad_out
    proven = "[PASS]" in good_out and "ДОКАЗАНО" in good_out
    return caught, proven


def verdict_named(out: str, bad_fn: str, good_fn: str) -> tuple[bool, bool]:
    """По ИМЕНИ функции: `[FAIL] <fn>:` / `[PASS] <fn>:`."""
    caught = re.search(rf"\[FAIL\]\s+{re.escape(bad_fn)}\s*:", out) is not None
    proven = re.search(rf"\[PASS\]\s+{re.escape(good_fn)}\s*:", out) is not None
    return caught, proven


def evaluate(cls) -> dict:
    cwe, title, engine, bad_f, good_f = cls
    bad_p, good_p = FIX / bad_f, FIX / good_f
    if not bad_p.exists() or not good_p.exists():
        miss = bad_f if not bad_p.exists() else good_f
        return {"cwe": cwe, "title": title, "engine": engine,
                "error": f"нет фикстуры: {miss}"}

    bad_out = run(engine, bad_p)
    good_out = bad_out if bad_p == good_p else run(engine, good_p)

    if engine == "xray":
        caught = "[BOUNDS PATH]" in bad_out
        proven = "[BOUNDS PATH]" not in good_out
    elif engine == "kernc-prove":
        caught = "НЕ доказано" in bad_out
        proven = "ДОКАЗАНО" in good_out
    elif engine in FUNCS:
        bf, gf = FUNCS[engine]
        caught, proven = verdict_named(bad_out, bf, gf)
    else:
        caught, proven = verdict_contracts(bad_out, good_out)

    return {"cwe": cwe, "title": title, "engine": engine,
            "caught": caught, "proven": proven}


def score(results: list[dict]) -> dict:
    """Индекс Юдена и официальный счёт SV-COMP по результатам пар."""
    tp = sum(1 for r in results if r.get("caught"))
    fn = sum(1 for r in results if not r.get("caught"))
    tn = sum(1 for r in results if r.get("proven"))
    fp = sum(1 for r in results if not r.get("proven"))
    tpr = tp / (tp + fn) if (tp + fn) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    points = (tp * PTS_BAD_CAUGHT + tn * PTS_GOOD_PROVEN
              - fp * PENALTY_FP - fn * PENALTY_FN)
    max_points = len(results) * (PTS_BAD_CAUGHT + PTS_GOOD_PROVEN)
    return {"tp": tp, "fn": fn, "tn": tn, "fp": fp,
            "tpr": tpr, "fpr": fpr, "juden": tpr - fpr,
            "points": points, "max_points": max_points}

FUNCS = {
    "verify-sql": ("rls_buggy", "rls_safe"),
    "noninterference": ("check_pin_leaky", "constant_time_op"),
}


def selftest() -> int:
    """Мета-тест: гейт обязан покраснеть, если метрика перестала быть идеальной.

    Ветки: (1) идеальный набор проходит; (2) пропущенный `bad` (FN) красит
    гейт; (3) обвинённый `good` (FP) красит гейт; (4) штраф SV-COMP
    действительно отрицательный (метрика не «всегда хорошая»).
    """
    bad = 0
    perfect = [{"cwe": f"C{i}", "caught": True, "proven": True}
               for i in range(9)]
    s = score(perfect)
    if abs(s["juden"] - 1.0) > 1e-9 or s["points"] != s["max_points"]:
        print(f"[FAIL] selftest: идеальный набор не даёт J=1.00 / 27 очков: {s}")
        bad += 1
    else:
        print("[OK] selftest: идеальный набор даёт J=1.00 и 27/27")

    missed = [dict(r) for r in perfect]
    missed[0]["caught"] = False                      # FN
    s = score(missed)
    if s["juden"] >= 1.0 or s["points"] >= s["max_points"]:
        print("[FAIL] selftest: пропущенный `bad` (FN) НЕ испортил метрику")
        bad += 1
    else:
        print(f"[OK] selftest: FN ловится (J={s['juden']:.3f}, "
              f"очки={s['points']}/{s['max_points']})")

    accused = [dict(r) for r in perfect]
    accused[0]["proven"] = False                     # FP
    s = score(accused)
    if s["juden"] >= 1.0 or s["points"] >= s["max_points"]:
        print("[FAIL] selftest: обвинённый `good` (FP) НЕ испортил метрику")
        bad += 1
    else:
        print(f"[OK] selftest: FP ловится (J={s['juden']:.3f}, "
              f"очки={s['points']}/{s['max_points']})")

    empty = score([])
    if empty["juden"] != 0.0:
        print("[FAIL] selftest: пустой набор дал ненулевой индекс")
        bad += 1
    else:
        print("[OK] selftest: пустой набор — честный ноль, а не деление на ноль")
    print(f"[{'OK' if bad == 0 else 'FAIL'}] cwe-twins selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in args:
        return selftest()

    print("=" * 74)
    print("KERN: ПАРНЫЙ БЕНЧМАРК CWE-БЛИЗНЕЦОВ (bad vs good) — MITRE CWE")
    print("=" * 74)
    print("  [!] ПРОИСХОЖДЕНИЕ ФИКСТУР: это НАШИ синтетические пары-близнецы")
    print("      (`audits/cwe_twins/`), а НЕ официальный датасет NIST SARD.")
    print("      Официальные файлы SARD не скачивались и в прогоне не участвуют.")
    print("      Формулы метрик (индекс Юдена, счёт SV-COMP) — официальные,")
    print("      но считаются по НАШИМ девяти парам, а не по всему SARD.")
    results = []
    for cls in CLASSES:
        r = evaluate(cls)
        results.append(r)
        if r.get("error"):
            print(f"  [ERR ] {r['cwe']:12} {r['title'][:34]:36} {r['error']}")
            continue
        mark = "TP" if r["caught"] else "FN"
        mark2 = "TN" if r["proven"] else "FP"
        print(f"  [{mark}/{mark2}] {r['cwe']:12} {r['title'][:34]:36} "
              f"движок={r['engine']}")
    errors = [r for r in results if r.get("error")]
    if errors:
        print(f"\n[FAIL] фикстур нет: {len(errors)} — метрика НЕ считается")
        return 1

    s = score(results)
    print("-" * 74)
    print(f"  Индекс Юдена (NIST SARD) : J = TPR - FPR = {s['tpr']:.3f} - "
          f"{s['fpr']:.3f} = {s['juden']:.2f}   (требуется 1.00)")
    print(f"  Матрица                  : TP {s['tp']}/9 · TN {s['tn']}/9 · "
          f"FP {s['fp']} · FN {s['fn']}")
    print(f"  Счёт SV-COMP             : {s['points']} / {s['max_points']} "
          f"(штраф {s['max_points'] - s['points']})")
    ok = (abs(s["juden"] - 1.0) < 1e-9 and s["points"] == s["max_points"]
          and s["fp"] == 0 and s["fn"] == 0)
    if not ok:
        print("\n[FAIL] метрики НЕ идеальны: ложное обвинение `good` или "
              "пропуск `bad` — это цена, а не украшение.")
        return 1
    print("\n[OK] 9/9 классов: каждый `bad` ПОЙМАН, каждый `good` ДОКАЗАН; "
          "J = 1.00, счёт 27/27, штраф 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())

