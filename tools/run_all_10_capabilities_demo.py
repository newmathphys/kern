#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
"""Live demo of the 10 KERN capabilities -> docs/ALL_CAPABILITIES_LIVE_GUIDE.ru.md

Every section runs the real command and embeds the REAL output. Nothing is
written by hand, so the guide cannot drift from the code.

Usage: python3 tools/run_all_10_capabilities_demo.py [--write]
"""
from __future__ import annotations
import os, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "ALL_CAPABILITIES_LIVE_GUIDE.ru.md"
GUIDE_EN = ROOT / "docs" / "ALL_CAPABILITIES_LIVE_GUIDE.md"
EVID = ROOT / "docs" / "evidence"
ZIG = Path(os.environ.get("ZIG", Path.home() / "opt/zig-x86_64-linux-0.17.0/zig"))


def env() -> dict:
    e = dict(os.environ)
    e["PATH"] = f"{ROOT/'.venv/bin'}:{ROOT/'zig-out/bin'}:{ZIG.parent}:{e.get('PATH','')}"
    return e


def run(cmd, cwd=ROOT, timeout=600, shell=False):
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       timeout=timeout, env=env(), shell=shell)
    return r.returncode, (r.stdout + r.stderr).strip()


def clip(text: str, lines: int = 14) -> str:
    ls = text.splitlines()
    return "\n".join(ls[:lines]) + ("\n..." if len(ls) > lines else "")


SECTIONS: list[tuple[str, str, str, str]] = []
EN_TEXT = {
 1: ("1-2. Overflow and division by zero: KERN verdict + real compilers",
     "KERN checks a function over the whole type domain, not on three samples. Then the "
     "counterexamples are replayed by REAL toolchains: python3, gcc -fsanitize=undefined, "
     "rustc -C overflow-checks=on, zig run."),
 2: ("3. Diagnosis: which input rule is missing",
     "When a function is refuted, KERN searches for the missing precondition, re-verifies "
     "every hypothesis with a second Z3 run and NEVER edits the file."),
 3: ("4. Contract lock: catches a live model rewriting the spec",
     "Every @kern:requires/ensures is sealed with a hash. In a live experiment DeepSeek "
     "and GLM, given an UNSATISFIABLE contract, narrowed requires (leaving ensures alone) - "
     "the lock blocks exactly that. Below: the check on the current tree."),
 4: ("5. Refactoring equivalence: what a model broke and what it did not",
     "Two versions of a function are compared without contracts. EQUIVALENT is reported "
     "ONLY when the in-house proof checker accepted the derivation (QueryKind.equivalence)."),
 5: ("6. Bug hunter with no contracts at all",
     "It reads argument types (including standard Python annotations) and builds up to 250 "
     "hostile inputs per function: empty lists, strings, boundaries. On QuixBugs it catches "
     "40/40 bugs by live execution."),
 6: ("7. [VACUOUS] conditions and hard / [advisory] classes",
     "`x > 10 and x < 5` is unsatisfiable: a plain test would say 'green', KERN honestly "
     "marks the vacuum. An [advisory] violation yields T_advisory, which is NEVER added to "
     "the proven counter T."),
 7: ("8. Belnap B4 logic, 7 axes, evidence ledger (T + F = B)",
     "timeout and nonlinearity are N, not 'a bug' (hence FP = 0). A conflict of T and F "
     "gives B. The conformance exam checks 12 sections including add/retract and rejection "
     "of negative SCCs."),
 8: ("9. Architecture graph and forbidden negative cycles",
     "An exact import graph is built (KERN itself and an external project); SCC analysis "
     "rejects negative recursive cycles (NegativeRecursiveCycle)."),
 9: ("10. .kimg container, KERNFS, KERN-X and external signature check",
     "Any directory (including a cloned foreign repository) is packed into .kimg with a "
     "Merkle tree; fsck verifies integrity, inspect prints the manifest, diff finds the "
     "changed file. The project signature is checked with a public key."),
}


def section(title: str, why: str, cmd: str, out: str) -> None:
    SECTIONS.append((title, why, cmd, out))


print("1/10 переполнение + наземная проверка компиляторами...", flush=True)
rc, out = run([sys.executable, "tools/anti_self_deception_check.py"])
section("1-2. Переполнение и деление на ноль: вердикт KERN + живые компиляторы",
        "KERN проверяет функцию не на трёх примерах, а на всём домене типа. "
        "Затем контрпримеры переигрываются НАСТОЯЩИМИ инструментами: python3, "
        "gcc -fsanitize=undefined, rustc -C overflow-checks=on, zig run.",
        "make anti-self-deception-check", out)

print("3/10 explain --hypotheses...", flush=True)
rc, out = run([sys.executable, "tools/kern_contracts.py", "explain", "--hypotheses",
               "audits/codecheck/py_abs_bad.py"])
section("3. Диагност: каких входных правил не хватает",
        "Когда функция опровергнута, KERN сам ищет пропущенное предусловие, "
        "перепроверяет каждую гипотезу вторым прогоном Z3 и НЕ правит файл.",
        "python3 tools/kern_contracts.py explain --hypotheses audits/codecheck/py_abs_bad.py", out)

print("4/10 замок контрактов...", flush=True)
rc, out = run(["make", "contracts-lock-check"])
section("4. Замок контрактов: ловит подмену ТЗ живой моделью",
        "Все @kern:requires/ensures запечатаны хешами. В живом эксперименте DeepSeek "
        "и GLM, получив НЕВЫПОЛНИМЫЙ контракт, сузили requires (ensures не тронули) — "
        "замок это блокирует. Ниже — проверка на текущем дереве.",
        "make contracts-lock-check", out)

print("5/10 эквивалентность рефакторинга...", flush=True)
orig = EVID / "refactor" / "clamp_orig.py"
ref = EVID / "refactor" / "clamp_opencode_deepseek-v4.1-flash-free.py"
if orig.exists() and ref.exists():
    rc, out = run([sys.executable, "tools/kern_contracts.py", "--diff-equiv", str(orig), str(ref)])
    cmd = f"python3 tools/kern_contracts.py --diff-equiv {orig.name} {ref.name}"
else:
    out, cmd = "(артефакты рефакторинга не найдены)", "make diff-equiv"
section("5. Эквивалентность рефакторинга: что модель сломала, а что нет",
        "Без контрактов сравниваются две версии функции. Вердикт EQUIVALENT выдаётся "
        "ТОЛЬКО когда внутренний пруф-чекер принял вывод (QueryKind.equivalence).", cmd, out)

print("6/10 trace_explorer...", flush=True)
mini = Path("/tmp/kern-demo-blind")
for d in ("python_programs", "correct_python_programs"):
    (mini / d).mkdir(parents=True, exist_ok=True)
src = Path("/tmp/kern-megatest/repos/boltons/boltons/mathutils.py")
if src.exists():
    import ast
    text = src.read_text(encoding="utf-8")
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef):
            code = ast.get_source_segment(text, node) + "\n"
            for d in ("python_programs", "correct_python_programs"):
                (mini / d / f"{node.name}.py").write_text(code, encoding="utf-8")
    rc, out = run([sys.executable, "tools/trace_explorer.py", str(mini)], timeout=600)
    cmd = f"python3 tools/trace_explorer.py {mini}  # функции boltons по алфавиту"
else:
    out, cmd = "(клон boltons не найден)", "python3 tools/trace_explorer.py <датасет>"
section("6. Охотник за багами без единого контракта",
        "Читает типы аргументов (включая стандартные аннотации Python) и сам строит "
        "до 250 ядовитых входов на функцию: пустые списки, строки, границы. "
        "На QuixBugs ловит 40/40 багов живым вызовом.", cmd, out)

print("7/10 VACUOUS + advisory...", flush=True)
with tempfile.TemporaryDirectory() as td:
    vac = Path(td) / "vacuous.py"
    vac.write_text("# @kern:requires x > 10 and x < 5\n# @kern:ensures result > 0\n"
                   "def bad(x: int) -> int:\n    return x\n", encoding="utf-8")
    rc1, out1 = run([sys.executable, "tools/kern_contracts.py", str(vac)])
rc2, out2 = run([sys.executable, "tools/kern_contracts.py", "examples/contracts_advisory_demo.py"])
section("7. Пустые условия [VACUOUS] и классы hard / [advisory]",
        "Условие `x > 10 and x < 5` невыполнимо: обычный тест сказал бы «зелено», "
        "KERN честно помечает вакуум. А `[advisory]`-нарушение даёт T_advisory, "
        "который НИКОГДА не складывается со счётчиком доказанного T.",
        "python3 tools/kern_contracts.py <vacuous.py>  |  examples/contracts_advisory_demo.py",
        "--- вакуумное предусловие ---\n" + out1 + "\n\n--- классы контрактов ---\n" + out2)

print("8/10 Белнап B4 / conformance...", flush=True)
rc, out = run([sys.executable, "tools/conformance_check.py"], timeout=900)
section("8. Логика Белнапа B4, 7 осей, журнал свидетельств (T + F = B)",
        "`timeout` и нелинейность — это N, а не «баг» (поэтому FP = 0). "
        "Конфликт T и F даёт B. Конформанс-экзамен проверяет 12 разделов, "
        "включая add/retract и отказ на отрицательных SCC.",
        "make conformance-check", out)

print("9/10 kernx graph...", flush=True)
rc, out = run(["zig-out/bin/kernx", "graph"], timeout=300)
import json as _json
try:
    g = _json.loads(out)
    stats = f"модулей {len(g['nodes'])}, рёбер {len(g['edges'])}"
except Exception:
    stats = "(граф не разобран)"
rc2, out2 = run(["zig-out/bin/kernx", "graph", "--root", "/tmp/kern-megatest/repos/zig-clap"], timeout=300)
try:
    g2 = _json.loads(out2)
    stats2 = f"модулей {len(g2['nodes'])}, рёбер {len(g2['edges'])}"
except Exception:
    stats2 = "(внешний граф не разобран)"
section("9. Граф архитектуры и запрет отрицательных циклов",
        "Строится точный граф импортов (сам KERN и внешний проект), SCC-анализ "
        "отвергает отрицательные рекурсивные циклы (NegativeRecursiveCycle).",
        "kernx graph  |  kernx graph --root <внешний проект>",
        f"KERN: {stats}\nzig-clap: {stats2}")

print("10/10 .kimg + аттестат...", flush=True)
repo = Path("/tmp/kern-megatest/repos/zig-clap")
parts = []
if repo.exists():
    v1 = Path("/tmp/kern-demo-v1.kimg")
    rc, o = run(["zig-out/bin/kernc", "pack-dir", str(repo), "-o", str(v1)])
    parts.append("$ kernc pack-dir ... -o v1.kimg\n" + o)
    rc, o = run(["zig-out/bin/kernc", "fsck", str(v1)])
    parts.append("$ kernc fsck v1.kimg\n" + o)
    rc, o = run(["zig-out/bin/kernc", "inspect", str(v1)])
    parts.append("$ kernc inspect v1.kimg\n" + clip(o, 2))
rc, o = run([sys.executable, "tools/verify_attestation.py"])
parts.append("$ make verify-attestation\n" + clip(o, 6))
section("10. Контейнер .kimg, KERNFS, KERN-X и внешняя проверка подписи",
        "Любая папка (в том числе скачанный чужой репозиторий) пакуется в .kimg "
        "с деревом Меркла; fsck проверяет целостность, inspect печатает паспорт, "
        "diff находит изменённый файл. Подпись проекта проверяется публичным ключом.",
        "kernc pack-dir / fsck / inspect / diff  ·  make verify-attestation",
        "\n\n".join(parts))

print("пишу путеводители (RU + EN)...", flush=True)
NL = chr(10)
FACTS = ("> Facts (synced by `make sync`): core <!-- fact:core_tests -->402 · "
         "next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->465 · "
         "CHECK <!-- fact:check_targets -->146 · cases <!-- fact:canfail_cases -->167 · "
         "anchors <!-- fact:anchors -->131 · registry <!-- fact:registry_targets -->183 · "
         "META <!-- fact:meta_targets -->22 · Lean <!-- fact:lean_theorems -->143 · "
         "QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff.")

ru = ["# Все 10 возможностей KERN: живые примеры и дословный вывод", "",
      "> Документ **сгенерирован** скриптом `tools/run_all_10_capabilities_demo.py`:",
      "> каждый раздел — это реально выполненная команда и её настоящий вывод.",
      "> Ничего не написано руками, поэтому документ не может разойтись с кодом.", "",

      "Запуск: `make demo-all`", "", FACTS, ""]
en = ["# All 10 KERN capabilities: live examples and verbatim output", "",
      "> This document is **generated** by `tools/run_all_10_capabilities_demo.py`:",
      "> every section is a command that was really executed, with its real output.",
      "> Nothing is written by hand, so the document cannot drift from the code.", "",
      "Run: `make demo-all`", "", FACTS, ""]
for i, (title, why, cmd, out) in enumerate(SECTIONS, 1):
    t_en, w_en = EN_TEXT.get(i, (title, why))
    ru += [f"## {title}", "", f"**Зачем.** {why}", "", "**Команда.**", "```bash", cmd, "```", "",
           "**Реальный вывод:**", "```text", clip(out, 40), "```", ""]
    en += [f"## {t_en}", "", f"**Why.** {w_en}", "", "**Command.**", "```bash", cmd, "```", "",
           "**Real output:**", "```text", clip(out, 40), "```", ""]
if "--write" in sys.argv:
    GUIDE.write_text(NL.join(ru) + NL, encoding="utf-8")
    GUIDE_EN.write_text(NL.join(en) + NL, encoding="utf-8")
    (EVID / "demo_all_10.log").write_text(NL.join(en) + NL, encoding="utf-8")
    print(f"[OK] {GUIDE.name} ({len(ru)} строк) и {GUIDE_EN.name} ({len(en)} lines)")
else:
    print(NL.join(ru))

if __name__ == "__main__":
    pass
