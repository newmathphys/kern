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
    d = _parse(out)
    if d["checked"] < 0:
        return False, "в выводе нет ни [REPO SUMMARY], ни строки `buckets:`"
    if d["unnamed"]:
        return False, f"сводка признала пропуски БЕЗ причины: {d['unnamed'][0].strip()[:90]}"
    if d["named"] != d["skipped"]:
        return False, (f"Σ причин {d['named']} != пропусков {d['skipped']} "
                       f"(размерности смешаны)")
    if d["b_sum"] != d["b_total"]:
        return False, f"Σ корзин {d['b_sum']} != total {d['b_total']} (#405)"
    mixed = [n for n in notes if n.startswith("skip: ")]
    if mixed:
        return False, f"заметка помечена как пропуск функции: {mixed[0][:90]}"
    return True, (f"заметок уровня ВЕТКИ {len(notes)}, пропусков функций {d['skipped']}, "
                  f"Σ корзин {d['b_sum']} == total {d['b_total']}, отрицательной разницы НЕТ")


def _verdict(d: dict) -> tuple:
    """Решение ворот: ТРИ КОРЗИНЫ (#405) и список причин обязаны сходиться.

    ЧТО ИЗМЕНИЛОСЬ ВМЕСТЕ С КОДОМ (предохранитель #405.3). Раньше порог был
    `skipped >= 2` — он был привязан к СТАРОЙ воронке, где «нет `if`» считалось
    пропуском. Теперь фикстура обязана задействовать ВСЕ ТРИ корзины:
    `checked >= 1`, `trivial >= 1`, `skipped >= 1`, и сумма корзин обязана
    равняться `total`. Иначе разделение корзин ничем не проверено.
    """
    if d["unnamed"]:
        return False, f"сводка признала пропуски БЕЗ причины: {d['unnamed'][0].strip()}"
    if d["checked"] < 0:
        return False, "в выводе нет ни [REPO SUMMARY], ни строки `buckets:`"
    if d["checked"] < 1:
        return False, f"checked={d['checked']}: переводимое условие не проверено"
    if d["trivial"] < 1:
        return False, (f"trivial={d['trivial']}: корзина «обязательств нет» НЕ "
                       f"задействована — фикстура не проверяет разделение корзин (#405)")
    if d["skipped"] < 1:
        return False, (f"skipped={d['skipped']}: ожидался хотя бы один НАСТОЯЩИЙ "
                       f"отсев (условие вне подмножества / `nil/null` / битовый)")
    if d["named"] != d["skipped"]:
        return False, f"напечатано причин {d['named']}, а пропусков {d['skipped']}"
    if d["b_sum"] != d["b_total"] or d["b_total"] != d["total"]:
        return False, (f"Σ корзин {d['b_sum']} != total {d['b_total']} "
                       f"(сводка говорит total {d['total']}) — инвариант воронки нарушен (#405)")
    return True, (f"checked {d['checked']} | trivial {d['trivial']} | "
                  f"skipped {d['skipped']} | Σ {d['b_sum']} == total {d['b_total']}; "
                  f"причин {d['named']} = пропусков {d['skipped']}")


RE_SUM = re.compile(r"функций проверено (\d+) / (\d+) \(skipped (\d+)\)")
RE_BUCKETS = re.compile(r"buckets: checked (\d+) \| trivial (\d+) \| skipped (\d+) "
                        r"\| Σ (\d+) == total (\d+)")


def _parse(out: str) -> dict:
    """Разобрать сводку: ТРИ КОРЗИНЫ + причины + признания «без причины».

    Читаются ДВА независимых источника (строка `[REPO SUMMARY]` и строка
    `buckets:`) — их расхождение само по себе является нарушением инварианта,
    поэтому `b_total` сверяется с `total` из сводки.
    """
    d = {"checked": -1, "total": -1, "skipped": -1, "named": 0, "trivial": -1,
         "b_sum": -1, "b_total": -1, "unnamed": []}
    m = RE_SUM.search(out)
    if m:
        d["checked"], d["total"], d["skipped"] = (int(m.group(1)), int(m.group(2)),
                                                  int(m.group(3)))
    mb = RE_BUCKETS.search(out)
    if mb:
        d["checked"], d["trivial"], d["skipped"] = (int(mb.group(1)), int(mb.group(2)),
                                                    int(mb.group(3)))
        d["b_sum"], d["b_total"] = int(mb.group(4)), int(mb.group(5))
    for ln in out.splitlines():
        st = ln.strip()
        if st.startswith("skip: ") and " \u00d7 " in st:
            try:
                d["named"] += int(st.rsplit(" \u00d7 ", 1)[1])
            except ValueError:
                pass
    d["unnamed"] = [ln for ln in out.splitlines() if "БЕЗ записанной причины" in ln]
    return d


def _run(d: Path) -> tuple[int, str]:
    env = dict(os.environ)
    zig = Path.home() / "opt" / "zig-x86_64-linux-0.17.0"
    env["PATH"] = str(zig) + os.pathsep + str(ROOT / ".venv" / "bin") + os.pathsep + env.get("PATH", "")
    p = subprocess.run([PY, str(ROOT / "tools" / "kern_contracts.py"), "--xray", str(d)],
                       capture_output=True, text=True, env=env, timeout=900)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def selftest() -> int:
    def D(checked, trivial, skipped, named, unnamed=(), b_sum=None, b_total=None,
          total=None):
        """Собрать разобранную сводку: по умолчанию инварианты СОБЛЮДЕНЫ."""
        _s = checked + trivial + skipped
        return {"checked": checked, "trivial": trivial, "skipped": skipped,
                "named": named, "unnamed": list(unnamed),
                "b_sum": _s if b_sum is None else b_sum,
                "b_total": _s if b_total is None else b_total,
                "total": _s if total is None else total}

    cases = [
        (D(1, 1, 2, 2), True, "все три корзины задействованы, причины сходятся"),
        (D(1, 1, 2, 0), False, "причины не напечатаны"),
        (D(1, 1, 2, 2, unnamed=["[!] пропусков БЕЗ записанной причины: 1 — это дефект"]),
         False, "сводка сама признала пропуск без причины"),
        (D(0, 2, 2, 2), False, "ни одно условие не проверено"),
        (D(1, 0, 3, 3), False, "корзина `trivial` НЕ задействована (#405)"),
        (D(1, 1, 2, 2, b_sum=5), False, "Σ корзин не равна total (#405)"),
        (D(1, 1, 2, 2, b_total=5), False, "строка `buckets:` расходится со сводкой (#405)"),
    ]
    bad = 0
    for args, want, name in cases:
        got, why = _verdict(args)
        mark = "OK" if got == want else "ПРОВАЛ"
        if got != want:
            bad += 1
        print(f"  [{mark}] {name}: verdict={got} ({why})")
    # НЕВАКУУМНОСТЬ #407.2: вывод ДО правки (отрицательная разница «-1») обязан
    # быть ОТВЕРГНУТ. Если он проходит, проверка размерностей ничего не доказывает.
    _c, _s, _n, _u = _parse(OLD_MIXED_OUTPUT), None, None, None
    got, why = _verdict(_c)
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
        d = _parse(out)
        if d["checked"] < 0:
            print("[FAIL #400] в выводе нет ни [REPO SUMMARY], ни строки `buckets:`")
            print(out[-800:])
            return 1
        ok, why = _verdict(d)
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
