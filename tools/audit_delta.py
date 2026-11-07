#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""`audit-delta` (#484): ЧТО ИЗМЕНИЛОСЬ В АУДИТЕ МЕЖДУ ДВУМЯ ВЕРСИЯМИ.

ЗАЧЕМ. «Проверено N функций» — это фотография. Вопрос, который задаёт ревьюер,
звучит иначе: **«что стало хуже в ЭТОМ изменении?»**. Без дельты аудит не может
быть блокирующим гейтом PR: любой отчёт читается глазами целиком, а «раньше было
доказано, теперь SKIP» не видно вовсе.

ЧТО СЧИТАЕТСЯ. Две стороны сравниваются ЧЕРЕЗ МАШИННЫЙ ABI (`--xray-json`, #483),
поэтому инструмент не парсит текст и не зависит от вёрстки отчёта:
  * НОВАЯ находка (в head есть, в base нет) -> РЕГРЕСС, код возврата 1;
  * ИСЧЕЗНУВШАЯ находка (в base была)      -> исправление, код 0;
  * ДРЕЙФ ВОРОНКИ: checked/trivial/skipped по файлам и суммарно. Рост `skipped`
    при падении `checked` — это «стало меньше доказано», и он ПЕЧАТАЕТСЯ, даже
    если находок не прибавилось (иначе тихое ослабление прошло бы незамеченным).

ИДЕНТИЧНОСТЬ находки — `(файл, тип, функция)`, а не весь текст: контрпример и
номера строк меняются от версии к версии, и сравнивать их напрямую значило бы
объявлять регрессом любое перемещение кода.

ГРАНИЦА (честно): межпроцедурные выводы не моделируются, поэтому «новая находка»
означает ровно «новый детектор сработал», а не «раньше было безопасно».

ИСПОЛНИТЕЛЬ (`KERN_AUDIT_BIN`). По умолчанию аудит делает
`tools/kern_contracts.py` (dev-путь). Если задан `KERN_AUDIT_BIN` — вызывается
УКАЗАННЫЙ бинарь тем же ABI (`--xray … --xray-json`). Так GitHub Action
считает дельту РЕЛИЗНЫМ апплаенсом `kerna` (без .venv и Zig у клиента), а
логика сравнения остаётся ОДНА на оба пути (копия в YAML разошлась бы).

ДЕФЕКТ #498 (найден при постройке Action, ИЗМЕРЕН). Раньше ключ находки
строился как «путь БЕЗ ПЕРВОГО сегмента». Для ОДНОГО корня это работало, но
`git archive` базы и рабочее дерево головы — РАЗНЫЕ корни, и ключи не
совпадали НИКОГДА. Замер: две ИДЕНТИЧНЫЕ по содержимому папки в разных корнях
давали «новых 5 + исправленных 5». То есть PR-гейт объявлял регрессом любое
перемещение кода, а `make audit-delta BASE=../old HEAD=.` (документированный
режим) не мог быть блокирующим. Исправление: путь берётся ОТНОСИТЕЛЬНО корня
аудита (`audit_target` из ответа ABI), а не «срезанием сегмента».
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
EXTRACTOR = ROOT / "tools" / "kern_contracts.py"
# Пустой -> dev-путь (kern_contracts.py). Задан -> внешний бинарь того же ABI.
AUDIT_BIN = os.environ.get("KERN_AUDIT_BIN", "").strip()

RE_FN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)")


def audit_json(target: str) -> dict:
    """Прогон аудита через ABI (#483). Возвращает документ или падает честно.

    ДЕФЕКТ #498b (ИЗМЕРЕН при постройке Action). Относительный `target`
    разрешался от каталога ИНСТРУМЕНТА: ребёнок запускался с `cwd=ROOT`, поэтому
    `.` означало «репозиторий KERN», а не «дерево вызывающего». В GitHub Action
    это увело бы аудит в чекаут САМОГО действия (замер: `head.target` =
    `/…/kern` при аудите посторонней папки). Теперь относительный путь
    разрешается от ТЕКУЩЕГО каталога процесса и подставляется абсолютным.
    """
    tgt = Path(target).expanduser()
    if not tgt.is_absolute():
        tgt = Path.cwd() / tgt
    target = str(tgt.resolve())
    if AUDIT_BIN:
        cmd = [AUDIT_BIN, "--xray", target, "--xray-json"]
    else:
        cmd = [PY, str(EXTRACTOR), "--xray", target, "--xray-json"]
    p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
    out = p.stdout or ""
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise SystemExit(f"[!] {target}: stdout не является ABI-JSON ({e}). "
                         f"Первые 200 символов: {out[:200]!r}")


def _norm_file(path: str, root: str = "") -> str:
    """Путь ОТНОСИТЕЛЬНО КОРНЯ аудита (дефект #498).

    Корень берётся из `audit_target` ответа ABI. Раньше срезался первый сегмент
    пути, и сравнение работало только внутри одного корня: base (`git archive`)
    и head (рабочее дерево) — РАЗНЫЕ корни, поэтому «новых 5 + исправленных 5»
    получалось даже на идентичном содержимом (измерено).
    """
    p = path.replace("\\", "/")
    r = (root or "").replace("\\", "/").rstrip("/")
    if r and (p == r or p.startswith(r + "/")):
        return p[len(r):].lstrip("/")
    if p.startswith("./"):
        return p[2:]
    return p


def key_of(f: dict, root: str = "") -> tuple[str, str, str]:
    m = RE_FN.match(str(f.get("details", "")).strip())
    return (_norm_file(str(f.get("file", "")), root), str(f.get("type", "")),
            m.group(1) if m else "")


def delta(base: dict, head: dict) -> dict:
    kb = {key_of(f, str(base.get("audit_target", ""))) for f in base.get("findings", [])}
    kh = {key_of(f, str(head.get("audit_target", ""))) for f in head.get("findings", [])}
    sb, sh = base.get("summary", {}), head.get("summary", {})
    return {
        "schema_version": "1.0",
        "base": {"target": base.get("audit_target"), "summary": sb},
        "head": {"target": head.get("audit_target"), "summary": sh},
        "new_findings": sorted(kh - kb),
        "fixed_findings": sorted(kb - kh),
        "funnel": {k: (sh.get(k, 0) - sb.get(k, 0))
                   for k in ("total", "checked", "trivial", "skipped", "findings", "unreadable")},
    }


def _selftest() -> int:
    """Три направления на фикстурах: регресс / исправление / тот же вход.

    Невакуумность: если дельта «видит» регресс и там, где ничего не менялось,
    или НЕ видит его там, где менялось, — тест краснеет. Без этого инструмент
    мог бы быть зелёным всегда.
    """
    clean, buggy = "tests/fixtures/precision_clean", "tests/fixtures/precision_buggy"
    fails = 0

    def check(name: str, ok: bool, detail: str) -> None:
        nonlocal fails
        fails += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {name}: {detail}")

    d1 = delta(audit_json(clean), audit_json(buggy))
    check("clean -> buggy: регресс найден", len(d1["new_findings"]) == 5,
          f"новых {len(d1['new_findings'])}")
    check("clean -> buggy: исправлений нет", not d1["fixed_findings"], "")

    d2 = delta(audit_json(buggy), audit_json(clean))
    check("buggy -> clean: исправлено 5", len(d2["fixed_findings"]) == 5,
          f"исчезло {len(d2['fixed_findings'])}")
    check("buggy -> clean: регрессов нет", not d2["new_findings"], "")

    d3 = delta(audit_json(buggy), audit_json(buggy))
    check("тот же вход: дельта пуста",
          not d3["new_findings"] and not d3["fixed_findings"]
          and all(v == 0 for v in d3["funnel"].values()),
          "все счётчики дельты = 0")

    # ДЕФЕКТ #498 — случай, который СТАРАЯ проверка не ловила: ТО ЖЕ содержимое,
    # но ДРУГОЙ корень (так и выглядит PR-гейт: `git archive` базы + рабочее
    # дерево головы). До правки здесь было «новых 5 + исправленных 5» (измерено),
    # то есть регрессом объявлялось любое перемещение кода.
    with tempfile.TemporaryDirectory(prefix="kern_delta_a_") as ra, \
         tempfile.TemporaryDirectory(prefix="kern_delta_b_") as rb:
        src = Path(buggy)
        for root in (ra, rb):
            for f in sorted(src.rglob("*")):
                if f.is_file():
                    (Path(root) / f.relative_to(src)).parent.mkdir(parents=True, exist_ok=True)
                    (Path(root) / f.relative_to(src)).write_bytes(f.read_bytes())
        d4 = delta(audit_json(ra), audit_json(rb))
    check("#498: тот же код в РАЗНЫХ корнях — дельта пуста",
          not d4["new_findings"] and not d4["fixed_findings"],
          f"новых {len(d4['new_findings'])}, исчезло {len(d4['fixed_findings'])}"
          " (до #498 было 5/5)")

    print(f"[{'FAIL' if fails else 'OK'}] audit-delta selftest: провалов {fails}")
    return 1 if fails else 0


def main() -> int:
    args = sys.argv[1:]
    if "--selftest" in args:
        return _selftest()
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if len(args) != 2:
        print("использование: audit_delta.py <BASE_DIR> <HEAD_DIR> [--json]")
        return 2
    base_dir, head_dir = args
    d = delta(audit_json(base_dir), audit_json(head_dir))

    if as_json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
    else:
        f = d["funnel"]
        print("=" * 74)
        print(f"AUDIT DELTA: {base_dir} -> {head_dir}")
        print("=" * 74)
        print(f"  воронка: total {f['total']:+d} | checked {f['checked']:+d} | "
              f"trivial {f['trivial']:+d} | skipped {f['skipped']:+d} | "
              f"находок {f['findings']:+d} | нечитаемых {f['unreadable']:+d}")
        if d["new_findings"]:
            print(f"\n  РЕГРЕСС — новых находок {len(d['new_findings'])}:")
            for fl, ty, fn in d["new_findings"]:
                print(f"    + {fl} [{ty}] {fn}")
        if d["fixed_findings"]:
            print(f"\n  ИСПРАВЛЕНО — исчезло {len(d['fixed_findings'])}:")
            for fl, ty, fn in d["fixed_findings"]:
                print(f"    - {fl} [{ty}] {fn}")
        # ТИХОЕ ОСЛАБЛЕНИЕ: находок столько же, но доказано меньше.
        if f["skipped"] > 0 and f["checked"] < 0:
            print(f"\n  ⚠ ТИХОЕ ОСЛАБЛЕНИЕ: skipped {f['skipped']:+d} при checked "
                  f"{f['checked']:+d} — доказано МЕНЬШЕ, хотя находок не прибавилось")
        if not d["new_findings"] and not d["fixed_findings"]:
            print("\n  изменений в находках нет")
    return 1 if d["new_findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
