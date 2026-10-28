#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# SPDX-License-Identifier: LicenseRef-KERN-Proprietary
"""ФИЗИЧЕСКИЙ ОРАКУЛ для невмешательства / 2-Safety (шаг D плана).

ЗАЧЕМ. Семейство `noninterference` проверялось МОДЕЛЬ ПРОТИВ МОДЕЛИ: taint-анализ
по IR (`noninterference.analyze`) объявлял, что ветвление по секрету — утечка,
а `constantTimeEqual` — нет, и это принималось на веру. Вакуум: никто не сверял
утверждение модели с ФИЗИЧЕСКИМ временем исполнения.

ЧТО ДЕЛАЕТ ЭТОТ ОРАКУЛ.
  1. СТАТИЧЕСКИЙ слой — вердикт ядра `kernc theory` по IR-программам:
     утечки (ветвление / индекс памяти / переменное время над секретом) обязаны
     быть ОПРОВЕРГНУТЫ, а программы без влияния секрета — ДОКАЗАНЫ. Отдельно
     проверяется FAIL-CLOSED: неизвестная инструкция обязана дать SKIP
     (вердикта НЕТ), а не «доказано» (класс #385).
  2. ФИЗИЧЕСКИЙ слой — РЕАЛЬНОЕ время: проба `nonint-probe` вызывает настоящие
     `constantTimeEqual` и `earlyExitEqual` из `src/verifier/noninterference.zig`
     на 4096-байтовом секрете, отличающемся в РАЗНЫХ ПОЗИЦИЯХ (1 против 4096),
     и печатает отношение МИНИМУМОВ из N прогонов.
  3. СОГЛАСОВАНИЕ модели и реальности:
       * модель «нет утечки» + время не зависит от позиции → ПОДТВЕРЖДЕНО (safe);
       * модель «утечка»    + время ЗАВИСИТ от позиции    → ПОДТВЕРЖДЕНО (leak);
       * модель «нет утечки» + время зависит → ПРОПУСК (MISSED);
       * модель «утечка»    + время не зависит → ЛОЖНАЯ ТРЕВОГА.

ЧЕСТНАЯ ГРАНИЦА (и это не отговорка, а свойство метода).
  * ЭТО СТАТИСТИЧЕСКИЙ ОРАКУЛ: он измеряет РЕАЛЬНОЕ время и ПОДВЕРЖЕН ШУМУ
    ПЛАНИРОВЩИКА ОС. Поэтому используется только МИНИМУМ из N прогонов
    (минимум устойчив к вытеснению, тогда как сумма/среднее — нет), а вердикт
    никогда не объявляется доказательством невмешательства.
  * Измеряется РАЗНИЦА ДВУХ РЕАЛИЗАЦИЙ (constant-time против раннего выхода),
    а не «отсутствие утечки» в произвольной функции: доказать невмешательство
    для произвольного кода этот замер не может по построению.
  * Модель (IR) и реальность (Zig-функции) связаны ОПИСАННЫМ соответствием
    (см. MODELS ниже), а не автоматическим переводом кода в IR.

ИНВАРИАНТЫ: MISSED == 0 · FALSE_ALARM == 0 · оба класса ПОДТВЕРЖДЕНО присутствуют
(невакуумность) · статический вердикт детерминирован · негативный контроль
классификатора ловит ОБА класса ошибок.
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

# Порог «время НЕ зависит от позиции». Измерено: CT_RATIO = 1.00 (три прогона:
# 1.0025 / 1.0007 / 1.0052) → порог 3.0 с трёхкратным запасом на шум.
CT_MAX = 3.0
# Порог «время ЗАВИСИТ от позиции». Измерено: EE_RATIO = 62.1 (60.6 / 62.1 / 62.1)
# → порог 10.0 с шестикратным запасом.
EE_MIN = 10.0

# IR-модели двух РЕАЛЬНЫХ реализаций (описанное соответствие, не перевод кода):
#   constantTimeEqual — комбинирование БЕЗ ветвления по секрету (cmov) → утечки нет;
#   earlyExitEqual    — операция ПЕРЕМЕННОЙ ДЛИТЕЛЬНОСТИ над секретом (ранний выход)
#                       → утечка `variable_time`.
MODELS = {
    "constant-time": "S1 P2 C3:1:2",
    "early-exit": "S1 T1",
}

# Статический слой: (инструкции, ожидание, что именно ожидается)
LEAK_FIXTURES = [
    ("S1 B1", "branch"),
    ("S7 M7", "memory_index"),
    ("S1 T1", "variable_time"),
    ("S1 A2=1 B2", "branch"),
]
SAFE_FIXTURES = [
    "P1 B1",
    "S1 P1 B1",
    "S1 P2 C3:1:2",
    "S1 A2=1 P2 B2",
]
# FAIL-CLOSED: инструкция вне подмножества обязана дать SKIP, а не вердикт.
UNSUPPORTED_FIXTURES = [
    "S1 Q9",   # неизвестный код операции
    "Z1 B1",   # неизвестный код операции
    "S",       # токен короче двух символов
]


def child_env() -> dict:
    env = dict(os.environ)
    env["PATH"] = f"{ROOT / '.venv' / 'bin'}:{env.get('PATH', '')}"
    return env


def parse_lines(out: str) -> dict[int, tuple[str, str]]:
    """'строка N: nonint ...' -> {N: (verdict, reason)}.

    verdict ∈ {proven, refuted, skip, value}. Строки без вердикта не попадают.
    """
    res: dict[int, tuple[str, str]] = {}
    for line in out.splitlines():
        m = re.match(r"\s*\[(PASS|FAIL|SKIP|VALUE)\]\s*(.*)$", line)
        if not m:
            continue
        mark, rest = m.group(1), m.group(2)
        lm = re.search(r"строка\s+(\d+)", rest)
        if not lm:
            continue
        reason = rest.split("|", 1)[1].strip() if "|" in rest else ""
        verdict = {"PASS": "proven", "FAIL": "refuted", "SKIP": "skip", "VALUE": "value"}[mark]
        res[int(lm.group(1))] = (verdict, reason)
    return res


def static_layer() -> tuple[dict[int, tuple[str, str]], str]:
    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    spec = SPEC_DIR / "nonint_spec.txt"
    lines: list[str] = ["# физический оракул невмешательства (шаг D)"]
    for instrs, _ in LEAK_FIXTURES:
        lines.append(f"nonint {instrs}")
    for instrs in SAFE_FIXTURES:
        lines.append(f"nonint {instrs}")
    for instrs in UNSUPPORTED_FIXTURES:
        lines.append(f"nonint {instrs}")
    spec.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        p = subprocess.run([str(KERNC), "theory", str(spec)], cwd=ROOT, env=child_env(),
                           capture_output=True, text=True, errors="replace", timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {}, f"kernc theory не запустился: {e}"
    out = (p.stdout or "") + (p.stderr or "")
    # Ненулевой код у `kernc theory` — ОЖИДАЕМ (в спецификации есть опровержения),
    # поэтому читается ВЫВОД, а не код возврата.
    return parse_lines(out), ""


def zig_candidates() -> list[str]:
    """Кандидаты компилятора Zig: `ZIG` из окружения, затем PATH.

    `.venv/bin` ИСКЛЮЧАЕТСЯ: там лежит ДРУГОЙ Zig (пакет `ziglang` из pip,
    измерено — без `std.Io`, из-за чего `compat.zig` не собирается).
    """
    out: list[str] = []
    z = os.environ.get("ZIG")
    if z:
        out.append(z)
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d or d.endswith("/.venv/bin") or "/.venv/" in d:
            continue
        p = Path(d) / "zig"
        if p.exists():
            out.append(str(p))
    return out


def zig_exe() -> tuple[str | None, str]:
    """Компилятор Zig 0.17 (по ВЕРСИИ, а не по имени файла).

    Возвращает (путь, версия). Проверка версии обязательна: любой другой Zig
    даст ошибки сборки, которые легко принять за «проба не работает».
    """
    for c in zig_candidates():
        try:
            v = subprocess.run([c, "version"], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            continue
        ver = (v.stdout or "").strip()
        if ver.startswith("0.17"):
            return c, ver
    return None, ""


def physical_layer() -> tuple[float | None, float | None, str]:
    """Проба реального времени. Возвращает (ct_ratio, ee_ratio, ошибка).

    Запуск — ПРЯМЫМ `zig run` с явным модулем `compat`, а НЕ через `zig build`:
    шаг сборки КЭШИРУЕТ результат запуска и при повторном вызове печатает
    «cached» БЕЗ вывода пробы (измерено), то есть оракул читал бы пустоту.
    """
    zig, zver = zig_exe()
    if zig is None:
        return None, None, "не найден компилятор Zig 0.17 (проверен `ZIG` и PATH без .venv/bin)"
    env = child_env()
    cmd = [
        zig, "run",
        "--dep", "compat",
        "-Mroot=src/verifier/nonint_timing_probe.zig",
        "-Mcompat=src/compat.zig",
    ]
    print(f"[i] проба времени: {zig} (версия {zver})")
    try:
        p = subprocess.run(cmd, cwd=ROOT, env=env,
                           capture_output=True, text=True, errors="replace", timeout=900)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, None, f"проба времени не запустилась: {e}"
    out = (p.stdout or "") + (p.stderr or "")
    cm = re.search(r"CT_RATIO=([0-9.]+)", out)
    em = re.search(r"EE_RATIO=([0-9.]+)", out)
    if not cm or not em:
        tail = "\n".join(out.splitlines()[-4:])
        return None, None, f"в выводе пробы нет CT_RATIO/EE_RATIO (rc={p.returncode}); хвост: {tail}"
    return float(cm.group(1)), float(em.group(1)), ""


def classify(model_says_leak: bool, physical_shows_delta: bool) -> str:
    if model_says_leak and physical_shows_delta:
        return "CONFIRMED_LEAK"
    if not model_says_leak and not physical_shows_delta:
        return "CONFIRMED_SAFE"
    if not model_says_leak and physical_shows_delta:
        return "MISSED"          # модель пропустила реальную зависимость от секрета
    return "FALSE_ALARM"          # модель обвинила то, что от секрета не зависит


def run() -> int:
    print("=" * 78)
    print("ФИЗИЧЕСКИЙ ОРАКУЛ НЕВМЕШАТЕЛЬСТВА (2-Safety): модель против РЕАЛЬНОГО времени")
    print("=" * 78)
    print("[!] СТАТИСТИЧЕСКИЙ ОРАКУЛ: измеряется РЕАЛЬНОЕ время, подвержен шуму")
    print("    планировщика ОС; используется МИНИМУМ из N прогонов, вердикт НЕ является")
    print("    доказательством невмешательства произвольного кода.")
    ok = True

    verdicts, err = static_layer()
    if err:
        print(f"[FAIL] статический слой: {err}")
        print("RC=1")
        return 1

    # --- 1. Статический слой: утечки обязаны быть опровергнуты ---
    n_leak = len(LEAK_FIXTURES)
    for i, (instrs, kind) in enumerate(LEAK_FIXTURES, start=2):
        v, reason = verdicts.get(i, ("?", ""))
        if v != "refuted":
            print(f"[FAIL] `nonint {instrs}`: ожидалось ОПРОВЕРГНУТО, получено {v!r} ({reason})")
            ok = False
        elif kind not in reason:
            print(f"[FAIL] `nonint {instrs}`: вид утечки не назван ({reason})")
            ok = False
        else:
            print(f"  [OK] `nonint {instrs}` -> УТЕЧКА {kind}")

    # --- 2. Статический слой: безопасные обязаны быть доказаны ---
    base = 2 + n_leak
    for j, instrs in enumerate(SAFE_FIXTURES):
        v, reason = verdicts.get(base + j, ("?", ""))
        if v != "proven":
            print(f"[FAIL] `nonint {instrs}`: ожидалось ДОКАЗАНО, получено {v!r} ({reason})")
            ok = False
        else:
            print(f"  [OK] `nonint {instrs}` -> утечек нет")

    # --- 3. FAIL-CLOSED: неподдерживаемая инструкция не даёт вердикта ---
    base2 = base + len(SAFE_FIXTURES)
    for j, instrs in enumerate(UNSUPPORTED_FIXTURES):
        v, reason = verdicts.get(base2 + j, ("?", ""))
        if v != "skip":
            print(f"[FAIL] `nonint {instrs}`: ожидался SKIP (fail-closed), получено {v!r}")
            ok = False
        elif "вердикта НЕТ" not in reason:
            print(f"[FAIL] `nonint {instrs}`: причина SKIP не называет отсутствие вердикта ({reason})")
            ok = False
        else:
            print(f"  [OK] `nonint {instrs}` -> SKIP (вердикта НЕТ)")

    # --- 4. Детерминизм статического слоя ---
    v2, err2 = static_layer()
    if err2 or v2 != verdicts:
        print("[FAIL] статический вердикт недетерминирован")
        ok = False
    else:
        print("  [OK] статический вердикт детерминирован (два прогона совпали)")

    # --- 5. Физический слой: РЕАЛЬНОЕ время ---
    # «Мнение модели» берётся ИЗ ЯДРА (вердикт `kernc theory` по модельной
    # программе), а НЕ из строковой константы: иначе саботаж анализатора не
    # изменил бы классификацию, и оракул был бы вакуумным.
    ct_idx = 2 + n_leak + SAFE_FIXTURES.index(MODELS["constant-time"])
    ee_idx = 2 + [f[0] for f in LEAK_FIXTURES].index(MODELS["early-exit"])
    ct_model_leak = verdicts.get(ct_idx, ("?", ""))[0] == "refuted"
    ee_model_leak = verdicts.get(ee_idx, ("?", ""))[0] == "refuted"
    print(f"\n[i] модельные программы (вердикт ЯДРА):")
    print(f"    constant-time `nonint {MODELS['constant-time']}` -> "
          f"{'УТЕЧКА' if ct_model_leak else 'утечек нет'}")
    print(f"    early-exit    `nonint {MODELS['early-exit']}` -> "
          f"{'УТЕЧКА' if ee_model_leak else 'утечек нет'}")

    ct, ee, perr = physical_layer()
    if perr:
        print(f"[FAIL] физический слой: {perr}")
        print("RC=1")
        return 1
    assert ct is not None and ee is not None
    print(f"\n[ИЗМЕРЕНО] отношение времён (позиция отличия 1 против 4096, min-of-N):")
    print(f"  constantTimeEqual : CT_RATIO={ct:.4f}  (порог < {CT_MAX})")
    print(f"  earlyExitEqual    : EE_RATIO={ee:.4f}  (порог >= {EE_MIN})")

    ct_says_leak = ct_model_leak
    ee_says_leak = ee_model_leak
    ct_delta = ct >= CT_MAX
    ee_delta = ee >= EE_MIN

    rows = [
        ("constant-time", ct_says_leak, ct_delta, ct),
        ("early-exit", ee_says_leak, ee_delta, ee),
    ]
    counts = {"CONFIRMED_LEAK": 0, "CONFIRMED_SAFE": 0, "MISSED": 0, "FALSE_ALARM": 0}
    for name, model_leak, delta, val in rows:
        c = classify(model_leak, delta)
        counts[c] += 1
        print(f"  [{c}] {name}: модель говорит {'утечка' if model_leak else 'утечки нет'}, "
              f"реальность {'зависит от позиции' if delta else 'не зависит'} (ratio={val:.2f})")

    if counts["MISSED"]:
        print(f"[FAIL] ПРОПУЩЕНО реальных зависимостей: {counts['MISSED']}")
        ok = False
    if counts["FALSE_ALARM"]:
        print(f"[FAIL] ЛОЖНЫХ ТРЕВОГ: {counts['FALSE_ALARM']}")
        ok = False
    if counts["CONFIRMED_LEAK"] < 1 or counts["CONFIRMED_SAFE"] < 1:
        print(f"[FAIL] невакуумность: подтверждённых утечек {counts['CONFIRMED_LEAK']}, "
              f"подтверждённых безопасных {counts['CONFIRMED_SAFE']} (нужно >= 1 каждого)")
        ok = False

    # --- 6. Негативный контроль классификатора (без него инварианты выше пусты) ---
    neg = [
        ("MISSED", classify(False, True)),
        ("FALSE_ALARM", classify(True, False)),
    ]
    for want, got in neg:
        if want != got:
            print(f"[FAIL] негативный контроль: ожидался {want}, получен {got}")
            ok = False
    if ok:
        print(f"  [OK] негативный контроль: классификатор ловит ОБА класса ошибок")

    if ok:
        print(f"[OK] физический оракул невмешательства: модель и РЕАЛЬНОЕ время согласованы "
              f"(CT_RATIO={ct:.2f} против EE_RATIO={ee:.2f}); 0 пропусков, 0 ложных тревог")
    print(f"RC={0 if ok else 1}")
    return 0 if ok else 1


def selftest() -> int:
    checks = [
        ("модель+физика согласны (утечка) = ПОДТВЕРЖДЕНО", classify(True, True) == "CONFIRMED_LEAK"),
        ("модель+физика согласны (нет) = ПОДТВЕРЖДЕНО", classify(False, False) == "CONFIRMED_SAFE"),
        ("модель молчит, физика видит = ПРОПУСК", classify(False, True) == "MISSED"),
        ("модель обвиняет, физика нет = ЛОЖНАЯ ТРЕВОГА", classify(True, False) == "FALSE_ALARM"),
        ("порог CT ниже порога EE", CT_MAX < EE_MIN),
        ("модель constant-time — из БЕЗОПАСНЫХ фикстур (вердикт ядра читается)", MODELS["constant-time"] in SAFE_FIXTURES),
        ("модель early-exit — из фикстур УТЕЧЕК (вердикт ядра читается)", MODELS["early-exit"] in [f[0] for f in LEAK_FIXTURES]),
        ("разбор строк: PASS -> proven", parse_lines("  [PASS] ДОКАЗАНО строка 5: nonint P1 B1 | утечек нет").get(5, ("", ""))[0] == "proven"),
        ("разбор строк: FAIL -> refuted", parse_lines("  [FAIL] ОПРОВЕРГНУТО строка 2: nonint S1 B1 | УТЕЧКА branch на шаге 1").get(2, ("", ""))[0] == "refuted"),
        ("разбор строк: SKIP -> skip", parse_lines("  [SKIP] строка 9: nonint S1 Q9 | nonint: неизвестная инструкция 'Q9' — вердикта НЕТ").get(9, ("", ""))[0] == "skip"),
        ("разбор строк: мусор не даёт вердикта", parse_lines("просто текст без маркера") == {}),
        ("инструкции утечек названы", len(LEAK_FIXTURES) == 4),
        ("безопасных фикстур 4", len(SAFE_FIXTURES) == 4),
        ("fail-closed фикстур 3", len(UNSUPPORTED_FIXTURES) == 3),
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
