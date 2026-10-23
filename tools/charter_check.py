#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""УСТАВ KERN: проверяющий для законов классов I и II.

ЗАЧЕМ. Устав, который нельзя проверить, — это пожелание. Здесь каждый закон
называет своего проверяющего, и проверяющий ЗАПУСКАЕТСЯ. Мета-правило («у
каждого закона есть проверяющий») тоже проверяется: закон, названный в
`docs/CHARTER.md`, но отсутствующий в таблице ниже, валит гейт.

ТРИ КЛАССА, и различие между ними честное:
  I  — алгебраические: доказывает KERN (`charter/laws.py`, `@kern:`-контракты).
  II — процессные: проверяют гейты репозитория (список ниже).
  III— политика: машинно НЕ проверяется; в уставе это указано прямо, а не
       замаскировано под проверку.

СВЕРКА МОДЕЛИ С ЯДРОМ. Законы класса I доказаны над МОДЕЛЬЮ (`charter/laws.py`),
а не над Zig-кодом. Чтобы модель не разошлась с ядром, здесь она сверяется с
оракулом самого ядра (`kern-conformance`, собранный из `src/core/eq2.zig` и
`src/next/state_axes.zig`): все 16 пар join, все 4 значения конфляции и все 7
отображений вердиктов обязаны совпасть. Без этой сверки модель — просто текст.

Запуск:  python3 tools/charter_check.py [--selftest]
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARTER = ROOT / "docs" / "CHARTER.md"
LAWS_PY = ROOT / "charter" / "laws.py"

# --- Класс I: закон -> (краткая формулировка, функция-контракт) --------------
# Имена обязаны существовать в charter/laws.py: иначе «закона» нет.
CLASS_I = {
    "L1": ("T ⊔ F = B — противоречие не затирается", "law_join_T_F"),
    "L2": ("⊔ идемпотентен: x ⊔ x = x", "law_join_idempotent"),
    "L3": ("конфляция ~ инволютивна: ~~a = a", "law_conflate_involution"),
    "L4": ("сбой инструмента не становится F (timeout/out_of_fuel/…)", "law_no_false_accusation"),
    "L5": ("B не производится вердиктом — только конфликтом свидетельств", "law_verdict_never_b"),
    "L6": ("invalid_certificate отображается в N, а не в F", "law_invalid_cert_is_unknown"),
    "L7": ("N — единица ⊔: N ⊔ x = x", "law_join_identity_N"),
    "L8": ("частный случай L4, машинно доказанный: timeout → N", "law_timeout_is_unknown"),
}

# Законы, которые Z3 подтверждает, но наш пруф-чекер вывода не покрывает.
# Они НЕ считаются доказанными — и это зафиксировано, а не замалчано.
EXPECTED_UNCOVERED = {"law_no_false_accusation", "law_verdict_never_b"}

# --- Класс II: процессный закон -> команда-проверяющий -----------------------
CLASS_II = (
    ("P1", "каждая CHECK-цель умеет падать (100 % покрытие)", ["tools/registry.py"]),
    ("P2", "ни одного числа без якоря в публичных документах", ["tools/check_metrics_consistency.py"]),
    ("P3", "снимок состояния собран из facts+реестра+журнала", ["tools/gen_status.py", "--check"]),
    ("P4", "llms.txt генерируется из facts.json", ["tools/gen_llms_txt.py", "--check"]),
    ("P5", "EN/RU факты совпадают во всех парах", ["tools/docs_parity_check.py"]),
    ("P6", "каждое свидетельство отслеживается и не содержит провала", ["tools/evidence_gate.py"]),
)

# --- Класс III: политика (машинно не проверяется) ----------------------------
CLASS_III = (
    "Q1", "опубликованный тег не двигается",
    "Q2", "секреты не попадают в репозиторий (частично: secrets-check)",
    "Q3", "второй агент работает только на чтение",
    "Q4", "ложное обвинение хуже пропуска",
)


def _run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run([sys.executable, *cmd], cwd=ROOT,
                       capture_output=True, text=True, check=False)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _oracle() -> dict:
    """Таблицы из САМОГО ЯДРА (kern-conformance). Пусто -> сверять нечем."""
    exe = ROOT / "zig-out" / "bin" / "kern-conformance"
    if not exe.exists():
        return {}
    p = subprocess.run([str(exe)], cwd=ROOT, capture_output=True, text=True, check=False)
    out: dict = {"b4": {}, "join": {}, "conflate": {}, "verdict": {}}
    for line in (p.stdout or "").splitlines():
        parts = line.strip().split("|")
        if len(parts) < 3:
            continue
        sec = parts[0]
        if sec == "b4" and len(parts) == 4:
            out["b4"][parts[1]] = (int(parts[2]), int(parts[3]))
        elif sec == "join" and len(parts) == 4:
            out["join"][(parts[1], parts[2])] = parts[3]
        elif sec == "conflate" and len(parts) == 3:
            out["conflate"][parts[1]] = parts[2]
        elif sec == "verdict" and len(parts) == 3:
            out["verdict"][parts[1]] = parts[2]
    return out


def check_laws() -> list[str]:
    """Класс I: все законы доказаны, кроме явно перечисленных непокрытых."""
    errs: list[str] = []
    rc, out = _run(["tools/kern_contracts.py", "charter/laws.py"])
    proven = set(re.findall(r"\[PASS\]\s+(\w+):", out))
    skipped = set(re.findall(r"\[SKIP\]\s+(\w+):", out))
    violated = re.findall(r"\[FAIL\]\s+(\w+):", out)
    for name in violated:
        errs.append(f"закон {name}: НАРУШЕН — устав не выполняется")
    m = re.search(r"ВАКУУМНЫХ\s+(\d+)", out)
    if m and int(m.group(1)):
        errs.append("закон вакуумен — доказан на пустом множестве входов")
    m = re.search(r"ЛОЖНЫХ ТРЕВОГ\s+(\d+)", out)
    if m and int(m.group(1)):
        errs.append("ложная тревога в законах")
    for lid, (_text, fn) in CLASS_I.items():
        if fn in skipped and fn not in EXPECTED_UNCOVERED:
            errs.append(f"закон {lid} ({fn}): SKIP, но не в списке ожидаемо непокрытых")
        if fn not in proven and fn not in skipped:
            errs.append(f"закон {lid} ({fn}): нет вердикта — закон без проверяющего")
    for fn in EXPECTED_UNCOVERED:
        if fn in proven:
            errs.append(f"{fn} теперь доказан — обновите EXPECTED_UNCOVERED "
                        f"(это улучшение, и его надо зафиксировать)")
    if rc != 0:
        errs.append(f"kern_contracts вернул rc={rc}")
    print(f"  [I] законов: {len(CLASS_I)} | доказано {len(proven)} | "
          f"не покрыто пруф-чекером {len(skipped)} | нарушено {len(violated)}")
    return errs


def check_model_vs_kernel() -> list[str]:
    """Сверка модели устава с таблицами САМОГО ядра."""
    errs: list[str] = []
    orc = _oracle()
    if not orc.get("join"):
        return ["нет оракула ядра (kern-conformance) — модель сверять нечем"]
    sys.path.insert(0, str(ROOT))
    from charter import laws as L  # noqa: E402

    code = {"N": L.N, "T": L.T, "F": L.F, "B": L.B}
    n_join = n_conf = n_verd = 0
    for (a, b), want in orc["join"].items():
        got = L.join_code(code[a], code[b])
        if got != code[want]:
            errs.append(f"join({a},{b}): модель {got}, ядро {code[want]}")
        n_join += 1
    for a, want in orc["conflate"].items():
        if L.conflate_code(code[a]) != code[want]:
            errs.append(f"conflate({a}): модель != ядро ({want})")
        n_conf += 1
    verd_codes = {"proved": 0, "refuted": 1, "unknown": 2, "timeout": 3,
                  "out_of_fuel": 4, "invalid_certificate": 5, "tool_error": 6}
    for name, want in orc["verdict"].items():
        v = verd_codes.get(name)
        if v is None:
            errs.append(f"вердикт `{name}` ядра не отображён в модели")
            continue
        got = 1 if v == 0 else (2 if v == 1 else 0)
        if got != code[want]:
            errs.append(f"вердикт `{name}`: модель {got}, ядро {code[want]}")
        n_verd += 1
    print(f"  [I] сверка с ядром: join {n_join} пар · conflate {n_conf} · "
          f"вердикты {n_verd}")
    return errs


def check_gates() -> list[str]:
    """Класс II: запускаем каждого названного проверяющего."""
    errs: list[str] = []
    for pid, text, cmd in CLASS_II:
        rc, out = _run(cmd)
        mark = "OK" if rc == 0 else "FAIL"
        print(f"  [II] {pid} {mark}: {text}")
        if rc != 0:
            tail = "\n".join(out.strip().splitlines()[-3:])
            errs.append(f"{pid} ({text}) rc={rc}: {tail}")
    return errs


def check_no_law_without_checker() -> list[str]:
    """Мета-правило: закон, названный в уставе, обязан быть в таблице."""
    errs: list[str] = []
    if not CHARTER.exists():
        return [f"нет {CHARTER.relative_to(ROOT)}"]
    text = CHARTER.read_text(encoding="utf-8")
    ids = set(re.findall(r"^\|\s*\*\*(L\d+|P\d+|Q\d+)\*\*\s*\|", text, re.M))
    known = set(CLASS_I) | {p[0] for p in CLASS_II} | set(CLASS_III)
    missing = ids - known
    if missing:
        errs.append(f"в уставе есть законы без проверяющего: {sorted(missing)}")
    if not ids:
        errs.append("в уставе не найдено ни одного закона (форма таблицы изменилась?)")
    print(f"  [meta] законов в уставе: {len(ids)} | машинно проверяемых: "
          f"{len(ids & (set(CLASS_I) | {p[0] for p in CLASS_II}))} | политика: "
          f"{len(ids & set(CLASS_III))}")
    return errs


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in args:
        return selftest()
    print("УСТАВ KERN — проверка законов")
    errs: list[str] = []
    errs += check_laws()
    errs += check_model_vs_kernel()
    errs += check_gates()
    errs += check_no_law_without_checker()
    if errs:
        for e in errs:
            print(f"[FAIL] {e}")
        print(f"\n[FAIL] устав не выполняется: расхождений {len(errs)}")
        return 1
    print("\n[OK] УСТАВ ВЫПОЛНЯЕТСЯ: законы доказаны, модель сверена с ядром, "
          "процессные гейты зелёные, законов без проверяющего нет")
    return 0


def selftest() -> int:
    """Мета-тест: сломанный закон обязан валить устав.

    Проверяем именно то, ради чего устав существует: что он не декорация.
    Ломаем КОПИЮ файла законов (оригинал не трогаем) и требуем красного.
    """
    import tempfile
    bad = 0
    src = LAWS_PY.read_text(encoding="utf-8")
    broken = src.replace("# @kern:ensures result == 3",
                         "# @kern:ensures result == 2", 1)  # L1 перестаёт держаться
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d) / "laws.py"
        tmp.write_text(broken, encoding="utf-8")
        _rc, out = _run(["tools/kern_contracts.py", str(tmp)])
        if "[FAIL]" not in out:
            print("[FAIL] selftest: сломанный закон L1 НЕ пойман")
            bad += 1
        else:
            print("[OK] selftest: сломанный закон L1 ловится (устав не декорация)")
    sys.path.insert(0, str(ROOT))
    from charter import laws as L  # noqa: E402
    real = L.join_code
    try:
        L.join_code = lambda a, b: (L.p_of(a) ^ L.p_of(b)) | ((L.n_of(a) ^ L.n_of(b)) << 1)
        errs = check_model_vs_kernel()
        if not errs:
            print("[FAIL] selftest: подмена join на XOR НЕ замечена сверкой с ядром")
            bad += 1
        else:
            print(f"[OK] selftest: подмена модели замечена ({len(errs)} расхождений)")
    finally:
        L.join_code = real
    print(f"[{'OK' if bad == 0 else 'FAIL'}] charter selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
