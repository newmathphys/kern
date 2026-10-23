#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""ШАГ I: семантика ЗНАЧЕНИЙ языка — объект, и он обязан быть ПОЛНЫМ.

ЧТО ПРОВЕРЯЕТ.

1. Полнота таблицы: у КАЖДОГО языка, который умеет определить экстрактор
   (расширение файла -> язык), есть запись в `VALUE_SEMANTICS`. Раньше
   неизвестный язык молча получал семантику Python: C-код с floor-делением —
   это #317 заново и ТИХО.

2. Правило I4: `semantics_for("неизвестный")` обязан БРОСИТЬ отказ, а не
   вернуть дефолт.

3. Дисперсия: в местах, отвечающих за СЕМАНТИКУ ЗНАЧЕНИЙ (деление и маркеры
   оборачивания), не осталось `if lang ==`. Синтаксическая дисперсия не
   запрещена: её ошибка даёт видимый SKIP, а не ложный вердикт.

4. Согласованность с наблюдаемым поведением: правила `div` из таблицы
   совпадают с фактическими SMT-формулами на контрольных точках. Защита от
   «таблица говорит floor, а код строит trunc».

Запуск:  python3 tools/lang_semantics_check.py [--selftest]
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KC = ROOT / "tools" / "kern_contracts.py"

EXPECTED_LANGS = {"python", "c", "zig", "rust", "go", "ts", "js", "evm"}


def load_kc():
    spec = importlib.util.spec_from_file_location("kc_sem", KC)
    mod = importlib.util.module_from_spec(spec)
    # ВАЖНО: `@dataclass` внутри модуля ищет свой модуль через
    # `sys.modules.get(cls.__module__)` — без регистрации он падает с
    # `AttributeError: 'NoneType' object has no attribute '__dict__'`.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def check_table(kc) -> list[str]:
    errs = []
    sem = kc.VALUE_SEMANTICS
    for lang in sorted(EXPECTED_LANGS):
        if lang not in sem:
            errs.append(f"нет записи для языка {lang!r}")
            continue
        s = sem[lang]
        if s.div not in ("floor", "trunc0"):
            errs.append(f"{lang}: неизвестное правило div={s.div!r}")
        if s.mod not in ("floor", "trunc0"):
            errs.append(f"{lang}: неизвестное правило mod={s.mod!r}")
        if s.true_div is not None and s.true_div not in ("floor", "trunc0"):
            errs.append(f"{lang}: неизвестное правило true_div={s.true_div!r}")
    # Инварианты, из которых вышли РЕАЛЬНЫЕ дефекты.
    if "python" in sem and sem["python"].div != "floor":
        errs.append("python: div обязан быть floor (иначе #317)")
    if "c" in sem and sem["c"].div != "trunc0":
        errs.append("c: div обязан быть trunc0 (иначе #317)")
    if "python" in sem and sem["python"].true_div is not None:
        errs.append("python: `/` — истинное (float) деление, обязано быть None")
    if "evm" in sem and not sem["evm"].div_zero_value:
        errs.append("evm: деление на ноль ОПРЕДЕЛЕНО как 0 (Yellow Paper)")
    return errs


def check_rule_i4(kc) -> list[str]:
    errs = []
    try:
        kc.semantics_for("klingon")
    except kc.Unsupported:
        pass
    except Exception as e:                     # noqa: BLE001
        errs.append(f"I4: ожидался Unsupported, получено {type(e).__name__}")
    else:
        errs.append("I4 НАРУШЕНО: неизвестный язык вернул семантику вместо отказа")
    return errs



def check_no_value_dispersion(kc) -> list[str]:
    """В местах семантики ЗНАЧЕНИЙ не должно остаться `if lang ==`."""
    errs = []
    src = KC.read_text(encoding="utf-8")
    for fname in ("def expr_smt(", "def _explicit_wrap("):
        i = src.find(fname)
        if i < 0:
            errs.append(f"не найдена {fname}")
            continue
        j = src.find("\ndef ", i + 1)
        body = src[i:j if j > 0 else len(src)]
        for line in body.splitlines():
            # Комментарии не код: упоминание «раньше здесь стояло `if lang ==
            # "python"`» — это ДОКУМЕНТАЦИЯ дефекта, а не дисперсия.
            # (Обратный случай — #245, где комментарий ПРЯТАЛ число; здесь
            # комментарий создавал бы ложное срабатывание.)
            code = line.split("#", 1)[0]
            m = re.search(r"if lang ==\s*[\"'](\w+)[\"']", code)
            if m:
                errs.append(f"{fname}: осталась дисперсия по языку "
                            f"(lang == {m.group(1)!r}) — значение обязано "
                            f"браться из VALUE_SEMANTICS")
    return errs


def check_formula_agreement(kc) -> list[str]:
    """Таблица против ФАКТИЧЕСКИХ SMT-формул на контрольных точках."""
    errs = []
    try:
        import ast as _ast
        import z3
    except ImportError:
        return ["z3 недоступен — сверка формул НЕ выполнена (это не «ок»)"]

    cases = [(-7, 2), (7, -2), (-7, -2), (7, 2), (-1, 3), (1, -3)]
    for lang in ("python", "c"):
        sem = kc.VALUE_SEMANTICS[lang]
        for a, b in cases:
            node = _ast.parse(f"({a}) // ({b})", mode="eval").body
            try:
                smt = kc.expr_smt(node, {}, lang)
            except kc.Unsupported:
                continue
            want = a // b if sem.div == "floor" else int(a / b)
            s = z3.Solver()
            s.add(z3.parse_smt2_string(
                f"(set-logic ALL)(declare-const r Int)(assert (= r {smt}))"
                f"(assert (distinct r {want}))"))
            if s.check() == z3.sat:
                errs.append(f"{lang}: формула деления для ({a}, {b}) не совпала "
                            f"с табличным правилом {sem.div!r}")
    return errs


def check_flags_are_read(kc) -> list[str]:
    """Флаги таблицы обязаны ЧИТАТЬСЯ кодом, а не лежать мёртвым грузом.

    Это защита от того самого класса, из которого вышли #339/#340: два
    источника истины — таблица говорит одно, код делает другое. Таблица, поля
    которой никто не читает, — это документация, а не семантика.
    """
    errs = []
    src = KC.read_text(encoding="utf-8")
    for flag, why in (
        ("div_zero_value",
         "без него EVM получил бы ложное обвинение в делении на ноль"),
        ("signed",
         "без него беззнаковые/ EVM получили бы обязанности MIN/-1 и -x"),
        ("wrap_ops",
         "без него `+%`/`wrapping_add` обвинялись бы в переполнении"),
        ("true_div",
         "без него Python `/` (float) не уходил бы в честный SKIP"),
    ):
        uses = [m.start() for m in re.finditer(rf"\.{flag}\b", src)]
        # Объявление в __init__/__slots__ не считается чтением.
        reads = [u for u in uses
                 if "self." + flag not in src[max(0, u - 5):u + len(flag) + 5]]
        if len(reads) < 1:
            errs.append(f"поле `{flag}` не читается кодом — {why}")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    kc = load_kc()

    if args.selftest:
        errs = []
        saved = dict(kc.VALUE_SEMANTICS)
        try:
            kc.VALUE_SEMANTICS.pop("c", None)
            if not check_table(kc):
                errs.append("пропажа записи языка не замечена")
            kc.VALUE_SEMANTICS.clear()
            if not check_table(kc):
                errs.append("пустая таблица не замечена")
            kc.VALUE_SEMANTICS.clear()
            kc.VALUE_SEMANTICS.update(saved)
            kc.VALUE_SEMANTICS["klingon"] = kc.VALUE_SEMANTICS["python"]
            if not check_rule_i4(kc):
                errs.append("дефолт вместо отказа не замечен")
        finally:
            kc.VALUE_SEMANTICS.clear()
            kc.VALUE_SEMANTICS.update(saved)
        if errs:
            print("SELFTEST FAILED: " + "; ".join(errs))
            return 1
        print("SELFTEST PASSED: пропажа языка, пустая таблица и дефолт вместо "
              "отказа — все три замечены")
        return 0

    errs = (check_table(kc) + check_rule_i4(kc) + check_no_value_dispersion(kc)
            + check_flags_are_read(kc) + check_formula_agreement(kc))
    print("СЕМАНТИКА ЗНАЧЕНИЙ ЯЗЫКА (шаг I)")
    print(f"  языков в таблице: {len(kc.VALUE_SEMANTICS)} | "
          f"ожидалось: {len(EXPECTED_LANGS)}")
    for lang in sorted(kc.VALUE_SEMANTICS):
        s = kc.VALUE_SEMANTICS[lang]
        print(f"    {lang:7s} div={s.div:6s} mod={s.mod:6s} "
              f"true_div={str(s.true_div):7s} div0_value={s.div_zero_value} "
              f"wrap_ops={len(s.wrap_ops)}")
    if errs:
        print()
        for e in errs:
            print(f"  [FAIL] {e}")
        print(f"\nРАСХОЖДЕНИЙ: {len(errs)}")
        return 1
    print("\n[OK] таблица полна, неизвестный язык — отказ (I4), "
          "в семантике значений дисперсии нет, формулы совпали")
    return 0


if __name__ == "__main__":
    sys.exit(main())
