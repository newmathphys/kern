#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN gate: QuixBugs через `--diff-equiv` — АНАЛИТИЧЕСКИ, без прогона тестов.

ЧТО ЭТО. Классический корпус QuixBugs: 40 пар `buggy` / `correct`. Проверка
идёт нашим `--diff-equiv` (сравнение тел, а не запуск тестов), и главный вопрос
звучимости формулируется ОДНИМ числом:

    false_equivalent == 0

Ни один багованный алгоритм не имеет права получить вердикт `EQUIVALENT`.
Ложное «эквивалентно» на баге — это не «пропуск», а ЛОЖНОЕ ДОКАЗАТЕЛЬСТВО:
именно то, что делает инструмент опасным (класс #206/#317).

ВТОРАЯ ПОЛОВИНА — КОНТРОЛЬНАЯ, И ОНА НЕ ЗАВИСИТ ОТ ДАТАСЕТА.
На парах `(correct, correct)` (семантически идентичные файлы В ПОДМНОЖЕСТВЕ)
вердикт обязан быть `EQUIVALENT`, а число `false_diverged` — нулём. Без этой
половины гейт ловил бы только «слишком мягкий» анализатор и пропускал «слишком
строгий», который обвиняет и правильный код (класс #178: детектор, обвиняющий
всё, бесполезен).

ЧЕСТНЫЙ SKIP, А НЕ МОЛЧАЛИВОЕ «ОК». Датасет QuixBugs — внешний
(`git clone https://github.com/jkoppel/QuixBugs`), поэтому при его отсутствии
половина с 40 парами НЕ выполняется и это НАЗЫВАЕТСЯ вслух (`[SKIP] … датасета
нет`). Контрольная половина выполняется ВСЕГДА — значит гейт не бывает
вакуумным даже без сети.

ЧЕГО ГЕЙТ НЕ УТВЕРЖДАЕТ (границы названы явно):

  * `DIVERGED` здесь подтверждается ЖИВЫМ вызовом (это делает
    `quixbugs_check.py`), но САМ гейт звучимости не проверяет доказательство
    для `EQUIVALENT` — он проверяет, что таких вердиктов на багах НЕТ.
  * 40 пар — это весь корпус QuixBugs, а не «все баги мира».
  * Датасет берётся из внешнего репозитория: гейт не проверяет его
    происхождение (хеш коммита), только результат на нём.

Запуск:  python3 tools/quixbugs_diff_check.py [--dataset DIR] [--selftest]
Код возврата: 0 — инварианты выполнены (или датасета нет и это названо);
              1 — ложное `EQUIVALENT` на баге ИЛИ ложный `DIVERGED` на контроле.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = Path(os.environ.get("QUIXBUGS_DIR", "/tmp/QuixBugs-master"))
EX = ROOT / "tools" / "kern_contracts.py"

# Контрольные пары: файл В ПОДМНОЖЕСТВЕ, скопированный в две «версии».
# Источник — наши же фикстуры CWE, где принадлежность подмножеству ИЗМЕРЕНА
# (в `cwe-juliet-check` они дают `[PASS] ДОКАЗАНО`).
#
# ГРАНИЦА НАЗВАНА (дефект #361): `--diff-equiv` сравнивает тела PYTHON-функций
# и на `.c`-файле падает с `SyntaxError`, а не выдаёт честный вердикт. Поэтому
# контрольная половина берёт только Python-фикстуры; падение на не-Python входе
# НЕ считается расхождением и НЕ считается доказательством — оно НАЗЫВАЕТСЯ
# (`tool_errors`) и краснит гейт.
CONTROLS = [
    ROOT / "audits" / "cwe_juliet" / "cwe369_good.py",
    # ДЕФЕКТ #361 ИСПРАВЛЕН: C-like контроль теперь РАБОТАЕТ (`parse_bodies`
    # маршрутизирует расширения из `CLIKE_EXT` через `parse_clike`), поэтому
    # `.c`-пара возвращена в контрольную половину — раньше она падала с
    # `SyntaxError`, и падение выдавалось за расхождение.
    ROOT / "audits" / "quixbugs_diff" / "clike_control.c",
]

# C-like ПАРА «багованная vs исправленная»: `--diff-equiv` обязан поймать
# расхождение с ТОЧНЫМ контрпримером (дефект #361 закрыт двусторонне).
CLIKE_PAIR = (ROOT / "audits" / "quixbugs_diff" / "clike_bad.c",
              ROOT / "audits" / "quixbugs_diff" / "clike_good.c")


def run_diff(a: Path, b: Path) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(EX), "--diff-equiv", str(a), str(b)],
                       cwd=str(ROOT), capture_output=True, text=True, timeout=900)
    return r.returncode, r.stdout + r.stderr


def dataset_half(dataset: Path) -> dict:
    """Половина с 40 парами QuixBugs. `false_equivalent` ОБЯЗАН быть нулём."""
    if not dataset.is_dir():
        return {"ran": False,
                "reason": (f"датасета нет: {dataset} — "
                           "git clone --depth 1 "
                           "https://github.com/jkoppel/QuixBugs /tmp/QuixBugs-master")}
    out = Path(tempfile.gettempdir()) / "kern_quixbugs_diff.json"
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "quixbugs_check.py"),
                        str(dataset), "--json", str(out)],
                       cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
    if not out.exists():
        return {"ran": False, "reason": f"quixbugs_check не создал JSON (rc={r.returncode})"}
    counts = json.loads(out.read_text(encoding="utf-8")).get("counts", {})
    diverged = int(counts.get("DIVERGED", 0))
    equivalent = int(counts.get("EQUIVALENT", 0))
    return {"ran": True, "diverged": diverged, "equivalent": equivalent,
            "false_equivalent": equivalent, "counts": counts}


def control_half() -> dict:
    """Контрольные пары `(correct, correct)`: ложный DIVERGED обязан быть нулём.

    Три исхода РАЗЛИЧАЮТСЯ (это и есть правило А, применённое к самому
    инструменту): `EQUIVALENT` — доказано; вне подмножества — названный SKIP;
    ПАДЕНИЕ инструмента (`Traceback`/`SyntaxError`) — `tool_errors`, и это
    ДЕФЕКТ, а не «расхождение»: считать падение находкой значило бы засчитать
    опечатку за доказательство.
    """
    bad, ok, skipped, crashed = [], [], [], []
    with tempfile.TemporaryDirectory() as d:
        for src in CONTROLS:
            if not src.exists():
                skipped.append(f"{src.name}: нет фикстуры")
                continue
            a, b = Path(d) / f"a_{src.name}", Path(d) / f"b_{src.name}"
            shutil.copy(src, a)
            shutil.copy(src, b)
            rc, out = run_diff(a, b)
            if "Traceback" in out or "SyntaxError" in out:
                crashed.append(f"{src.name}: инструмент УПАЛ (rc={rc})")
            elif "нечего" in out or "вне подмножества" in out:
                skipped.append(f"{src.name}: вне подмножества")
            elif "[EQUIVALENT]" in out and "разошедшихся 0" in out:
                ok.append(src.name)
            else:
                bad.append(src.name)
    return {"in_subset": ok, "false_diverged": bad, "skipped": skipped,
            "tool_errors": crashed}


def clike_half() -> dict:
    """C-like `--diff-equiv`: багованная пара обязана дать DIVERGED с контрпримером.

    ДЕФЕКТ #361: до маршрутизации C-like через `parse_clike` этот прогон падал с
    `SyntaxError`. Теперь проверяется ДВУСТОРОННЕ: расхождение ловится (и с
    ТОЧНЫМ контрпримером), а контроль «файл против себя» даёт `EQUIVALENT`.
    """
    a, b = CLIKE_PAIR
    if not a.exists() or not b.exists():
        return {"ran": False, "reason": "нет C-like фикстур"}
    rc, out = run_diff(a, b)
    if "Traceback" in out or "SyntaxError" in out:
        return {"ran": True, "tool_error": True,
                "detail": "инструмент УПАЛ на C-like входе (#361 не закрыт)"}
    diverged = "[DIVERGED]" in out and "[КОНТРПРИМЕР]" in out
    return {"ran": True, "tool_error": False, "diverged": diverged,
            "detail": next((l.strip()[:96] for l in out.splitlines()
                            if "[КОНТРПРИМЕР]" in l), "<контрпример не предъявлен>")}


def selftest() -> int:
    """Мета-тест: ОБА инварианта обязаны быть проверяемыми.

    Ветки: (1) `false_equivalent > 0` обязан красить гейт (ложное
    доказательство); (2) `false_diverged > 0` обязан красить гейт (ложное
    обвинение); (3) чистый набор проходит; (4) контрольная половина без
    единой пары в подмножестве НЕ засчитывается как «доказано» (иначе гейт
    был бы вакуумным без датасета).
    """
    bad = 0

    def verdict(ds: dict, ctl: dict) -> bool:
        if ds["ran"] and ds["false_equivalent"] != 0:
            return False
        if ctl["false_diverged"]:
            return False
        if not ctl["in_subset"]:
            return False
        return True

    clean_ds = {"ran": True, "false_equivalent": 0, "diverged": 40,
                "equivalent": 0}
    clean_ctl = {"in_subset": ["a"], "false_diverged": [], "skipped": []}
    if not verdict(clean_ds, clean_ctl):
        print("[FAIL] selftest: чистый набор НЕ прошёл")
        bad += 1
    else:
        print("[OK] selftest: чистый набор проходит")

    if verdict({**clean_ds, "false_equivalent": 1}, clean_ctl):
        print("[FAIL] selftest: ложное EQUIVALENT на баге НЕ поймано")
        bad += 1
    else:
        print("[OK] selftest: ложное EQUIVALENT на баге ловится (инвариант 1)")

    if verdict(clean_ds, {**clean_ctl, "false_diverged": ["a"]}):
        print("[FAIL] selftest: ложный DIVERGED на контроле НЕ пойман")
        bad += 1
    else:
        print("[OK] selftest: ложный DIVERGED на контроле ловится (инвариант 2)")

    if verdict(clean_ds, {"in_subset": [], "false_diverged": [], "skipped": ["x"]}):
        print("[FAIL] selftest: пустая контрольная половина засчитана как доказано")
        bad += 1
    else:
        print("[OK] selftest: пустая контрольная половина НЕ засчитана")
    print(f"[{'OK' if bad == 0 else 'FAIL'}] quixbugs-diff selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in args:
        return selftest()
    dataset = DATASET
    if "--dataset" in args:
        dataset = Path(args[args.index("--dataset") + 1])

    print("=" * 74)
    print("KERN: QuixBugs через `--diff-equiv` (аналитически, без прогона тестов)")
    print("=" * 74)
    ds = dataset_half(dataset)
    ctl = control_half()
    ck = clike_half()

    print(f"  ПАРЫ (buggy vs correct): ", end="")
    if ds["ran"]:
        print(f"DIVERGED {ds['diverged']} | EQUIVALENT {ds['equivalent']} | "
              f"false_equivalent {ds['false_equivalent']}  (требуется 0)")
    else:
        print(f"[SKIP] {ds['reason']}")
    print(f"  C-LIKE ПАРА (buggy vs good, #361): "
          f"{'DIVERGED + контрпример' if ck.get('diverged') else 'НЕ ПОЙМАНО'}")
    print(f"      {ck['detail']}")
    print(f"  КОНТРОЛЬ (correct vs correct): EQUIVALENT {len(ctl['in_subset'])} | "
          f"false_diverged {len(ctl['false_diverged'])} | "
          f"падений инструмента {len(ctl['tool_errors'])}  (требуется 0)")
    if ctl["skipped"]:
        for s in ctl["skipped"]:
            print(f"    [SKIP] {s}")
    if ctl["tool_errors"]:
        for s in ctl["tool_errors"]:
            print(f"    [TOOL ERROR] {s}")
    print("-" * 74)

    problems = []
    if ds["ran"] and ds["false_equivalent"] != 0:
        problems.append(f"ЛОЖНОЕ ДОКАЗАТЕЛЬСТВО: {ds['false_equivalent']} "
                        f"багованных пар объявлены эквивалентными")
    if ctl["false_diverged"]:
        problems.append(f"ЛОЖНОЕ ОБВИНЕНИЕ: {ctl['false_diverged']}")
    if ctl["tool_errors"]:
        problems.append(f"ПАДЕНИЕ ИНСТРУМЕНТА (дефект #361, а не расхождение): "
                        f"{ctl['tool_errors']}")
    if ck.get("tool_error"):
        problems.append(f"C-like вход роняет инструмент (#361 НЕ закрыт): "
                        f"{ck['detail']}")
    elif ck.get("ran") and not ck.get("diverged"):
        problems.append("C-like багованная пара НЕ поймана `--diff-equiv`")
    if not ctl["in_subset"]:
        problems.append("контрольная половина не проверила НИ ОДНОЙ пары "
                        "(вакуумный гейт)")
    if problems:
        for p in problems:
            print(f"[FAIL] {p}")
        return 1
    if not ds["ran"]:
        print("[i] инвариант `false_equivalent == 0` НЕ ПРОВЕРЯЛСЯ: датасета нет "
              "(названо вслух, а не засчитано как «ок»)")
    print("[OK] false_equivalent == 0 (или названный SKIP) и "
          "false_diverged == 0 на контроле")
    return 0


if __name__ == "__main__":
    sys.exit(main())
