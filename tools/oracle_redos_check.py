#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# SPDX-License-Identifier: LicenseRef-KERN-Proprietary
"""ФИЗИЧЕСКИЙ ОРАКУЛ для ReDoS (шаг D плана).

ЗАЧЕМ. До этого шага семейство `redos` проверялось МОДЕЛЬ ПРОТИВ МОДЕЛИ: `redos.zig`
ищет вложенные кванторы, а `theory_cli.zig` сам же объявляет свой вывод верным.
Это вакуум: компьютер подтверждает себе, что его формулы непротиворечивы, и ничего
не говорит о реальности.

ЧТО ДЕЛАЕТ ЭТОТ ОРАКУЛ. Для каждой регулярки из подмножества парсера:
  1. НАТИВНЫЙ вердикт — `kernc theory` (анализ `redos.zig` по разобранному AST);
  2. ФИЗИЧЕСКИЙ замер — РЕАЛЬНЫЙ `re.fullmatch` в ИЗОЛИРОВАННОМ процессе с жёстким
     таймаутом. Сентинел выбирается КАК У АТАКУЮЩЕГО: `!`, а для `.`-шаблонов `\n`,
     потому что `.` его не матчит (иначе `(.*)*` «не взрывается» на `!`);
  3. КЛАССИФИКАЦИЯ: подтверждено / ложное обвинение / пропуск / честно-безопасно.

ИНВАРИАНТЫ (без любого из них проверка бессмысленна):
  * ложных обвинений 0 (ядро сказало «взрывается», а реальный движок мгновенен);
  * пропусков 0 (ядро сказало «безопасно», а реальный движок ВЗОРВАЛСЯ);
  * НЕВАКУМНОСТЬ: есть и подтверждённые уязвимые, и подтверждённые безопасные —
    иначе сравнение тривиально (все «совпадут» на одном классе);
  * FAIL-CLOSED (#385): регулярка с синтаксисом ВНЕ подмножества парсера обязана
    быть SKIP, а НЕ «ДОКАЗАНО» — иначе вердикт относился бы к другой регулярке;
  * НЕГАТИВНЫЙ КОНТРОЛЬ: заведомо неверное утверждение обязано быть ОТВЕРГНУТО.

ЧЕГО ЭТО НЕ ДОКАЗЫВАЕТ (граница):
  * замер машинно-зависим (порог калиброван на этой машине, 2026-10-28);
  * подмножество парсера узкое (литералы, `.`, `|`, `()`, `*+?`), поэтому классы
    `[a-z]`, класс цифр, `{m,n}` — SKIP, а не «безопасно»;
  * проверяются 9 регулярок, а не «все регулярки мира»: это дифференциальный
    тест на представителях классов, а не доказательство для произвольной строки.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"
SPEC_DIR = ROOT / "tests" / "fixtures" / "oracles"

# --- КАЛИБРОВКА (измерено 2026-10-28, `tools/oracle_redos_check.py --calibrate`) ---
# N=24: безопасные <= 0.0007 с, уязвимые >= 0.9756 с (разделение ~1400x).
N = 24
THRESHOLD = 0.2     # с: выше — «взорвалось» (285x выше самой медленной безопасной)
KILL = 8.0          # с: жёсткий таймаут изолированного процесса → тоже «взрыв»

# (регулярка, единица повтора, сентинел, ожидаемый физический класс)
FIXTURES = [
    ("(a+)+",   "a",  "!",  True),
    ("(a*)*",   "a",  "!",  True),
    ("(a|a)*",  "a",  "!",  True),
    ("(a|a)+",  "a",  "!",  True),
    ("(.*)*",   "a",  "\n", True),
    ("(.+)+",   "a",  "\n", True),
    ("abc",     "abc", "",  False),
    ("(ab|cd)+", "ab", "!",  False),
    ("(a+b)+",  "a",  "!",  False),
]
# ВНЕ подмножества парсера: обязаны быть SKIP (fail-closed #385), а не вердикт.
UNSUPPORTED = [r"(\d+)+", "[a-z]+"]

RUNNER = ("import re,sys,time;t=time.perf_counter();"
          "re.fullmatch(sys.argv[1],sys.argv[2]);"
          "print(time.perf_counter()-t)")


def child_env() -> dict:
    env = dict(os.environ)
    env["PATH"] = f"{ROOT / '.venv' / 'bin'}:{env.get('PATH', '')}"
    return env


def native_verdict(regex: str, idx: int) -> tuple[str, str]:
    """Вердикт ЯДРА: 'vulnerable' | 'safe' | 'skip' | 'error' + причина."""
    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    spec = SPEC_DIR / f"redos_{idx}.txt"
    spec.write_text(f"# физический оракул ReDoS\nredos {regex}\n", encoding="utf-8")
    try:
        p = subprocess.run([str(KERNC), "theory", str(spec)], cwd=ROOT, env=child_env(),
                           capture_output=True, text=True, errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return "error", f"kernc theory не запустился: {e}"
    out = p.stdout + p.stderr
    if "[SKIP]" in out:
        return "skip", out.strip().splitlines()[-1][:160] if out.strip() else ""
    if "ОПРОВЕРГНУТО" in out:
        return "vulnerable", ""
    if "ДОКАЗАНО" in out:
        return "safe", ""
    return "error", f"вердикт не разобран: {out.strip()[:160]}"


def physical(regex: str, text: str) -> tuple[bool, float]:
    """РЕАЛЬНЫЙ замер: изолированный процесс, жёсткий таймаут.

    Возвращает (взорвалось?, секунды). Убитый по таймауту считается взрывом.
    """
    try:
        p = subprocess.run([sys.executable, "-c", RUNNER, regex, text],
                           capture_output=True, text=True, errors="replace", timeout=KILL)
    except subprocess.TimeoutExpired:
        return True, KILL
    if p.returncode != 0 or not p.stdout.strip():
        return False, -1.0
    el = float(p.stdout.strip())
    return el > THRESHOLD, el


def classify(native: str, exploded: bool) -> str:
    """Классификатор. ВЫНЕСЕН отдельно, чтобы негативный контроль мог его проверить."""
    if native == "vulnerable":
        return "CONFIRMED_VULN" if exploded else "FALSE_ACCUSATION"
    if native == "safe":
        return "MISSED" if exploded else "CONFIRMED_SAFE"
    return "BOUNDARY"


def run() -> int:
    print("=" * 72)
    print("=== KERN: ФИЗИЧЕСКИЙ ОРАКУЛ ReDoS (реальный движок против нативного анализа) ===")
    print(f"=== замер: N={N}, порог {THRESHOLD} с, таймаут {KILL} с (калибровка 2026-10-28) ===")
    print("=" * 72)

    counts = {"CONFIRMED_VULN": 0, "FALSE_ACCUSATION": 0, "MISSED": 0,
              "CONFIRMED_SAFE": 0, "BOUNDARY": 0}
    bad: list[str] = []

    for i, (regex, unit, sentinel, expect_vuln) in enumerate(FIXTURES):
        text = unit * N + sentinel
        nv, why = native_verdict(regex, i)
        exploded, el = physical(regex, text)
        cls = classify(nv, exploded)
        counts[cls] += 1
        tstr = f"{el:.4f}с" if el >= 0 else "ошибка запуска"
        print(f"  {'OK ' if cls in ('CONFIRMED_VULN', 'CONFIRMED_SAFE') else '!! '}"
              f"{cls:16s} {regex:10s} сентинел={sentinel!r:6s} физика={tstr:11s} ядро={nv}")
        if cls in ("FALSE_ACCUSATION", "MISSED"):
            bad.append(f"{regex}: {cls} ({why})")
        # Ожидание калибровки обязано совпасть с физикой: иначе порог устарел,
        # и «совпадение с ядром» было бы случайным.
        if exploded != expect_vuln:
            bad.append(f"{regex}: КАЛИБРОВКА УСТАРЕЛА — ожидали "
                       f"{'взрыв' if expect_vuln else 'мгновенно'}, получили "
                       f"{'взрыв' if exploded else 'мгновенно'} ({tstr})")

    # FAIL-CLOSED (#385): синтаксис вне подмножества парсера → SKIP, НЕ «ДОКАЗАНО».
    for j, regex in enumerate(UNSUPPORTED):
        nv, _ = native_verdict(regex, 100 + j)
        counts[classify(nv, False)] += 1
        ok = nv == "skip"
        print(f"  {'OK ' if ok else '!! '}{'FAIL_CLOSED' if ok else 'FAIL_OPEN':16s} "
              f"{regex:10s} ядро={nv} "
              f"({'вердикта НЕТ — верно' if ok else 'ВЕРДИКТ О ДРУГОЙ РЕГУЛЯРКЕ?!'})")
        if not ok:
            bad.append(f"{regex}: fail-open — ядро дало «{nv}» вместо SKIP (#385)")

    # НЕГАТИВНЫЙ КОНТРОЛЬ: классификатор ОБЯЗАН уметь ловить оба класса ошибок,
    # иначе «0 ложных обвинений» ничего не значит (проверка, не способная упасть).
    neg = []
    if classify("vulnerable", False) != "FALSE_ACCUSATION":
        neg.append("не ловит ложное обвинение")
    if classify("safe", True) != "MISSED":
        neg.append("не ловит пропуск")
    if classify("skip", True) != "BOUNDARY":
        neg.append("SKIP смешан с вердиктом")
    print(f"  {'OK ' if not neg else '!! '}НЕГАТИВНЫЙ КОНТРОЛЬ: классификатор "
          f"{'ловит оба класса ошибок' if not neg else '; '.join(neg)}")

    print("-" * 72)
    print(f"  подтверждено УЯЗВИМЫХ  : {counts['CONFIRMED_VULN']}  (реальный движок взорвался)")
    print(f"  подтверждено безопасных: {counts['CONFIRMED_SAFE']}")
    print(f"  ЛОЖНЫХ ОБВИНЕНИЙ       : {counts['FALSE_ACCUSATION']}  (обязано быть 0)")
    print(f"  ПРОПУСКОВ              : {counts['MISSED']}  (обязано быть 0)")
    print(f"  границ (SKIP, fail-closed): {counts['BOUNDARY']}")
    print("-" * 72)

    ok = True
    if counts["FALSE_ACCUSATION"]:
        print(f"[FAIL] ложные обвинения: {counts['FALSE_ACCUSATION']}")
        ok = False
    if counts["MISSED"]:
        print(f"[FAIL] пропуски: {counts['MISSED']}")
        ok = False
    if counts["CONFIRMED_VULN"] < 5:
        print(f"[FAIL] невакуумность: подтверждённых уязвимых {counts['CONFIRMED_VULN']} < 5")
        ok = False
    if counts["CONFIRMED_SAFE"] < 3:
        print(f"[FAIL] невакуумность: подтверждённых безопасных {counts['CONFIRMED_SAFE']} < 3")
        ok = False
    if neg:
        print("[FAIL] негативный контроль не прошёл")
        ok = False
    for r in bad:
        print(f"[FAIL] {r}")
        ok = False
    if ok:
        print(f"[OK] физический оракул ReDoS: {counts['CONFIRMED_VULN']} уязвимых подтверждены "
              f"РЕАЛЬНЫМ движком, {counts['CONFIRMED_SAFE']} безопасных не обвинены, "
              f"0 ложных обвинений, 0 пропусков")
    print(f"RC={0 if ok else 1}")
    return 0 if ok else 1


def selftest() -> int:
    """Быстрая проверка САМОГО классификатора (без kernc и без замеров)."""
    checks = [
        ("ложное обвинение ловится", classify("vulnerable", False) == "FALSE_ACCUSATION"),
        ("пропуск ловится", classify("safe", True) == "MISSED"),
        ("подтверждённая уязвимость", classify("vulnerable", True) == "CONFIRMED_VULN"),
        ("подтверждённая безопасность", classify("safe", False) == "CONFIRMED_SAFE"),
        ("SKIP не считается безопасностью", classify("skip", False) == "BOUNDARY"),
        ("заведомая ложь отвергнута", classify("safe", True) != "CONFIRMED_SAFE"),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"  {'[OK]' if ok else '[FAIL]'} {n}")
    if bad:
        print(f"[FAIL] selftest: {len(bad)} проверок не прошло")
        return 1
    print(f"[OK] selftest: {len(checks)}/{len(checks)} проверок классификатора")
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
