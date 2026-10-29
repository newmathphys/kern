#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the Apache License, Version 2.0.
"""Гейт #400: причины пропуска C-like `--xray` обязаны ПЕЧАТАТЬСЯ.

ЧТО БЫЛО НЕ ТАК. Сводка `--xray` для C-like заявляла
«skipped N with explicit reasons», но НИ ОДНОЙ причины не выводила:
`_xray_clike_file` их просто не возвращал. Читатель видел «с причинами» и не
видел ни одной — то есть фраза была ЛОЖНОЙ.

ЧТО ПРОВЕРЯЕТСЯ (4 свойства)
1. Сумма напечатанных причин `skip: KEY × CNT` РАВНА `skipped N` из сводки.
2. Нет строки «пропусков БЕЗ записанной причины» (она = дефект инструмента).
3. Позитивный контроль: файл с переводимым условием даёт `checked >= 1`.
4. `--selftest`: логика ворот отвергает три подделки вывода.

ГРАНИЦА. Гейт проверяет СВЯЗЬ счётчика и списка причин, а не качество самих
причин: «вне подмножества» может быть и слишком широкой корзиной.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

FIXTURE = '''// Позитивный контроль: условие переводимо -> checked >= 1
int clamped(int n) {
    if (n > 10) { return 10; }
    return n;
}

// Отсев 1: `p->len` — доступ к полю структуры вне подмножества
struct S { int len; };
int member(struct S *p) {
    if (p->len > 0) { return 1; }
    return 0;
}

// Отсев 2: побитовый `&` вне подмножества (только + - * / // %)
int bitwise(int a) {
    if ((a & 1) == 1) { return 1; }
    return 0;
}

// Отсев 3: условий `if` в теле нет вовсе
int plain(int n) {
    return 42;
}
'''


# ДЕФЕКТ #407.2: СМЕСЬ РАЗМЕРНОСТЕЙ (функции против ветвей).
# Вложенное условие-ВЫЗОВ (`is_ok(x)`) вне подмножества, поэтому функция
# ПРОВЕРЕНА (checked 1/1), а ОДНА её ветвь получает СПРАВОЧНУЮ заметку. До правки
# заметка попадала в гистограмму ПРОПУСКОВ, и сводка печатала «пропусков БЕЗ
# записанной причины: -1» — ветки вычитались из функций. Случай ДЕТЕРМИНИРОВАН:
# решатель для него не нужен, воспроизводится на любом окружении.
PY_FIXTURE = '''def g(x):
    if x > 0:
        if is_ok(x):
            return 1
    return 0
'''

# Вывод ДО правки — тот самый, который печатал отрицательное «число пропусков».
# Хранится как образец: он доказывает, что проверка НЕ вакуумна (её вердикт на
# этом выводе обязан быть False). Образец дословный, а не переписанный.
OLD_MIXED_OUTPUT = (
    "[REPO SUMMARY] файлов 2 | функций проверено 2 / 2 (skipped 0) | находок 0 "
    "| нечитаемых файлов 0\n"
    "    skip: g: ветка 3 не решена решателем × 1\n"
    "[!] пропусков БЕЗ записанной причины: -1 — это дефект инструмента, "
    "а не свойство проверяемого кода\n"
)


def _check_python_notes(tmp: Path) -> tuple:
    """#407.2: заметки уровня ВЕТКИ не имеют права попадать в пропуски ФУНКЦИЙ.

    Возвращает (ok, почему). Проверяются ЧЕТЫРЕ свойства, и все они ИЗМЕРЯЮТСЯ:
      1. случай НЕ вакуумный: фикстура обязана дать хотя бы одну строку `note:`
         (если механизм заметок исчезнет, проверка молча ослабнет — это ловим);
      2. сводка НЕ печатает отрицательное «число пропусков»;
      3. счётчик функций и напечатанные причины сходятся (Σ `skip:` == skipped);
      4. заметка НЕ помечена как `skip:` — иначе она снова смешается с функциями.
    """
    d = tmp / "py"
    d.mkdir(exist_ok=True)
    (d / "notes.py").write_text(PY_FIXTURE, encoding="utf-8")
    rc, out = _run(d)
    if rc != 0:
        return False, f"--xray вернул rc={rc} на python-фикстуре"
    notes = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("note: ")]
    if not notes:
        return False, ("фикстура НЕ дала ни одной заметки `note:` — случай "
                       "вакуумный (механизм заметок исчез или переименован)")
    neg = [ln.strip() for ln in out.splitlines() if "БЕЗ записанной причины: -" in ln]
    if neg:
        return False, f"отрицательное «число пропусков» вернулось: {neg[0][:90]}"
    checked, skipped, named, unnamed = _parse(out)
    if checked < 0:
        return False, "в выводе нет [REPO SUMMARY]"
    if unnamed:
        return False, f"сводка признала пропуски БЕЗ причины: {unnamed[0].strip()[:90]}"
    if named != skipped:
        return False, f"Σ причин {named} != пропусков {skipped} (размерности смешаны)"
    mixed = [n for n in notes if n.startswith("skip: ")]
    if mixed:
        return False, f"заметка помечена как пропуск функции: {mixed[0][:90]}"
    return True, (f"заметок уровня ВЕТКИ {len(notes)}, пропусков функций {skipped}, "
                  f"отрицательной разницы НЕТ")


def _verdict(checked: int, skipped: int, named: int, unnamed: list[str]) -> tuple[bool, str]:
    """Решение ворот: счётчик и список причин обязаны сходиться."""
    if unnamed:
        return False, f"сводка признала пропуски БЕЗ причины: {unnamed[0].strip()}"
    if checked < 1:
        return False, f"checked={checked}: переводимое условие не проверено"
    if skipped < 2:
        return False, f"skipped={skipped}: ожидались >= 2 пропуска (отсев по условию и по телу)"
    if named != skipped:
        return False, f"напечатано причин {named}, а пропусков {skipped}"
    return True, f"checked {checked} / {checked + skipped}, причин {named} = пропусков {skipped}"


def _parse(out: str) -> tuple[int, int, int, list[str]]:
    m = re.search(r"функций проверено (\d+) / (\d+) \(skipped (\d+)\)", out)
    if not m:
        return -1, -1, -1, []
    checked, skipped = int(m.group(1)), int(m.group(3))
    named = 0
    for ln in out.splitlines():
        st = ln.strip()
        if st.startswith("skip: ") and " \u00d7 " in st:
            try:
                named += int(st.rsplit(" \u00d7 ", 1)[1])
            except ValueError:
                pass
    unnamed = [ln for ln in out.splitlines() if "БЕЗ записанной причины" in ln]
    return checked, skipped, named, unnamed


def _run(d: Path) -> tuple[int, str]:
    env = dict(os.environ)
    zig = Path.home() / "opt" / "zig-x86_64-linux-0.17.0"
    env["PATH"] = str(zig) + os.pathsep + str(ROOT / ".venv" / "bin") + os.pathsep + env.get("PATH", "")
    p = subprocess.run([PY, str(ROOT / "tools" / "kern_contracts.py"), "--xray", str(d)],
                       capture_output=True, text=True, env=env, timeout=900)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def selftest() -> int:
    cases = [
        ((1, 2, 2, []), True, "честный вывод"),
        ((1, 2, 0, []), False, "причины не напечатаны"),
        ((1, 2, 2, ["[!] пропусков БЕЗ записанной причины: 1 — это дефект"]), False,
         "сводка сама признала пропуск без причины"),
        ((0, 3, 3, []), False, "ни одно условие не проверено"),
    ]
    bad = 0
    for args, want, name in cases:
        got, why = _verdict(*args)
        mark = "OK" if got == want else "ПРОВАЛ"
        if got != want:
            bad += 1
        print(f"  [{mark}] {name}: verdict={got} ({why})")
    # НЕВАКУУМНОСТЬ #407.2: вывод ДО правки (отрицательная разница «-1») обязан
    # быть ОТВЕРГНУТ. Если он проходит, проверка размерностей ничего не доказывает.
    _c, _s, _n, _u = _parse(OLD_MIXED_OUTPUT)
    got, why = _verdict(_c, _s, _n, _u)
    if got:
        print(f"  [ПРОВАЛ] вывод ДО правки принят за чистый: {why}")
        bad += 1
    else:
        print(f"  [OK] вывод ДО правки отвергнут: {why[:70]}")
    if bad:
        print(f"SELFTEST FAILED: {bad} из {len(cases) + 1} ветвей неверны")
        return 1
    print(f"SELFTEST PASSED: {len(cases) + 1} ветвей, все верны")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    tmp = Path(tempfile.mkdtemp(prefix="kern_xray_skip_"))
    try:
        (tmp / "fixture.c").write_text(FIXTURE, encoding="utf-8")
        rc, out = _run(tmp)
        if rc != 0:
            print(f"[FAIL #400] --xray вернул rc={rc}")
            print(out[-800:])
            return 1
        checked, skipped, named, unnamed = _parse(out)
        if checked < 0:
            print("[FAIL #400] в выводе нет [REPO SUMMARY]")
            print(out[-800:])
            return 1
        ok, why = _verdict(checked, skipped, named, unnamed)
        if not ok:
            print(f"[FAIL #400] {why}")
            print(out[-1200:])
            return 1
        print(f"[PASS #400] {why}")
        # ДЕФЕКТ #407.2: размерности причин (функции против ветвей).
        ok2, why2 = _check_python_notes(tmp)
        if not ok2:
            print(f"[FAIL #407.2] {why2}")
            print(out[-1200:])
            return 1
        print(f"[PASS #407.2] {why2}")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
