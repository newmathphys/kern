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
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
EXTRACTOR = ROOT / "tools" / "kern_contracts.py"

RE_FN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)")


def audit_json(target: str) -> dict:
    """Прогон аудита через ABI (#483). Возвращает документ или падает честно."""
    p = subprocess.run([PY, str(EXTRACTOR), "--xray", target, "--xray-json"],
                       cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
    out = p.stdout or ""
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise SystemExit(f"[!] {target}: stdout не является ABI-JSON ({e}). "
                         f"Первые 200 символов: {out[:200]!r}")


def _norm_file(path: str) -> str:
    """Путь БЕЗ каталога-корня: иначе base/ и head/ дают разные ключи всегда."""
    p = path.replace("\\", "/")
    return p.split("/", 1)[1] if "/" in p else p


def key_of(f: dict) -> tuple[str, str, str]:
    m = RE_FN.match(str(f.get("details", "")).strip())
    return (_norm_file(str(f.get("file", ""))), str(f.get("type", "")),
            m.group(1) if m else "")


def delta(base: dict, head: dict) -> dict:
    kb = {key_of(f) for f in base.get("findings", [])}
    kh = {key_of(f) for f in head.get("findings", [])}
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
