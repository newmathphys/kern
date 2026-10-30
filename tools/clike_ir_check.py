#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""БАРЬЕР 2+3: ТАБЛИЧНЫЙ МИКРО-ТЕСТ ПЕРЕВОДА УСЛОВИЙ + IR-СЛЕПОК.

ЗАЧЕМ (оплачено практикой такта 2.2). Семнадцать дефектов такта (#400–#417)
жили в C-like-переводчике внутри `tools/kern_contracts.py`, и НИ ОДИН старый
тест их не поймал, потому что тесты смотрели на КОНЕЧНЫЙ ВЕРДИКТ файла
(`PASS`/`FAIL`), а не на сам перевод:

  * `#413`: `_saturate_rewrite('a +| b')` возвращал вход БЕЗ ИЗМЕНЕНИЙ (перепись
    не работала из-за управляющего байта 0x08), но вердикт файла всё равно был
    `PASS` — символ `|` случайно уводил выражение в BV-маршрут;
  * `#414`: `!f(c)` превращалось в `f == 0(c)` -> `(= f _havoc_1)` — ЛОЖНАЯ
    модель, и Z3 отвечал `sat`, так что снаружи всё выглядело тихо.

ЗДЕСЬ проверяется ПРЯМО функция перевода: пара «сырое условие C/TS ->
ОЖИДАЕМАЯ строка SMT или SKIP». Такой тест идёт за доли секунды и БЕЗ Z3,
поэтому ошибка регулярки ловится до 47-секундного прогона корпуса.

ПОЧЕМУ ЗНАЧЕНИЯ ИМЕННО ТАКИЕ. Каждое ожидание — не догадка, а ИЗМЕРЕННЫЙ
выход текущего конвейера, и рядом записано, какой дефект такта оно защищает.
Если конвейер изменится осознанно, таблица обновляется вместе с ним — и это
видно в диффе, а не «в прогоне через час».

ГРАНИЦА. Тест проверяет ПЕРЕВОД, а не звучимость модели: он не доказывает, что
перевод верен математически. Он доказывает, что перевод НЕ ИЗМЕНИЛСЯ молча —
то есть ловит регрессию и случайную порчу, а не отсутствие ошибки в замысле.
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import kern_contracts as K  # noqa: E402

# (сырое условие, ожидаемый SMT ИЛИ None = обязан быть SKIP, почему это важно)
CASES: tuple = (
    ("c != ' ' && c != '\\t'",
     "(and (distinct c 32) (distinct c 9))",
     "литералы -> коды символов (#410); без этого корзина «синтаксис» в cmark"),
    ("node->next == NULL", "(= node__next 0)",
     "поле + NULL -> плоское имя и ноль (#416, шаг 6)"),
    ("!node->next", "(= node__next 0)",
     "`!p` после сплющивания поля (ловушка сортов Z3, #409/#416)"),
    ("node->type == 1", "(= node__type 1)",
     "поле -> плоское имя (#416): 100 условий в cmark"),
    ("a->b->c == NULL", "(= a__b__c 0)",
     "цепочка полей -> одно плоское имя (#416)"),
    ("!p", "(= p 0)",
     "голое имя: перепись `!` разрешена (#409)"),
    ("!fs.existsSync(p)", None,
     "ВЫЗОВ: `!` не переписывается, честный SKIP (#414)"),
    ("!S_is_line_end_char(c)", None,
     "#414: здесь рождалась ЛОЖНАЯ модель `(= f _havoc_1)`"),
    ("error.code === 'ENOENT'", "(= error__code 6123186)",
     "`===` + поле + литерал (#416): 35 из 77 отказов TS"),
    ("x !== 5", "(distinct x 5)",
     "`!==` нормализуется до переписи null (#416)"),
    ("typeof body !== 'object'", "(distinct body__typeof 3993132)",
     "`typeof X` -> `X__typeof` (#416): +18 условий в toolkit"),
    ("obj?.prop", None,
     "опциональная цепочка в условии — вне подмножества (названная граница)"),
    ("a ?? b", None,
     "nullish-оператор в условии — вне подмножества (названная граница)"),
    ("a ? b : c", "(ite (not (= a 0)) b c)",
     "тернарник -> ite, голое имя в булевой позиции (#408)"),
    ("a ? b ? c : d : e", "(ite (not (= a 0)) (ite (not (= b 0)) c d) e)",
     "ВЛОЖЕННЫЙ тернарник: правый ассоциативный разбор (#408)"),
    ("s[0] == 45", "(= (ite (= 0 0) s__e0 (ite (= 0 1) s__e1 s__e2)) 45)",
     "константный индекс: окно элементов (уже работает — потому индекс дал +1)"),
    ("subj->flags & FLAG", None,
     "БИТОВОЕ в условии — Шаг 4b (BV) НЕ начат: абстракция дала бы бутафорию"),
    ("len(arr)", "len__arr",
     "символическая длина (Zero-Annotation)"),
    ("x == nil", "(= x 0)",
     "nil -> 0 (Int-модель указателя, шаг 6)"),
)

# Отдельно: предохранитель #414 (второй рубеж) — вызов ЛИТЕРАЛА обязан отказать.
GUARD_CASES = (("0(c)", "broken rewrite"), ("6123186(x)", "broken rewrite"))


def translate(raw: str, lang: str = "c"):
    """ТОТ ЖЕ конвейер, что в `--xray`: литералы -> операторы -> поля -> null -> SMT.

    Возвращает строку SMT или None (SKIP). Исключение -> None.
    """
    try:
        s = K._literals_to_numbers(raw)
        s = s.replace("===", "==").replace("!==", "!=")
        s = K._flatten_fields(s)
        rw = K._null_to_zero(s)
        if rw is None:
            return None
        node = ast.parse(K.clike_to_python(rw), mode="eval").body
        return K.expr_smt(node, {}, lang)
    except Exception:  # noqa: BLE001 — SKIP и есть ожидаемый исход для части случаев
        return None


def run_cases() -> list[str]:
    bad: list[str] = []
    for raw, want, why in CASES:
        got = translate(raw)
        if got != want:
            bad.append(f"{raw!r}: ожидали {want!r}, получили {got!r}  ({why})")
    for raw, want_sub in GUARD_CASES:
        try:
            ast.parse(K.clike_to_python(raw), mode="eval")
            node = ast.parse(K.clike_to_python(raw), mode="eval").body
            K.expr_smt(node, {}, "c")
            bad.append(f"{raw!r}: предохранитель #414 НЕ сработал (вызов литерала принят)")
        except Exception as e:  # noqa: BLE001
            if want_sub not in str(e):
                bad.append(f"{raw!r}: ожидали отказ с {want_sub!r}, получили {e!r}")
    return bad


def selftest() -> int:
    """МЕТА-ТЕСТ: гейт ОБЯЗАН покраснеть на подсаженном ожидании."""
    ok = True
    global CASES
    saved = CASES
    CASES = ((CASES[0][0], CASES[0][1] + "X", "подсадка"),)
    if not run_cases():
        print("  [FAIL] подсаженное ожидание НЕ поймано — гейт вакуумен")
        ok = False
    else:
        print("  [OK]   подсаженное ожидание поймано")
    CASES = ((CASES[0][0], "", "подсадка: пустое ожидание"),)
    if not run_cases():
        print("  [FAIL] пустое ожидание НЕ поймано")
        ok = False
    else:
        print("  [OK]   пустое ожидание поймано")
    CASES = saved
    if run_cases():
        print("  [FAIL] таблица не проходит на текущем коде")
        ok = False
    else:
        print(f"  [OK]   таблица ({len(CASES)} случаев) проходит")
    return 0 if ok else 1


def dump_ir(corpus: str) -> int:
    """IR-СЛЕПОК за доли секунды БЕЗ Z3: функции + переведённые условия + SHA.

    ЗАЧЕМ. Прыжки знаменателя `458 -> 476 -> 443` ловились только полным прогоном
    с Z3. Здесь то же самое видно сразу: какие функции найдены, сколько условий
    переведено и изменился ли слепок ЦЕЛИКОМ.
    """
    root = Path(corpus).expanduser()
    ir = ir_of(root)
    print(json.dumps({k: v for k, v in ir.items() if k != "files"}, ensure_ascii=False))
    return 0


def ir_of(root: Path) -> dict:
    """IR-слепок корпуса: функции + переведённые условия + SHA (без Z3)."""
    exts = {".c", ".h", ".cc", ".cpp", ".ts", ".js", ".zig", ".rs", ".go"}
    ir: dict = {"corpus": str(root), "files": {}, "n_functions": 0,
                "n_conditions": 0, "n_translated": 0}
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in exts:
            continue
        try:
            funcs = K._clike_functions(f)
        except Exception:  # noqa: BLE001
            continue
        for name, _params, body, ln, _ranges, _reqs in funcs:
            b = K._strip_c_casts(body)
            mask = K._strip_c_comments_strings(b)
            conds = [b[m.start(1):m.end(1)] for m in K._clike_ifs(mask)]
            tr = sum(1 for c in conds if translate(c) is not None)
            ir["files"].setdefault(str(f.relative_to(root)), []).append(
                {"fn": name, "line": ln, "conds": len(conds), "translated": tr})
            ir["n_functions"] += 1
            ir["n_conditions"] += len(conds)
            ir["n_translated"] += tr
    blob = json.dumps(ir["files"], sort_keys=True, ensure_ascii=False)
    ir["sha256"] = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return ir


# БАЗОВЫЕ СЛЕПКИ КОРПУСОВ (ИЗМЕРЕНО на пришпиленных SHA, см. docs/CORPORA.md).
# Смысл: любая правка C-like-переводчика, меняющая РАЗБОР (набор функций или
# переведённые условия), обязана быть ВИДНА здесь — за доли секунды и без Z3.
# Именно этого не хватало, когда знаменатель гулял `458 -> 476 -> 443`.
IR_BASELINES = {
    "cmark-gfm/src": {"sha256": "0aa016a61960017a", "n_functions": 308,
                      "n_conditions": 2539, "n_translated": 2398},
    "toolkit/packages": {"sha256": "2a7aac90f9317962", "n_functions": 150,
                         "n_conditions": 156, "n_translated": 134},
}
CACHE = Path.home() / ".cache" / "kern" / "repos"


def check_baselines() -> int:
    """Сверить IR-слепки корпусов с базой. Отсутствие корпуса — НАЗВАННЫЙ пропуск."""
    rc = 0
    for name, want in IR_BASELINES.items():
        root = CACHE / name
        if not root.exists():
            print(f"  [SKIP] {name}: корпуса нет в кэше — проверка слепка НЕ выполнена")
            continue
        got = ir_of(root)
        if got["sha256"] != want["sha256"]:
            print(f"  [FAIL] {name}: слепок ИЗМЕНИЛСЯ: было {want['sha256']}, стало {got['sha256']}")
            print(f"         функции {want['n_functions']} -> {got['n_functions']} | "
                  f"условия {want['n_conditions']} -> {got['n_conditions']} | "
                  f"переведено {want['n_translated']} -> {got['n_translated']}")
            rc = 1
        else:
            print(f"  [OK]   {name}: слепок совпал ({got['sha256']}), "
                  f"функций {got['n_functions']}, условий {got['n_conditions']}, "
                  f"переведено {got['n_translated']}")
    return rc


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        print("KERN: мета-тест табличного IR-гейта")
        return selftest()
    if "--check-baselines" in argv:
        print("KERN: сверка IR-слепков корпусов с базой")
        return check_baselines()
    if "--dump-ir" in argv:
        i = argv.index("--dump-ir")
        return dump_ir(argv[i + 1] if i + 1 < len(argv) else ".")
    bad = run_cases()
    if bad:
        print(f"[!] табличный IR-гейт: расхождений {len(bad)}")
        for b in bad:
            print(f"    {b}")
        return 1
    print(f"[OK] табличный IR-гейт: {len(CASES)} случаев перевода + "
          f"{len(GUARD_CASES)} предохранителя #414 — совпали")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
