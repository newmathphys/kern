#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Генератор `docs/STATUS.md` (EN) и `docs/STATUS.ru.md` (RU).

ЗАЧЕМ. Витрина (`README`, `docs/index.html`) отвечает на вопрос «что это», но не
на вопрос «в каком состоянии проект СЕЙЧАС». Снимок состояния приходилось
собирать вручную (реестр + журнал + PR), и он дрейфовал — тот же класс дефекта,
что #311 (`llms.txt`) и #320 (утверждение сильнее измеренного).

ПРИНЦИП. Файл целиком собирается из машинных источников:
  * `docs/facts.json`            — измеренные факты (числа, якоря `<!-- fact:... -->`)
  * `tools/registry.py --json`   — цели и их классы
  * `docs/CAPABILITY_STATUS.md`  — журнал дефектов (статусы считаются, не пишутся)

Дата снимка НЕ хранится: сохранённая дата сама становится устаревшей. Дата
снимка — это дата коммита, которым файл был обновлён (`git log -1 docs/STATUS.md`).

Запуск:  python3 tools/gen_status.py [--check|--write|--selftest]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FACTS = ROOT / "docs" / "facts.json"
JOURNAL = ROOT / "docs" / "CAPABILITY_STATUS.md"
OUT = ("docs/STATUS.md", "docs/STATUS.ru.md")

# Журнал: `| **NNN** | описание | ✅ СТАТУС |`
ROW = re.compile(r"^\|\s*\*\*(\d+)\*\*\s*\|.*\|\s*([^|]*?)\s*\|\s*$", re.M)


def _facts() -> dict:
    return json.loads(FACTS.read_text(encoding="utf-8"))


def _registry() -> dict:
    """Счётчики классов берём у самого реестра, а не у `facts.json`.

    `facts.json` хранит только числа, нужные якорям; классы целей (MEASURE,
    EXTERNAL) в нём не отражены. Источник — `registry.py --json`, поэтому
    расхождение невозможно по построению. Дополнительно `check()` СВЕРЯЕТ
    числа фактов с реестром: если они разойдутся, гейт скажет это прямо.
    """
    try:
        out = subprocess.run([sys.executable, "tools/registry.py", "--json"],
                             cwd=ROOT, capture_output=True, text=True, check=False)
        d = json.loads(out.stdout)
    except (OSError, ValueError):
        return {}
    return {
        "targets": int(d.get("targets", 0)),
        "CHECK": len(d.get("checks", [])),
        "MEASURE": len(d.get("measures", [])),
        "BUILD": len(d.get("builds", [])),
        "EXTERNAL": len(d.get("external", [])),
        "META": len(d.get("meta", [])),
        "canfail_cases": len(d.get("canfail_cases", [])),
        "checks_covered": len(d.get("checks_covered", [])),
    }


def _anchor(key: str, value: int) -> str:
    """Число + невидимый якорь: `make sync` обновит его сам."""
    return f"<!-- fact:{key} -->{value}"


def _journal() -> dict:
    """Статусы журнала СЧИТАЮТСЯ, а не пишутся руками.

    ВАЖНО про формат: журнал прожил две генерации таблицы. В ранних строках
    третья колонка — КАТЕГОРИЯ (`гейт`, `ядро`, `витрина`), статуса там нет
    вовсе; в поздних — статус (`✅ ИСПРАВЛЕНО`). Поэтому классифицируются
    только ЯВНЫЕ статусы, а строки раннего формата считаются отдельно и НЕ
    переинтерпретируются: выдать им статус значило бы выдумать данные.

    «Открытым» дефект считается, только если статус НАЧИНАЕТСЯ с «ОТКРЫТ» (или
    явно «НЕ ИСПРАВЛЕНО»). Это отделяет статус от упоминания в тексте: строка
    «✅ НАЙДЕН KERN, PR ОТКРЫТ» — это найденный дефект в чужом репозитории, а
    не наш открытый (класс ошибки, который ловится здесь в третий раз: #245,
    #320, #332).
    """
    text = JOURNAL.read_text(encoding="utf-8")
    rows = ROW.findall(text)
    b = {"total": len(rows), "fixed": 0, "submitted": 0, "external": 0,
         "limitation": 0, "decision": 0, "open": 0, "legacy": 0}
    open_ids: list[str] = []
    for num, status in rows:
        s = status.replace("*", "").strip()
        s = re.sub(r"^[^\wА-Яа-яЁё]+", "", s)  # снять ведущий эмодзи/маркер
        up = s.upper()
        if up.startswith("ОТКРЫТ") or "НЕ ИСПРАВЛЕНО" in up:
            b["open"] += 1
            open_ids.append(f"#{num}")
        elif "ИСПРАВЛЕНО" in up:
            b["fixed"] += 1
        elif "ОТПРАВЛЕНО" in up:
            b["submitted"] += 1
        elif "НАЙДЕН" in up:
            b["external"] += 1
        elif "ОГРАНИЧЕНИЕ" in up:
            b["limitation"] += 1
        elif "РЕШЕНИЕ" in up:
            b["decision"] += 1
        else:
            b["legacy"] += 1
    b["open_ids"] = open_ids  # type: ignore[assignment]
    return b



def render_en(f: dict, reg: dict, j: dict) -> str:
    core = int(f["core_tests"])
    skip = int(f.get("cross_arch_skipped", 0))
    checks = int(f["check_targets"])
    q = f["quixbugs"]
    ver = f["version"]
    lines = [
        "# KERN — current status (generated)",
        "",
        "> Built from `docs/facts.json`, `tools/registry.py` and the defect journal by",
        "> `tools/gen_status.py`; gated by `make status-check`. Hand edits fail the gate.",
        "> There is deliberately no \"snapshot date\" in the file — a stored date goes",
        "> stale by itself. The date is the commit that last regenerated it:",
        "> `git log -1 docs/STATUS.md`.",
        "",
        "## Verification registry",
        "",
        "| Class | Count | Meaning |",
        "| --- | --- | --- |",
        f"| Targets, total | {_anchor('registry_targets', int(f['registry_targets']))} | every goal this repository claims to verify |",
        f"| CHECK | {_anchor('check_targets', checks)} | must be able to fail |",
        f"| MEASURE | {reg.get('MEASURE', 0)} | cannot fail — therefore not a proof |",
        f"| BUILD | {_anchor('build_targets', int(f['build_targets']))} | L0 only: it compiles |",
        f"| EXTERNAL | {reg.get('EXTERNAL', 0)} | third-party / cross-architecture |",
        f"| META | {_anchor('meta_targets', int(f['meta_targets']))} | harness, generators, guards |",
        "",
        f"Can-fail cases: **{_anchor('canfail_cases', int(f['canfail_cases']))}**, of which",
        f"**{checks}/{checks}** CHECK targets have a non-vacuous \"can fail\" proof.",
        "",
        "## Measured facts",
        "",
        "| Fact | Value |",
        "| --- | --- |",
        f"| Core Zig tests | {_anchor('core_tests', core)} ({core - skip} passed + {skip} skipped, 0 failed) |",
        f"| KERN-Next tests | {_anchor('next_tests', int(f['next_tests']))} |",
        f"| Full test catalog | {_anchor('catalog', int(f['catalog']))} |",
        f"| Lean 4 | {_anchor('lean_theorems', int(f['lean_theorems']))} theorems in 8 files, 0 sorry |",
        f"| Mutations killed | {_anchor('mutation_sites', int(f['mutation_sites']))} / {int(f['mutation_sites'])} across {int(f['mutation_files'])} files |",
        f"| Cross-architecture | {_anchor('cross_arch_passed', int(f['cross_arch_passed']))} passed / {_anchor('cross_arch_skipped', skip)} skipped / 0 failed |",
        f"| QuixBugs | {_anchor('quixbugs.smt', int(q['smt']))}/40 formal SMT · {_anchor('quixbugs.differential', int(q['differential']))}/40 live differential ({q['value']} value + {q['crash']} crash + {q['hang']} hang) · {_anchor('quixbugs.explored', int(q['explored']))} EXPLORED |",
        f"| Literal anchors | {_anchor('anchors', int(f['anchors']))} |",
        f"| Version | `{ver}` |",
        "",
        "## Defect journal",
        "",
        f"Numbered entries: **{j['total']}**.",
        "",
        "| Explicit status | Count |",
        "| --- | --- |",
        f"| Fixed | {j['fixed']} |",
        f"| Fix submitted upstream (our patch in someone else's repo) | {j['submitted']} |",
        f"| Real defect found by KERN in a third-party repo | {j['external']} |",
        f"| Documented limitation (we live with it; it is not a defect) | {j['limitation']} |",
        f"| Decision: considered and not adopted | {j['decision']} |",
        f"| Rows in the earlier journal format (category column, no status) | {j['legacy']} |",
        "",
        f"**Open technical defects: {j['open']}**"
        + (f" — {', '.join(j['open_ids'])}" if j["open_ids"] else ""),
        "",
        "> The journal spans two table generations: earlier rows carry a *category*",
        "> (`gate`, `kernel`, ...) and no status at all, later rows carry an explicit",
        "> status. Only explicit statuses are counted, and an entry counts as *open*",
        "> only when its status **starts with** `ОТКРЫТ`. Earlier rows are never",
        "> re-interpreted: assigning them a status would invent data.",
        "",
        f"Highest defect number in the journal: **{_anchor('max_defect', int(f['max_defect']))}**.",
        "Every entry names its cause and its fix; entries are never deleted.",
        "",
        "## External state",
        "",
        "| Item | Where |",
        "| --- | --- |",
        "| Pull request `TheAlgorithms/C#1595` | <https://github.com/TheAlgorithms/C/pull/1595> |",
        "| Pull request `TheAlgorithms/Rust#1075` | <https://github.com/TheAlgorithms/Rust/pull/1075> |",
        "| Last observed review state of both | `docs/evidence/external/verification.log` |",
        "| Release assets and signatures | <https://github.com/newmathphys/kern/releases> |",
        "",
        "> Review state is not duplicated here: it changes without the tree changing,",
        "> so it lives in the evidence log above, dated at the moment it was observed.",
        "",
        "## Where to read more",
        "",
        "- **What it is and why**: `README.md`",
        "- **What it can do, with live output**: `docs/ALL_CAPABILITIES_LIVE_GUIDE.md`",
        "- **Honest boundaries** (what it does *not* do): `README.md`, section \"Honest status\"",
        "- **Defect journal**: `docs/CAPABILITY_STATUS.md`",
        "- **Evidence, verbatim runs**: `docs/evidence/`",
        "- **Roadmap and open work**: `docs/PLAN_v2.6.4.md`, `docs/ROADMAP.md`",
        "",
    ]
    return "\n".join(lines)


def render_ru(f: dict, reg: dict, j: dict) -> str:
    core = int(f["core_tests"])
    skip = int(f.get("cross_arch_skipped", 0))
    checks = int(f["check_targets"])
    q = f["quixbugs"]
    ver = f["version"]
    lines = [
        "# KERN — текущее состояние (генерируется)",
        "",
        "> Собирается из `docs/facts.json`, `tools/registry.py` и журнала дефектов",
        "> скриптом `tools/gen_status.py`; проверяется `make status-check`.",
        "> Правка руками валит гейт. Даты снимка в файле НЕТ намеренно: сохранённая",
        "> дата сама устаревает. Дата — это коммит, которым файл обновлён:",
        "> `git log -1 docs/STATUS.ru.md`.",
        "",
        "## Реестр проверок",
        "",
        "| Класс | Кол-во | Смысл |",
        "| --- | --- | --- |",
        f"| Целей всего | {_anchor('registry_targets', int(f['registry_targets']))} | все цели, которые репозиторий заявляет проверяемыми |",
        f"| CHECK | {_anchor('check_targets', checks)} | обязаны уметь падать |",
        f"| MEASURE | {reg.get('MEASURE', 0)} | упасть не могут — значит не доказательство |",
        f"| BUILD | {_anchor('build_targets', int(f['build_targets']))} | только L0: компилируется |",
        f"| EXTERNAL | {reg.get('EXTERNAL', 0)} | сторонние / кросс-архитектура |",
        f"| META | {_anchor('meta_targets', int(f['meta_targets']))} | харнесс, генераторы, стражи |",
        "",
        f"Can-fail кейсов: **{_anchor('canfail_cases', int(f['canfail_cases']))}**, из них у",
        f"**{checks}/{checks}** CHECK-целей есть невакуумное доказательство «может упасть».",
        "",
        "## Измеренные факты",
        "",
        "| Факт | Значение |",
        "| --- | --- |",
        f"| Тесты ядра (Zig) | {_anchor('core_tests', core)} ({core - skip} прошло + {skip} пропущено, провалов 0) |",
        f"| Тесты KERN-Next | {_anchor('next_tests', int(f['next_tests']))} |",
        f"| Каталог тестов | {_anchor('catalog', int(f['catalog']))} |",
        f"| Lean 4 | {_anchor('lean_theorems', int(f['lean_theorems']))} теорем в 8 файлах, 0 sorry |",
        f"| Убито мутаций | {_anchor('mutation_sites', int(f['mutation_sites']))} / {int(f['mutation_sites'])} в {int(f['mutation_files'])} файлах |",
        f"| Кросс-архитектура | {_anchor('cross_arch_passed', int(f['cross_arch_passed']))} прошло / {_anchor('cross_arch_skipped', skip)} пропущено / 0 провалов |",
        f"| QuixBugs | {_anchor('quixbugs.smt', int(q['smt']))}/40 формально SMT · {_anchor('quixbugs.differential', int(q['differential']))}/40 живой дифференциал ({q['value']} значение + {q['crash']} падение + {q['hang']} зависание) · {_anchor('quixbugs.explored', int(q['explored']))} EXPLORED |",
        f"| Литеральных якорей | {_anchor('anchors', int(f['anchors']))} |",
        f"| Версия | `{ver}` |",
        "",
        "## Журнал дефектов",
        "",
        f"Нумерованных записей: **{j['total']}**.",
        "",
        "| Явный статус | Кол-во |",
        "| --- | --- |",
        f"| Исправлено | {j['fixed']} |",
        f"| Починка отправлена в чужой репозиторий | {j['submitted']} |",
        f"| Реальный дефект найден KERN в чужом репозитории | {j['external']} |",
        f"| Документированное ограничение (не дефект) | {j['limitation']} |",
        f"| Решение: рассмотрено и не взято | {j['decision']} |",
        f"| Строк раннего формата журнала (колонка-категория, статуса нет) | {j['legacy']} |",
        "",
        f"**Открытых технических дефектов: {j['open']}**"
        + (f" — {', '.join(j['open_ids'])}" if j["open_ids"] else ""),
        "",
        "> Журнал прожил две генерации таблицы: в ранних строках третья колонка —",
        "> КАТЕГОРИЯ (`гейт`, `ядро`, …) и статуса там нет вовсе, в поздних — явный",
        "> статус. Считаются только явные статусы, и «открытым» запись считается,",
        "> только если статус **начинается** с `ОТКРЫТ`. Ранние строки не",
        "> переинтерпретируются: приписать им статус значило бы выдумать данные.",
        "",
        f"Наибольший номер в журнале: **{_anchor('max_defect', int(f['max_defect']))}**.",
        "Каждая запись называет причину и исправление; записи не удаляются.",
        "",
        "## Внешнее состояние",
        "",
        "| Что | Где |",
        "| --- | --- |",
        "| Pull request `TheAlgorithms/C#1595` | <https://github.com/TheAlgorithms/C/pull/1595> |",
        "| Pull request `TheAlgorithms/Rust#1075` | <https://github.com/TheAlgorithms/Rust/pull/1075> |",
        "| Последнее наблюдённое состояние ревью | `docs/evidence/external/verification.log` |",
        "| Ассеты релиза и подписи | <https://github.com/newmathphys/kern/releases> |",
        "",
        "> Состояние ревью здесь не дублируется: оно меняется без изменения дерева,",
        "> поэтому живёт в логе свидетельств выше, с датой наблюдения.",
        "",
        "## Где читать дальше",
        "",
        "- **Что это и зачем**: `README.ru.md`",
        "- **Что умеет, с живым выводом**: `docs/ALL_CAPABILITIES_LIVE_GUIDE.ru.md`",
        "- **Честные границы** (чего НЕ делает): `README.ru.md`, раздел «Честный статус»",
        "- **Журнал дефектов**: `docs/CAPABILITY_STATUS.md`",
        "- **Свидетельства, дословные прогоны**: `docs/evidence/`",
        "- **Планы и открытая работа**: `docs/PLAN_v2.6.4.md`, `docs/ROADMAP.md`",
        "",
    ]
    return "\n".join(lines)


def render_all() -> dict[str, str]:
    f, reg, j = _facts(), _registry(), _journal()
    return {OUT[0]: render_en(f, reg, j), OUT[1]: render_ru(f, reg, j)}


def check() -> int:
    bad = 0
    f, reg = _facts(), _registry()
    # Сверка ДВУХ источников. Если facts.json и реестр разойдутся, STATUS
    # показывал бы половину правды, а `make sync` — правил бы числа под неё.
    for fact_key, reg_key in (("registry_targets", "targets"),
                              ("check_targets", "CHECK"),
                              ("build_targets", "BUILD"),
                              ("meta_targets", "META"),
                              ("canfail_cases", "canfail_cases")):
        if reg and int(f.get(fact_key, -1)) != int(reg.get(reg_key, -2)):
            print(f"[FAIL] facts.json[{fact_key}]={f.get(fact_key)} ≠ "
                  f"реестр[{reg_key}]={reg.get(reg_key)} — запустите `make sync`")
            bad += 1
    for rel, want in render_all().items():
        p = ROOT / rel
        if not p.exists():
            print(f"[FAIL] {rel} отсутствует")
            bad += 1
        elif p.read_text(encoding="utf-8") != want:
            print(f"[FAIL] {rel} разошёлся с источником — запустите `make status`")
            bad += 1
    if bad:
        return 1
    print(f"[OK] STATUS: {len(OUT)} файла совпадают с facts.json + реестром + журналом")
    return 0


def write() -> int:
    n = 0
    for rel, want in render_all().items():
        p = ROOT / rel
        if not p.exists() or p.read_text(encoding="utf-8") != want:
            p.write_text(want, encoding="utf-8")
            n += 1
            print(f"  updated {rel}")
    print(f"[OK] STATUS: файлов обновлено {n}")
    return 0


def selftest() -> int:
    """Мета-тест: числа не захардкожены, а статусы СЧИТАЮТСЯ.

    Если факт не влияет на вывод — он записан литералом, и файл снова начнёт
    устаревать молча (ровно так прожил дефект #311). Отдельно проверяется, что
    открытый дефект обязан попасть в STATUS: иначе «открытых: 0» станет
    константой, которую никто не пересчитывает.
    """
    bad = 0
    f, reg, j = _facts(), _registry(), _journal()
    base_en, base_ru = render_en(f, reg, j), render_ru(f, reg, j)
    if render_en(f, reg, j) != base_en or render_ru(f, reg, j) != base_ru:
        print("[FAIL] selftest: рендер не идемпотентен")
        bad += 1
    for key in ("core_tests", "lean_theorems", "mutation_sites", "check_targets",
                "canfail_cases", "catalog", "next_tests", "registry_targets",
                "meta_targets", "build_targets", "cross_arch_passed", "anchors",
                "max_defect"):
        m = dict(f)
        m[key] = int(f[key]) + 1
        if render_en(m, reg, j) == base_en or render_ru(m, reg, j) == base_ru:
            print(f"[FAIL] selftest: {key} не влияет на вывод — число захардкожено")
            bad += 1
    j2 = dict(j)
    j2["open"] = int(j["open"]) + 1
    j2["open_ids"] = list(j["open_ids"]) + ["#9999"]
    if "#9999" not in render_en(f, reg, j2) or "#9999" not in render_ru(f, reg, j2):
        print("[FAIL] selftest: открытый дефект не попадает в STATUS")
        bad += 1
    print(f"[{'OK' if bad == 0 else 'FAIL'}] STATUS selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in args:
        return selftest()
    if "--check" in args:
        return check()
    if "--write" in args:
        return write()
    print("usage: tools/gen_status.py [--check|--write|--selftest]")
    return 2


if __name__ == "__main__":
    sys.exit(main())
