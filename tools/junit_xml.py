#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""JUnit XML из прогонов KERN (шаг F1).

ЗАЧЕМ. Результаты проверок были видны только у нас: терминал и логи в
`docs/evidence/`. Внешний человек, подключивший KERN в свой конвейер, не видел
ничего — формата, который понимают GitHub Actions, IDE и любые CI-панели, у нас
не было вовсе (`grep junit` по репозиторию — пусто).

ЧЕСТНАЯ ГРАНИЦА ФОРМАТА. Раннер `zig build test` не печатает список тестов
построчно (он говорит с билд-раннером через `--listen=-`), поэтому «единица
отчёта» для него — ЦЕЛЬ, а не отдельный тест: один `<testcase>` на цель, с
временем и кодом возврата. Для `canfail` данные построчные (каждый кейс печатает
`[PASS] <имя> …`), поэтому кейсы попадают в отчёт отдельными `<testcase>` — но
берутся из УЖЕ СНЯТОГО лога, а не перепрогоняются: отчёт не имеет права занимать
часы и не должен менять дерево.

Выдумывать имена тестов, которых инструмент не сообщает, нельзя — это был бы
отчёт о прогоне, которого не было.

Запуск:  python3 tools/junit_xml.py [--out FILE] [--targets a,b,c] [--selftest]
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "evidence" / "junit.xml"
CANFAIL_LOG = ROOT / "docs" / "evidence" / "canfail.log"

# Компилятор берём из окружения, как это делает Makefile (`ZIG ?= zig`).
ZIG = __import__("os").environ.get("ZIG", "zig")

# Набор по умолчанию — быстрые и содержательные цели. Полный набор доступен
# через `--targets`, но по умолчанию он не берётся: отчёт не должен занимать
# часы (canfail — ~15 минут, Lean — минуты).
DEFAULT_TARGETS = (
    "test",
    "test-next",
    "version-check",
    "metrics-guard",
    "claims-audit",
    "docs-parity",
    "sync-check",
    "status-check",
    "llms-check",
    "charter-check",
)

# ДЕФЕКТ, НАЙДЕННЫЙ ЗДЕСЬ ЖЕ. `make test` -> `zig build test`, а билд-раннер Zig
# КЭШИРУЕТ запуск тестов: `zig build test --summary all` печатает
# «run test cached», и цель возвращает 0 за 0.1 с, НЕ ЗАПУСКАЯ тесты. Для отчёта
# это недопустимо: «test: passed» читалось бы как «тесты прошли», хотя они не
# выполнялись. Поэтому тестовые цели прогоняются командами, которые исполняются
# ВСЕГДА — теми же, что снимают свидетельства в `tools/collect_evidence.sh`
# (там это уже было сделано правильно; расхождение жило только в `make test`).
ALWAYS_RUN = {
    "test": [ZIG, "test", "--dep", "compat",
             "-Mroot=src/test_root.zig", "-Mcompat=src/compat.zig"],
    # `test-next` идёт через билд-раннер, и свежий `--cache-dir` заставляет его
    # ПЕРЕСОБИРАТЬ всё (минуты) — неверная цена за отчёт. Поэтому берём
    # `--summary all` и ЧЕСТНО помечаем попадание в кэш как «не перезапускалось»
    # (см. `cached`), а не выдаём кэш за прогон.
    "test-next": [ZIG, "build", "test-next", "--summary", "all"],
}

ANSI = re.compile(r"\x1b\[[0-9;]*m")
CASE = re.compile(r"^\s*\[(PASS|FAIL|SKIP)\]\s+(\S+)")


def was_cached(out: str) -> bool:
    """Билд-раннер Zig прямо говорит `cached` — значит шаг НЕ исполнялся."""
    return bool(re.search(r"\bcached\b", _clean(out)))


def _clean(text: str) -> str:
    """Снять ANSI-раскраску: цвет не должен попадать в XML."""
    return ANSI.sub("", text)


def _tail(text: str, n: int = 12) -> str:
    lines = [l for l in _clean(text).strip().splitlines() if l.strip()]
    return "\n".join(lines[-n:])


def run_target(name: str) -> tuple[int, float, str]:
    """Прогон цели. Для тестовых целей — команда, которая исполняется ВСЕГДА.

    Причина в комментарии к `ALWAYS_RUN`: `zig build test` может вернуть
    «run test cached», и тогда «passed» означало бы «не запускалось».
    """
    cmd = ALWAYS_RUN.get(name, ["make", name])
    t0 = time.time()
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    dt = time.time() - t0
    return p.returncode, dt, (p.stdout or "") + (p.stderr or "")


def test_count(out: str) -> int | None:
    """Сколько тестов реально прошло (Zig печатает `All N tests passed`)."""
    m = re.search(r"All\s+(\d+)\s+tests?\s+passed", out)
    return int(m.group(1)) if m else None


def cases_from_log() -> list[tuple[str, str]]:
    """Кейсы canfail — из СНЯТОГО лога (не перепрогоняем)."""
    if not CANFAIL_LOG.exists():
        return []
    out: list[tuple[str, str]] = []
    for line in CANFAIL_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        m = CASE.match(line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def build_xml(targets: tuple[str, ...], run: bool = True) -> ET.ElementTree:
    root = ET.Element("testsuites", {"name": "kern"})
    t_all = 0.0
    n_fail = 0

    suite = ET.SubElement(root, "testsuite", {"name": "kern targets"})
    for name in targets:
        if run:
            rc, dt, out = run_target(name)
        else:
            rc, dt, out = 0, 0.0, ""
        t_all += dt
        tc = ET.SubElement(suite, "testcase",
                           {"classname": "kern", "name": name, "time": f"{dt:.1f}"})
        n = test_count(out)
        cached = was_cached(out)
        if cached:
            # Кэш — это НЕ прогон. Пометка не даёт прочитать «passed» как
            # «тесты выполнялись».
            ET.SubElement(tc, "skipped", {"message": "не перезапускалось: попадание в кэш сборки"})
        if n is not None:
            # Сколько тестов РЕАЛЬНО прошло — чтобы «passed» нельзя было
            # прочитать как «не запускалось».
            props = ET.SubElement(tc, "properties")
            ET.SubElement(props, "property",
                          {"name": "tests_executed", "value": str(n)})
        if rc != 0:
            n_fail += 1
            f = ET.SubElement(tc, "failure", {"message": f"rc={rc}"})
            f.text = _tail(out) or f"{name} вернул rc={rc}"
    suite.set("tests", str(len(targets)))
    suite.set("failures", str(n_fail))
    suite.set("time", f"{t_all:.1f}")

    cases = cases_from_log()
    if cases:
        cs = ET.SubElement(root, "testsuite", {"name": "canfail cases (from log)"})
        cf = 0
        for verdict, cname in cases:
            tc = ET.SubElement(cs, "testcase",
                               {"classname": "canfail", "name": cname, "time": "0"})
            if verdict == "FAIL":
                cf += 1
                ET.SubElement(tc, "failure", {"message": "кейс не покраснел (вакуумный)"})
            elif verdict == "SKIP":
                ET.SubElement(tc, "skipped", {"message": "пропущен"})
        cs.set("tests", str(len(cases)))
        cs.set("failures", str(cf))
        cs.set("time", "0")

    root.set("tests", str(len(targets) + len(cases)))
    root.set("failures", str(n_fail + sum(1 for v, _ in cases if v == "FAIL")))
    root.set("time", f"{t_all:.1f}")
    return ET.ElementTree(root)


def write_xml(tree: ET.ElementTree, path: Path) -> None:
    ET.indent(tree, space="  ")
    path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in args:
        return selftest()
    targets = DEFAULT_TARGETS
    out = OUT
    for i, a in enumerate(args):
        if a == "--targets" and i + 1 < len(args):
            targets = tuple(x.strip() for x in args[i + 1].split(",") if x.strip())
        if a == "--out" and i + 1 < len(args):
            out = Path(args[i + 1])
    tree = build_xml(targets)
    write_xml(tree, out)
    root = tree.getroot()
    print(f"[OK] JUnit XML: {out.relative_to(ROOT)} | тестов {root.get('tests')} | "
          f"провалов {root.get('failures')} | {root.get('time')} с")
    return 1 if int(root.get("failures", "0")) else 0


def selftest() -> int:
    """Мета-тест: XML обязан разбираться стандартным парсером и нести провал.

    Проверяем две вещи, ради которых формат и существует: (1) файл валиден для
    чужого инструмента, (2) падение ЦЕЛИ попадает в отчёт как `<failure>`, а не
    растворяется в «всё прошло».
    """
    import tempfile
    bad = 0
    ok = build_xml(("version-check",), run=True)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "ok.xml"
        write_xml(ok, p)
        try:
            ET.parse(p)
            print("[OK] selftest: XML разбирается стандартным парсером")
        except ET.ParseError as e:
            print(f"[FAIL] selftest: XML невалиден: {e}")
            bad += 1
        if int(ok.getroot().get("failures", "0")):
            print("[FAIL] selftest: зелёная цель отмечена как провал")
            bad += 1

    # Подсадка: несуществующая цель обязана попасть в отчёт как <failure>.
    broken = build_xml(("no-such-target-xyz",), run=True)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "bad.xml"
        write_xml(broken, p)
        tree = ET.parse(p)
        fails = tree.getroot().findall(".//failure")
        if not fails:
            print("[FAIL] selftest: падение цели НЕ попало в отчёт")
            bad += 1
        else:
            print(f"[OK] selftest: падение цели попадает в отчёт ({len(fails)} failure)")
    print(f"[{'OK' if bad == 0 else 'FAIL'}] junit selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
