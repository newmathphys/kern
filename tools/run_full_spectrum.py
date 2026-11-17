#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""ПОЛИГОН FULL SPECTRUM: блок 01 (`kernc belnap` → нативная B4), 02 (`--heal`) и 04 (`--state-inv`).

ЗАЧЕМ. Механизмы KERN до сих пор демонстрировались РОВНО на одном примере
каждый. Один пример не отличает «режим работает» от «режим совпал с примером».
Здесь каждый режим прогоняется по корпусу карточек, и КАЖДАЯ карточка
проверяется ДВАЖДЫ:

  1. ВЕРДИКТ KERN — символически (∀-проверка инварианта или синтез гарда);
  2. НЕЗАВИСИМЫЙ ФИЗИЧЕСКИЙ ОРАКУЛ — не копия таблиц, а ВЫЧИСЛЕНИЕ:
     для `belnap` — B4 из первых принципов по парам свидетельств
     `(pos, neg) in {0,1}^2`; для `--heal` — CPython реально исполняет код
     (файл падает ДО, исполняется ПОСЛЕ и на обычных входах считает ВЕРНО);
     для `--state-inv` — последовательность вызовов проигрывается на объекте,
     инвариант проверяется ФИЗИЧЕСКИ.

ЗАКОН ЦЕЛОСТНОСТИ: `confirmed == total`. Любая неподтверждённая карточка —
rc=1, и витрины НЕ пишутся вовсе (зелёная галочка без доказательства = обман).

ИЗОЛЯЦИЯ: тексты карточек — ЧИСТЫЕ ДАННЫЕ (`benchmarks/full_spectrum/*.json`)
и материализуются в `tempfile.TemporaryDirectory()`. В дереве репозитория не
появляется ни одного `.py` с директивами `@kern:`, поэтому
`docs/contracts.lock.json` не задевается.

ЗАПУСК (нужен интерпретатор с z3 — штатно `.venv/bin/python`):
    .venv/bin/python tools/run_full_spectrum.py
    .venv/bin/python tools/run_full_spectrum.py --no-docs
    .venv/bin/python tools/run_full_spectrum.py --corpus benchmarks/full_spectrum/04_state_machines.json

ГРАНИЦА (названа вслух, а не спрятана): `--heal` синтезирует гарды ТОЛЬКО
для деления на ноль (`/`, `//`, `%`) — ровно то, что делает `_crash_sites`.
Выход за границы списка и «сдвинутый порог» он НЕ лечит, поэтому таких
карточек здесь нет: корпус не имеет права обещать больше инструмента.
"""
from __future__ import annotations

import argparse
import ast
import glob
import hashlib
import itertools
import json
import os
import re
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
KERN = os.path.join(TOOLS, "kern_contracts.py")
KERNC = os.path.join(ROOT, "zig-out", "bin", "kernc")
BENCH = os.path.join(ROOT, "benchmarks", "full_spectrum")
DOCS = os.path.join(ROOT, "docs")
PY = sys.executable

CRASH = "[CRASH PATH]"
MARK = "__ORACLE_JSON__"
MIN_SAFE_CHECKS = 12

# Обёртка физического оракула: карточка исполняется как модуль (KERN-код не
# импортируется), мутация — вторым модулем (если карточка её объявляет).
ORACLE_WRAPPER = '''import importlib.util
import itertools
import json
import sys


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load(sys.argv[1], "card")
mut = _load(sys.argv[2], "card_mut") if len(sys.argv) > 2 else None
RESULT = None
__ORACLE_SOURCE__
sys.stdout.write("__ORACLE_MARK__" + json.dumps(RESULT, ensure_ascii=False, default=str) + "\\n")
'''


def oracle_source(snippet):
    """Подставить тело оракула БЕЗ `%`-форматирования (символ `%` легален в коде)."""
    return ORACLE_WRAPPER.replace("__ORACLE_SOURCE__", snippet).replace(
        "__ORACLE_MARK__", MARK)


def run(cmd, cwd=None, timeout=180):
    """(rc, stdout, stderr). Таймаут назван кодом 124, а не тишиной."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=cwd or ROOT)
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", "[timeout %ss] %s" % (timeout, " ".join(cmd))


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def preflight():
    """Без z3 символическая половина карточки бессмысленна — падаем НАЗВАННО."""
    rc, out, err = run([PY, "-c", "import z3; print(z3.get_version_string())"])
    if rc != 0:
        tail = " ".join((err or out).strip().splitlines()[-1:]) or "import z3"
        return ("z3 недоступен для %s — прогон невозможен. Штатный запуск: "
                ".venv/bin/python tools/run_full_spectrum.py (%s)" % (PY, tail))
    return None


def oracle_json(out):
    """Достать машинный результат оракула из stdout (маркер + JSON)."""
    for line in out.splitlines():
        if line.startswith(MARK):
            try:
                return json.loads(line[len(MARK):])
            except json.JSONDecodeError:
                return None
    return None


def check_heal(card, tmpdir):
    """ДУГА ЦЕЛИКОМ: ДО (краш) -> --heal -> ПОСЛЕ (0 крашей + верный результат)."""
    errs = []
    probe = write_text(os.path.join(tmpdir, card["id"] + ".py"), card["code"])
    guards_expected = int(card["expect_guards"])

    rc_b, out_b, err_b = run([PY, probe])
    if rc_b == 0:
        errs.append("ДО: файл не падает физически (rc=0) — лечить нечего")
    elif "ZeroDivisionError" not in (out_b + err_b):
        errs.append("ДО: падение есть, но это не ZeroDivisionError")

    _rc, xout, _ = run([PY, KERN, "--xray", probe])
    crash_before = xout.count(CRASH)
    if crash_before != guards_expected:
        errs.append("--xray ДО: крашей %d, ожидалось %d" % (crash_before, guards_expected))

    rc_h, hout, herr = run([PY, KERN, "--heal", probe])
    if rc_h != 0:
        errs.append("--heal rc=%d" % rc_h)
    for needle in ("T (1,0)", "после патча: 0"):
        if needle not in (hout + herr):
            errs.append("--heal: в выводе нет «%s»" % needle)

    with open(probe, encoding="utf-8") as fh:
        patched = fh.read()
    guards = patched.count("[KERN HEAL]")
    if guards != guards_expected:
        errs.append("в исходник вставлено гардов %d, ожидалось %d" % (guards, guards_expected))

    bak = probe + ".bak"
    if not os.path.exists(bak):
        errs.append("бэкап <file>.bak не создан")
    else:
        with open(bak, encoding="utf-8") as fh:
            bak_src = fh.read()
        if bak_src != card["code"]:
            errs.append("бэкап НЕ равен исходнику")
        if "[KERN HEAL]" in bak_src:
            errs.append("бэкап содержит патч (обязан хранить оригинал)")

    _rc, xout2, _ = run([PY, KERN, "--xray", probe])
    crash_after = xout2.count(CRASH)
    if crash_after != 0:
        errs.append("--xray ПОСЛЕ: крашей %d, ожидалось 0" % crash_after)

    rc_a, out_a, err_a = run([PY, probe])
    if rc_a != 0:
        errs.append("ПОСЛЕ: python3 rc=%d — падение не снято" % rc_a)
    printed = out_a.strip()
    if printed != str(card["expect_stdout"]).strip():
        errs.append("ПОСЛЕ: stdout %r, ожидалось %r"
                    % (printed, str(card["expect_stdout"]).strip()))

    _rc, cout, _ = run([PY, KERN, probe])
    if "нарушено 0" not in cout:
        errs.append("повторная проверка контрактов: нет «нарушено 0»")
    if "НЕ РЕШЕНО 0" not in cout:
        errs.append("повторная проверка контрактов: есть НЕ РЕШЕНО")

    normal = card.get("normal") or []
    if normal:
        oracle = os.path.join(tmpdir, card["id"] + "_normal.py")
        write_text(oracle, (
            "import importlib.util, json, sys\n"
            "spec = importlib.util.spec_from_file_location('healed', sys.argv[1])\n"
            "m = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(m)\n"
            "res = []\n"
            "for expr, want in json.loads(sys.argv[2]):\n"
            "    got = eval(expr, {'__builtins__': {}}, dict(vars(m)))\n"
            "    ok = abs(float(got) - float(want)) <= 1e-9\n"
            "    res.append({'expr': expr, 'got': got, 'want': want, 'ok': ok})\n"
            "sys.stdout.write('%s' + json.dumps(res))\n" % MARK
        ))
        _rc, nout, nerr = run([PY, oracle, probe, json.dumps(normal)], cwd=tmpdir)
        parsed = oracle_json(nout)
        if not parsed:
            errs.append("обычные входы: оракул не дал результата (%s)"
                        % (" ".join((nout + nerr).split())[-120:] or "пусто"))
        else:
            for row in parsed:
                if not row["ok"]:
                    errs.append("ПОСЛЕ: гард сломал обычный вход %s -> %r (ожидалось %r)"
                                % (row["expr"], row["got"], row["want"]))
    return errs, {"crash_before": crash_before, "crash_after": crash_after,
                  "guards": guards, "rc_before": rc_b, "rc_after": rc_a}


def check_state_inv(card, tmpdir):
    """СИМВОЛ + ПЛОТЬ: KERN (∀) и физическая последовательность вызовов (∃)."""
    errs = []
    probe = write_text(os.path.join(tmpdir, card["id"] + ".py"), card["code"])

    rc, out, err = run([PY, KERN, "--state-inv", probe])
    text = out + err
    if rc != 0:
        errs.append("--state-inv rc=%d" % rc)
    if "[UNKNOWN]" in text:
        errs.append("есть [UNKNOWN]: нерешённое выдавать за доказанное нельзя")
    for fn in card["expect_fail"]:
        if ("[FAIL] %s: STATE INVARIANT VIOLATED" % fn) not in text:
            errs.append("KERN не поймал нарушение инварианта в %s" % fn)
    if card["expect_fail"] and "[КОНТРПРИМЕР]" not in text:
        errs.append("KERN напечатал FAIL без конкретного контрпримера")
    for fn in card["expect_pass"]:
        if ("[PASS] %s: PROVEN" % fn) not in text:
            errs.append("KERN не доказал инвариант для %s" % fn)

    mut_path = None
    mutation = card.get("mutation") or {}
    has_mutation = bool(mutation)
    if mutation:
        mut_path = write_text(os.path.join(tmpdir, card["id"] + "_mut.py"),
                              mutation["code"])
        _rc, mout, merr = run([PY, KERN, "--state-inv", mut_path])
        mtext = mout + merr
        if "[UNKNOWN]" in mtext:
            errs.append("мутация: [UNKNOWN]")
        for fn in mutation["expect_fail"]:
            if ("[FAIL] %s: STATE INVARIANT VIOLATED" % fn) not in mtext:
                errs.append("мутация: снятие гарда НЕ валит доказательство (%s)" % fn)

    oracle = os.path.join(tmpdir, card["id"] + "_oracle.py")
    write_text(oracle, oracle_source(card["oracle"]))
    argv = [PY, oracle, probe] + ([mut_path] if mut_path else [])
    rc_o, out_o, err_o = run(argv, cwd=tmpdir)
    res = oracle_json(out_o)
    if rc_o != 0 or not res:
        errs.append("физический оракул не дал результата (rc=%d): %s"
                    % (rc_o, " ".join((out_o + err_o).split())[-160:] or "пусто"))
        res = {}
    else:
        if int(res.get("unsafe_violations", 0)) < 1:
            errs.append("оракул НЕ воспроизвёл нарушение физически (unsafe_violations=%s)"
                        % res.get("unsafe_violations"))
        if int(res.get("safe_violations", 1)) != 0:
            errs.append("оракул нашёл нарушение в БЕЗОПАСНОМ переходе (%s)"
                        % res.get("safe_violations"))
        if int(res.get("safe_checks", 0)) < MIN_SAFE_CHECKS:
            errs.append("оракул проверил слишком мало последовательностей (%s < %d)"
                        % (res.get("safe_checks"), MIN_SAFE_CHECKS))
    return errs, {"unsafe_violations": res.get("unsafe_violations"),
                  "safe_violations": res.get("safe_violations"),
                  "safe_checks": res.get("safe_checks"),
                  "example": res.get("unsafe_example"),
                  "kern_note_en": ("[PASS] reference, 0 UNKNOWN + [FAIL] after guard removal"
                                  if has_mutation else
                                  "[FAIL] naive + [PASS] guarded, 0 UNKNOWN"),
                  "kern_note_ru": ("[PASS] эталон, 0 UNKNOWN + [FAIL] после снятия гарда"
                                  if has_mutation else
                                  "[FAIL] наивная + [PASS] защищённая, 0 UNKNOWN"),
                  "oracle_note_en": ("%s violation(s) on the unguarded twin · %s safe sequences, %s violation(s)"
                                     % (res.get("unsafe_violations"), res.get("safe_checks"),
                                        res.get("safe_violations"))
                                     if has_mutation else
                                     "%s concrete violation(s) found · %s safe sequences, %s violation(s)"
                                     % (res.get("unsafe_violations"), res.get("safe_checks"),
                                        res.get("safe_violations"))),
                  "oracle_note_ru": ("%s нарушений у близнеца без гарда · %s безопасных цепочек, %s нарушений"
                                     % (res.get("unsafe_violations"), res.get("safe_checks"),
                                        res.get("safe_violations"))
                                     if has_mutation else
                                     "%s конкретных нарушений найдено · %s безопасных цепочек, %s нарушений"
                                     % (res.get("unsafe_violations"), res.get("safe_checks"),
                                        res.get("safe_violations")))}


# ---------------------------------------------------------------------------
#  БЛОК 01: НАТИВНАЯ 4-ЗНАЧНАЯ ЛОГИКА БЕЛНАПА (kernc belnap)
# ---------------------------------------------------------------------------
# ОРАКУЛ СЧИТАЕТ B4 ИЗ ПЕРВЫХ ПРИНЦИПОВ, а не переписывает таблицу из Zig.
# Каждое значение — пара свидетельств (pos, neg) in {0,1}^2:
#     N = (0,0)  «нет свидетельств»     T = (1,0)  «только подтверждение»
#     F = (0,1)  «только опровержение»  B = (1,1)  «и то, и другое»
# Знание комбинируется ПОКОМПОНЕНТНО (OR — добавить информацию, AND — общая
# часть), истина — покомпонентной монотонностью:
#     join_k = (p1|p2, n1|n2)   meet_k = (p1&p2, n1&n2)   not = (n, p)
#     and_t  = (p1&p2, n1|n2)   or_t   = (p1|p2, n1&n2)
# Ни одна клетка не скопирована: символ получается ОБРАТНЫМ отображением пары.
BITS4 = {"N": (0, 0), "T": (1, 0), "F": (0, 1), "B": (1, 1)}
SYM4 = {(0, 0): "N", (1, 0): "T", (0, 1): "F", (1, 1): "B"}


def belnap_oracle(op, a, b=None):
    """Значение операции B4 из определения пар свидетельств (не таблица)."""
    p1, n1 = BITS4[a]
    if op == "not":
        return SYM4[(n1, p1)]
    p2, n2 = BITS4[b]
    if op == "join_k":
        return SYM4[(p1 | p2, n1 | n2)]
    if op == "meet_k":
        return SYM4[(p1 & p2, n1 & n2)]
    if op == "and_t":
        return SYM4[(p1 & p2, n1 | n2)]
    if op == "or_t":
        return SYM4[(p1 | p2, n1 & n2)]
    raise ValueError("неизвестная операция: %s" % op)


def kernc_belnap(args):
    return run([KERNC, "belnap"] + list(args), timeout=60)


def check_belnap(card, tmpdir):
    """KERN-вердикт = нативный вывод ядра; оракул = вычисление из пар битов."""
    errs = []
    if not (os.path.isfile(KERNC) and os.access(KERNC, os.X_OK)):
        return (["нет исполняемого %s — сначала `zig build` (kernc belnap живёт "
                 "в ядре Zig, а не в Python)" % os.path.relpath(KERNC, ROOT)], {})
    mode = card.get("mode", "ops")
    cells = 0

    if mode == "table":
        rc, out, err = kernc_belnap(["--table"])
        if rc != 0:
            errs.append("kernc belnap --table rc=%d: %s" % (rc, err.strip()[:90]))
        rows = [ln.split("|") for ln in out.splitlines() if ln.strip()]
        if len(rows) != 68:
            errs.append("--table: строк %d, ожидалось 68 (4 операции x 16 пар + 4 not)"
                        % len(rows))
        for row in rows:
            if len(row) == 4:
                op, a, b, got = row
            elif len(row) == 3:
                op, a, got = row
                b = None
            else:
                errs.append("--table: неразборчивая строка %r" % "|".join(row))
                continue
            want = belnap_oracle(op, a, b)
            cells += 1
            if got != want:
                errs.append("--table: %s(%s,%s) = %s, модель пар даёт %s"
                            % (op, a, b, got, want))
    else:
        calls = card.get("calls") or []
        if not calls:
            errs.append("карточка без вызовов (поле `calls` пусто)")
        for call in calls:
            op, a = call[0], call[1]
            b = call[2] if len(call) > 2 else None
            want = belnap_oracle(op, a, b)
            args = [op, a] + ([b] if b is not None else [])
            rc, out, err = kernc_belnap(args)
            got = out.strip()
            cells += 1
            if rc != 0:
                errs.append("kernc belnap %s rc=%d: %s"
                            % (" ".join(args), rc, err.strip()[:90]))
            elif got != want:
                errs.append("%s = %s, модель пар (pos,neg) даёт %s"
                            % (" ".join(args), got, want))
            rc2, out2, _err2 = kernc_belnap(["--bits"] + args)
            parts = out2.split()
            if rc2 != 0 or len(parts) != 4:
                errs.append("--bits %s: rc=%d, вывод %r"
                            % (" ".join(args), rc2, out2.strip()))
                continue
            sym, code, p, n = parts
            p_, n_ = BITS4[want]
            if (sym != want or code != str(p_ | (n_ << 1))
                    or p != str(p_) or n != str(n_)):
                errs.append("--bits %s = %s (код %s, p=%s, n=%s); модель даёт %s "
                            "(код %d, p=%d, n=%d)"
                            % (" ".join(args), sym, code, p, n, want,
                               p_ | (n_ << 1), p_, n_))

    gap_markers = 0
    gaps = card.get("spec_gaps")
    if gaps:
        fixture = write_text(os.path.join(tmpdir, card["id"] + "_gaps.py"), gaps["code"])
        rc, gout, gerr = run([PY, KERN, "--presets", fixture, "--spec-gaps"], timeout=180)
        gtext = gout + gerr
        gap_markers = gtext.count("[SPEC GAP]")
        need = int(gaps.get("min_markers", 1))
        if gap_markers < need:
            errs.append("--spec-gaps: маркеров [SPEC GAP] %d, ожидалось >= %d (rc=%d)"
                        % (gap_markers, need, rc))

    return errs, {"cells": cells, "gap_markers": gap_markers, "mode": mode}



# ---------------------------------------------------------------------------
#  БЛОК 03: ДИАГНОСТИКА ПРОТИВОРЕЧИВЫХ ТЗ (--verify-doc / --explain)
# ---------------------------------------------------------------------------
# ЧЕСТНОЕ РАЗДЕЛЕНИЕ РОЛЕЙ (измерено пилотами, а не предположено):
#   * минимальное (неприводимое) ядро несовместности даёт `--verify-doc`:
#     маркеры `[FAIL] CONFLICT B(1,1)` и `[CONFLICT B(1,1)] Minimal conflicting
#     clauses: [...]`, rc=1; невиновные пункты в ядро не попадают;
#   * `--explain` — ПАСПОРТ функции (CC, число выходов по SMT, строки падения),
#     он НЕ локализует конфликты. Поэтому в карточке он вторичен и проверяется
#     отдельно: напечатанные числа обязаны совпасть с независимым AST-пересчётом.
#
# НЕЗАВИСИМЫЙ ОРАКУЛ (не `expr_smt`!): свой переводчик Python-выражений в z3.
# Аксиомы, которые он проверяет:
#   (a) полный набор пунктов UNSAT;
#   (b) удаление ЛЮБОГО элемента ядра делает набор SAT (неприводимость);
#   (c) удаление любого ШУМОВОГО пункта оставляет UNSAT (шум невиновен);
#   (d) модель ослабленной спецификации физически исполняется `eval` по всем
#       оставшимся предикатам (реальный вектор-свидетель).
# Граница, названная вслух: ядро `--verify-doc` получается жадным удалением —
# оно НЕПРИВОДИМО, но не обязательно минимально по мощности.


def _import_z3():
    try:
        import z3  # noqa: F401  (нужен только оракулу)
        return z3
    except ImportError:
        return None


def _z3_translate(expr_text, vs, z3):
    """СВОЙ переводчик: подмножество линейной целой арифметики и булевых связок."""

    def const_of(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
            return node.value
        return None

    def ev(node):
        c = const_of(node)
        if c is not None:
            return z3.IntVal(c)
        if isinstance(node, ast.Name):
            if node.id not in vs:
                raise ValueError("неизвестная переменная %r" % node.id)
            return vs[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return z3.Not(ev(node.operand))
        if isinstance(node, ast.BinOp):
            a, b = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                ka, kb = const_of(node.left), const_of(node.right)
                if ka is not None:
                    return ka * b
                if kb is not None:
                    return a * kb
                raise ValueError("нелинейное умножение вне фрагмента")
            raise ValueError("оператор %s вне фрагмента" % type(node.op).__name__)
        if isinstance(node, ast.BoolOp):
            parts = [ev(v) for v in node.values]
            return z3.And(*parts) if isinstance(node.op, ast.And) else z3.Or(*parts)
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1:
                raise ValueError("цепочка сравнений вне фрагмента")
            a, b = ev(node.left), ev(node.comparators[0])
            op = node.ops[0]
            table = {ast.Lt: a < b, ast.LtE: a <= b, ast.Gt: a > b, ast.GtE: a >= b,
                     ast.Eq: a == b, ast.NotEq: a != b}
            for k, val in table.items():
                if isinstance(op, k):
                    return val
            raise ValueError("сравнение вне фрагмента")
        raise ValueError("узел %s вне фрагмента" % type(node).__name__)

    return ev(ast.parse(expr_text, mode="eval").body)


def _passport(src):
    """НЕЗАВИСИМЫЙ пересчёт паспорта: CC (Маккейб), число выходов, строки деления.

    Определение метрики то же, что у `--explain` (это опубликованная величина),
    но реализация СВОЯ — поэтому совпадение чисел что-то доказывает.
    """
    tree = ast.parse(src)
    fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)][0]
    cc = 1
    for n in ast.walk(fn):
        if isinstance(n, (ast.If, ast.For, ast.While, ast.IfExp)):
            cc += 1
        elif isinstance(n, ast.BoolOp):
            cc += max(0, len(n.values) - 1)
        elif isinstance(n, ast.Try):
            cc += len(n.handlers)
    rets = sum(1 for n in ast.walk(fn)
               if isinstance(n, ast.Return) and n.value is not None)
    crash = sorted(n.lineno for n in ast.walk(fn)
                   if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Mod)))
    return cc, rets, crash


def check_explain(card, tmpdir):
    """KERN-вердикт = `--verify-doc` (+ вторично `--explain`); оракул = MUS + eval."""
    errs = []
    doc = card["doc"]
    doc_path = write_text(os.path.join(tmpdir, card["id"] + "_doc.json"),
                          json.dumps(doc, ensure_ascii=False, indent=1))
    rc, out, err = run([PY, KERN, "--verify-doc", doc_path], timeout=900)
    text = out + err
    core = []
    m = re.search(r"Minimal conflicting clauses:\s*\[([^\]]*)\]", text)
    if m:
        core = [x.strip() for x in m.group(1).split(",") if x.strip()]
    if rc != 1:
        errs.append("--verify-doc rc=%d, ожидалось 1 (конфликт)" % rc)
    if "[FAIL] CONFLICT B(1,1)" not in text:
        errs.append("нет маркера [FAIL] CONFLICT B(1,1)")
    if not core:
        errs.append("ядро не названо (нет `Minimal conflicting clauses`)")
    noise = set(card.get("noise") or [])
    must = set(card.get("must_include") or [])
    if core and (set(core) & noise):
        errs.append("в ядро попал ШУМ: %s" % sorted(set(core) & noise))
    if core and must and set(core) != must:
        errs.append("ядро %s != ожидаемого %s" % (sorted(core), sorted(must)))

    facts = {"core": core, "noise": sorted(noise)}
    z3 = _import_z3()
    if z3 is None:
        errs.append("z3 недоступен — независимый MUS-оракул невозможен")
        return errs, facts
    by_id = {c["id"]: c["expr"] for c in doc["clauses"]}
    vs = {v: z3.Int(v) for v in doc["vars"]}

    def conj(ids):
        return z3.And(*[_z3_translate(by_id[i], vs, z3) for i in ids]) if ids else z3.BoolVal(True)

    def verdict(ids):
        s = z3.Solver()
        s.add(conj(ids))
        return s.check()

    full = [c["id"] for c in doc["clauses"]]
    if verdict(full) != z3.unsat:
        errs.append("оракул: ПОЛНЫЙ набор не UNSAT — карточка не конфликтна")
    for cid in core:
        trial = [i for i in core if i != cid]
        v = verdict(trial)
        if v != z3.sat:
            errs.append("ядро НЕ неприводимо: без %s набор %s" % (cid, v))
        facts["irreducible_checks"] = facts.get("irreducible_checks", 0) + 1
    for cid in sorted(noise):
        trial = [i for i in full if i != cid]
        if verdict(trial) != z3.unsat:
            errs.append("шум %s влияет на конфликт (без него SAT)" % cid)
    revived = None
    for cid in core:
        trial = [i for i in full if i != cid]
        s = z3.Solver()
        s.add(conj(trial))
        if s.check() != z3.sat:
            continue
        model = s.model()
        val = {v: model.eval(sym, model_completion=True).as_long() for v, sym in vs.items()}
        ok = True
        for i in trial:
            try:
                ok = ok and bool(eval(by_id[i], {"__builtins__": {}}, dict(val)))
            except Exception as exc:
                errs.append("eval предиката %s упал: %s" % (i, exc))
                ok = False
        revived = {"dropped": cid, "model": val, "eval_ok": ok}
        if not ok:
            errs.append("физический eval ослабленной модели дал False: %s" % val)
        break
    if revived is None:
        errs.append("ослабленная спецификация не дала SAT-модели")
    facts["revived"] = revived

    ex = card.get("explain")
    if ex:
        code_path = write_text(os.path.join(tmpdir, card["id"] + "_pp.py"), ex["code"])
        rc2, out2, err2 = run([PY, KERN, "--explain", code_path], timeout=300)
        t2 = out2 + err2
        m_cc = re.search(r"CC = (\d+)", t2)
        m_br = re.search(r"выходы \(SMT\): (\d+)", t2)
        m_cr = re.search(r"условия падения: деление на ноль в строках \[([0-9, ]+)\]", t2)
        own_cc, own_ret, own_crash = _passport(ex["code"])
        want = ex.get("expect") or {}
        if rc2 != 0:
            errs.append("--explain rc=%d (паспорт обязан печататься)" % rc2)
        if not m_cc or int(m_cc.group(1)) != own_cc:
            errs.append("--explain CC=%s, независимый пересчёт %d"
                        % (m_cc.group(1) if m_cc else "нет", own_cc))
        if not m_br or int(m_br.group(1)) != own_ret:
            errs.append("--explain выходов=%s, независимый пересчёт %d"
                        % (m_br.group(1) if m_br else "нет", own_ret))
        got_crash = [int(x) for x in m_cr.group(1).replace(" ", "").split(",") if x] if m_cr else []
        if got_crash != own_crash:
            errs.append("--explain строки падения %s, независимый пересчёт %s"
                        % (got_crash, own_crash))
        if want.get("cc") is not None and own_cc != int(want["cc"]):
            errs.append("CC=%d расходится с карточкой (%s)" % (own_cc, want["cc"]))
        if want.get("returns") is not None and own_ret != int(want["returns"]):
            errs.append("выходов=%d расходится с карточкой (%s)" % (own_ret, want["returns"]))
        if want.get("crash_lines") is not None and own_crash != list(want["crash_lines"]):
            errs.append("строки падения %s расходятся с карточкой (%s)"
                        % (own_crash, want["crash_lines"]))
        facts["passport"] = {"cc": own_cc, "returns": own_ret, "crash": own_crash}
    return errs, facts



# ---------------------------------------------------------------------------
#  БЛОК 05: КОНКОЛИЧЕСКИЙ СИНТЕЗ ВЕКТОРОВ ПОКРЫТИЯ (--concolic)
# ---------------------------------------------------------------------------
# ИЗМЕРЕНО ПИЛОТОМ: `--concolic` печатает ТОЛЬКО сводку
#   `[CONCOLIC] <fn>: concrete runs N, branches covered c/t (dead d, unexplored u)`
# и НЕ печатает сами входные векторы. Поэтому оракул не «забирает векторы у
# движка» (их там нет), а делает независимую физическую работу:
#   1) инструментирует AST карточки СВОИМИ маркерами (`__k_branch` для `if`,
#      `__k_line` для `return`) — дерево НЕ переводится в SMT;
#   2) перебирает объявленный конечный домен и РЕАЛЬНО исполняет функцию;
#   3) собирает множества (строка, взято) и векторы-свидетели для целевых строк;
#   4) сверяет с вердиктом KERN: covered == 2×|if|, dead == 0, unexplored == 0;
#   5) проверяет «игольное ушко»: тривиальный вектор (все параметры 0) НЕ должен
#      проходить целевые глубокие ветви — иначе карточка ничего не доказывает.


def _func_params(tree):
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    if len(fns) != 1:
        raise ValueError("карточка обязана содержать РОВНО одну функцию (найдено %d)" % len(fns))
    return fns[0].name, [a.arg for a in fns[0].args.args if a.arg != "self"]


class _BranchInstrument(ast.NodeTransformer):
    """Свои маркеры ветвей/строк внутри ЦЕЛЕВОЙ функции (исполнение остаётся живым)."""

    def __init__(self, fn_name):
        self.fn_name = fn_name
        self.inside = False
        self.if_lines = []

    def visit_FunctionDef(self, node):
        if node.name != self.fn_name:
            return node
        self.inside = True
        node = self.generic_visit(node)
        self.inside = False
        return node

    def visit_If(self, node):
        node = self.generic_visit(node)
        if not self.inside:
            return node
        ln = getattr(node, "lineno", 0)
        self.if_lines.append(ln)
        node.test = ast.Call(func=ast.Name(id="__k_branch", ctx=ast.Load()),
                             args=[ast.Constant(ln), node.test], keywords=[])
        return node

    def visit_Return(self, node):
        node = self.generic_visit(node)
        if not self.inside:
            return node
        ln = getattr(node, "lineno", 0)
        mark = ast.Expr(value=ast.Call(func=ast.Name(id="__k_line", ctx=ast.Load()),
                                       args=[ast.Constant(ln)], keywords=[]))
        return [mark, node]


def _instrument_and_run(code_src, entry, domain):
    """Физический прогон с инструментацией; возвращает покрытие и свидетелей."""
    tree0 = ast.parse(code_src)
    name, params = _func_params(tree0)
    if name != entry:
        raise ValueError("entry=%r, а функция в карточке %r" % (entry, name))
    missing = [p for p in params if p not in domain]
    if missing:
        raise ValueError("в домене нет параметров: %s" % missing)
    tr = _BranchInstrument(entry)
    tree = tr.visit(ast.parse(code_src))
    ast.fix_missing_locations(tree)
    current = {}
    hits, lines = {}, {}

    def __k_branch(ln, value):
        v = bool(value)
        hits.setdefault((ln, v), dict(current))
        return v

    def __k_line(ln):
        lines.setdefault(ln, dict(current))

    ns = {"__k_branch": __k_branch, "__k_line": __k_line}
    exec(compile(tree, "<instrumented>", "exec"), ns)
    fn = ns[entry]
    vectors = 0
    for vec in itertools.product(*[domain[p] for p in params]):
        current.clear()
        current.update(dict(zip(params, vec)))
        fn(**dict(current))
        vectors += 1
    return {"params": params, "hits": hits, "lines": lines,
            "vectors": vectors, "if_lines": tr.if_lines}


def _trivial_run(code_src, entry, params):
    tree0 = ast.parse(code_src)
    tr = _BranchInstrument(entry)
    tree = tr.visit(ast.parse(code_src))
    ast.fix_missing_locations(tree)
    seen = set()

    def __k_branch(ln, value):
        return bool(value)

    def __k_line(ln):
        seen.add(ln)

    lines = seen
    ns = {"__k_branch": __k_branch, "__k_line": __k_line}
    exec(compile(tree, "<trivial>", "exec"), ns)
    ns[entry](**{p: 0 for p in params})
    return lines


def check_concolic(card, tmpdir):
    """KERN-вердикт = `--concolic`; оракул = физическое покрытие и свидетели."""
    errs = []
    code = card["code"]
    entry = card["entry"]
    src_path = write_text(os.path.join(tmpdir, card["id"] + ".py"), code)
    rc, out, err = run([PY, KERN, "--concolic", src_path], timeout=1800)
    text = out + err
    pat = (r"\[CONCOLIC\] " + re.escape(entry) +
           r": concrete runs (\d+), branches covered (\d+)/(\d+) \(dead (\d+), unexplored (\d+)\)")
    m = re.search(pat, text)
    if rc != 0:
        errs.append("--concolic rc=%d: %s" % (rc, text.strip().splitlines()[-1][:90] if text.strip() else "пусто"))
    if not m:
        errs.append("нет строки [CONCOLIC] для %s" % entry)
    info = _instrument_and_run(code, entry, card["domain"])
    reach = info["hits"]
    expected = int(card.get("expect_covered") or 2 * len(info["if_lines"]))
    if len(reach) != expected:
        errs.append("оракул покрыл %d ветвей, ожидалось %d (домен карточки неполон)"
                    % (len(reach), expected))
    if m:
        runs, cov, tot, dead, unexpl = (int(x) for x in m.groups())
        if cov != expected:
            errs.append("KERN covered=%d, независимо покрыто %d" % (cov, expected))
        if dead != 0:
            errs.append("KERN dead=%d (ожидалось 0)" % dead)
        if unexpl != 0:
            errs.append("KERN unexplored=%d (ожидалось 0)" % unexpl)
        if tot != cov + dead + unexpl:
            errs.append("счёт ветвей KERN не сходится: %d != %d+%d+%d" % (tot, cov, dead, unexpl))
    else:
        runs = -1
    targets = list(card.get("targets") or [])
    if not targets:
        errs.append("карточка без `targets` (нечего доказывать физически)")
    witnesses = {}
    for t in targets:
        if t in info["lines"]:
            witnesses[t] = info["lines"][t]
        else:
            errs.append("целевая строка %d НЕ исполнена ни на одном векторе домена" % t)
    trivial = _trivial_run(code, entry, info["params"])
    triv_hit = [t for t in targets if t in trivial]
    if targets and len(triv_hit) == len(targets):
        errs.append("не «игольное ушко»: тривиальный вход (все нули) уже проходит все targets")
    return errs, {"runs": runs, "covered": len(reach), "expected": expected,
                  "targets": len(targets), "targets_hit": len(witnesses),
                  "vectors": info["vectors"], "witnesses": witnesses,
                  "trivial_targets": len(triv_hit)}



# ---------------------------------------------------------------------------
#  БЛОК 06: ЦЕЛОСТНОСТЬ ОБРАЗОВ .kimg И ПОДПИСИ Ed25519
# ---------------------------------------------------------------------------
# ИЗМЕРЕНО ПИЛОТОМ (без домыслов):
#   * `kernc check-integrity <img>` даёт rc=0 на целом образе и rc=2 на порче;
#     маркеры: `[OK] Целостность: заголовок + Merkle-корень совпали`,
#     `[!] Образ НЕВАЛИДЕН: BadMagic|UnsupportedVersion|BadHeaderSize`,
#     `[!] ОБЪЕКТ <i> ПОВРЕЖДЁН ... PayloadTampered`, `[!] Образ слишком мал`;
#   * `kernc attest sign <img> -k <seed32> -o <cert>` подписывает ЛЮБЫМ ключом,
#     а `attest verify` проверяет ВШИТЫМ ключом владельца и **всегда** выходит
#     с rc=0: вердикт только текстовый (`подпись=НЕВЕРНА|ok`, `привязка=ok|НЕ СОВПАЛА`).
#     Это граница CLI, а не наша: rc не является сигналом для attest.
#
# НЕЗАВИСИМЫЙ ОРАКУЛ:
#   * свой разбор 128-байтного заголовка и 96-байтных записей таблицы;
#   * BLAKE3 каждого объекта (`blake3`) против дайджеста в таблице;
#   * Ed25519 через `openssl pkeyutl -verify -rawin` (наш ключ и ключ владельца);
#   * SHA-256 образа против `contract_digest` сертификата (привязка);
#   * точная локализация мутации (какой объект/поле испорчено).

KIMG_OWNER_PUB = os.path.join(ROOT, "docs", "keys", "kern-owner.pub")
KIMG_MAGIC = b"KIMG\r\n\x1a\n"
CERT_MAGIC = b"KATT"


def _blake3(data):
    try:
        import blake3
    except ImportError:
        return None
    return blake3.blake3(data).digest()


def _kimg_header(blob):
    """СВОЙ разбор 128-байтного заголовка (структура из kimg_reader.zig)."""
    if len(blob) < 128:
        return {"too_small": len(blob)}
    (vmaj, vmin, hsize, flags, algo, block) = struct.unpack_from("<HHIIIQ", blob, 8)
    (t_off, t_size, count, p_off) = struct.unpack_from("<QQQQ", blob, 32)
    return {"magic_ok": blob[:8] == KIMG_MAGIC, "version": (vmaj, vmin),
            "header_size": hsize, "flags": flags, "hash_algo": algo,
            "block_size": block, "table_off": t_off, "table_size": t_size,
            "object_count": count, "payload_off": p_off,
            "root_digest": blob[64:96], "size": len(blob)}


def _kimg_objects(blob, h):
    """СВОЙ разбор таблицы объектов: 96 байт на запись."""
    out = []
    for i in range(int(h["object_count"])):
        base = int(h["table_off"]) + i * 96
        if base + 96 > len(blob):
            break
        digest = blob[base:base + 32]
        off, usize, csize = struct.unpack_from("<QQQ", blob, base + 32)
        # ИЗМЕРЕНО: `payload_offset` в записи ОТНОСИТЕЛЕН `data_payload_offset`
        # (224 при payload_off=608 даёт 832 — ровно место первого объекта).
        off = int(h["payload_off"]) + off
        codec = blob[base + 62]
        out.append({"index": i, "digest": digest, "off": off, "usize": usize,
                    "csize": csize, "codec": codec})
    return out


def _ed25519_verify(pub_pem, payload, sig):
    """Независимая проверка Ed25519 через OpenSSL (0 = подпись верна)."""
    with tempfile.TemporaryDirectory(prefix="ed25519_") as td:
        pl = os.path.join(td, "p.bin"); sg = os.path.join(td, "s.bin")
        with open(pl, "wb") as fh:
            fh.write(payload)
        with open(sg, "wb") as fh:
            fh.write(sig)
        rc, _out, err = run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", pub_pem,
                             "-rawin", "-in", pl, "-sigfile", sg], timeout=60)
        return rc == 0, err.strip()[:120]


def _openssl_available():
    rc, _out, _err = run(["openssl", "version"], timeout=30)
    return rc == 0


def _sign_image(img_path, seed32, cert_path):
    seed = os.path.join(os.path.dirname(cert_path), "seed32.bin")
    with open(seed, "wb") as fh:
        fh.write(seed32)
    return run([KERNC, "attest", "sign", img_path, "-k", seed, "-o", cert_path], timeout=300)


def _cert_fields(raw):
    return {"magic_ok": raw[:4] == CERT_MAGIC, "version": raw[4] if len(raw) > 4 else None,
            "verdict": raw[5] if len(raw) > 5 else None,
            "contract_digest": raw[8:40], "merkle_root": raw[40:72],
            "signature": raw[72:136], "payload": raw[8:40] + raw[40:72] + raw[5:6],
            "size": len(raw)}


def check_kimg(card, tmpdir):
    """KERN-вердикт = check-integrity / attest verify; оракул = байты + BLAKE3 + Ed25519."""
    errs = []
    scenario = card["scenario"]
    base = card.get("base", "toy")
    src = os.path.join(ROOT, "toy.kimg" if base == "toy" else "release.kimg")
    img = os.path.join(tmpdir, "image.kimg")
    with open(src, "rb") as fh:
        pristine = fh.read()
    blob = bytearray(pristine)
    details = {"scenario": scenario, "base": base}

    if scenario == "payload_flip":
        blob[-1] ^= 1
    elif scenario == "magic_corrupt":
        blob[0] ^= 1
    elif scenario == "version_corrupt":
        struct.pack_into("<H", blob, 8, 2)
    elif scenario == "hdrsize_corrupt":
        struct.pack_into("<I", blob, 12, 64)
    elif scenario == "truncated":
        del blob[-100:]
    elif scenario == "empty":
        del blob[:]
    elif scenario not in ("pristine", "sig_flip", "foreign_key", "stale_binding"):
        errs.append("неизвестный сценарий %r" % scenario)
    with open(img, "wb") as fh:
        fh.write(bytes(blob))

    expect = card.get("expect") or {}
    if scenario in ("sig_flip", "foreign_key", "stale_binding"):
        seed = bytes(range(32))
        cert_ours = os.path.join(tmpdir, "ours.cert")
        rc_s, out_s, _e = _sign_image(img, seed, cert_ours)
        if rc_s != 0 or "ОБРАЗ АТТЕСТОВАН" not in (out_s + _e):
            errs.append("attest sign rc=%d: %s" % (rc_s, (out_s + _e).strip()[:120]))
        if scenario == "sig_flip":
            raw = bytearray(open(cert_ours, "rb").read())
            raw[80] ^= 1
            with open(cert_ours, "wb") as fh:
                fh.write(bytes(raw))
            cert_used = cert_ours
        elif scenario == "foreign_key":
            cert_used = cert_ours
        else:
            cert_used = os.path.join(tmpdir, "owner.cert")
            with open(os.path.join(ROOT, "attestation.cert"), "rb") as fh:
                with open(cert_used, "wb") as out:
                    out.write(fh.read())
        rc, out, err = run([KERNC, "attest", "verify", img, cert_used], timeout=300)
        text = out + err
        for marker in expect.get("attest_markers") or []:
            if marker not in text:
                errs.append("attest verify: нет маркера %r (вывод: %s)"
                            % (marker, " ".join(text.split())[:140]))
        details["attest_rc"] = rc
        raw = open(cert_used, "rb").read()
        cf = _cert_fields(raw)
        details["cert"] = {"magic_ok": cf["magic_ok"], "size": cf["size"],
                           "binding_sha256_ok": hashlib.sha256(bytes(blob)).digest() == cf["contract_digest"]}
        if not cf["magic_ok"] or cf["size"] != 136:
            errs.append("сертификат не 136 байт или без магии KATT")
        if not _openssl_available():
            errs.append("openssl недоступен — независимая Ed25519-проверка невозможна")
        else:
            own = os.path.join(tmpdir, "ours.pub")
            der = bytes.fromhex("302e020100300506032b657004220420") + seed
            dpath = os.path.join(tmpdir, "ours.der")
            with open(dpath, "wb") as fh:
                fh.write(der)
            rc_d, _o, e_d = run(["openssl", "pkey", "-inform", "DER", "-in", dpath,
                                 "-pubout", "-out", own], timeout=60)
            if rc_d != 0:
                errs.append("не удалось вывести наш публичный ключ: %s" % e_d.strip()[:100])
            else:
                ours_ok, _ = _ed25519_verify(own, cf["payload"], cf["signature"])
                owner_ok, _ = _ed25519_verify(KIMG_OWNER_PUB, cf["payload"], cf["signature"])
                details["sig_valid_ours"] = ours_ok
                details["sig_valid_owner"] = owner_ok
                want = card.get("oracle") or {}
                if want.get("sig_valid_ours") is not None and ours_ok != bool(want["sig_valid_ours"]):
                    errs.append("оракул: подпись нашим ключом = %s, ожидалось %s"
                                % (ours_ok, want["sig_valid_ours"]))
                if want.get("sig_valid_owner") is not None and owner_ok != bool(want["sig_valid_owner"]):
                    errs.append("оракул: подпись ключом владельца = %s, ожидалось %s"
                                % (owner_ok, want["sig_valid_owner"]))
        return errs, details

    rc, out, err = run([KERNC, "check-integrity", img], timeout=600)
    text = out + err
    if rc != int(expect.get("integrity_rc", 0)):
        errs.append("check-integrity rc=%d, ожидалось %s" % (rc, expect.get("integrity_rc")))
    for marker in expect.get("markers") or []:
        if marker not in text:
            errs.append("check-integrity: нет маркера %r" % marker)
    details["integrity_rc"] = rc
    h = _kimg_header(bytes(blob))
    details["header"] = {k: h[k] for k in ("magic_ok", "version", "header_size",
                                          "object_count", "size") if k in h}
    if scenario == "pristine":
        if not h.get("magic_ok") or h.get("header_size") != 128 or h.get("version") != (1, 3):
            errs.append("оракул: заголовок невалиден: %s" % details["header"])
        objs = _kimg_objects(bytes(blob), h)
        bad = 0
        for ob in objs:
            if ob["codec"] != 0:
                continue
            data = bytes(blob)[ob["off"]:ob["off"] + ob["csize"]]
            got = _blake3(data)
            if got is not None and got != ob["digest"]:
                bad += 1
        details["objects"] = len(objs)
        details["digest_mismatches"] = bad
        if _blake3(b"") is None:
            errs.append("blake3 недоступен — независимая проверка объектов невозможна")
        elif bad != 0:
            errs.append("оракул: %d объектов с неверным BLAKE3 на ЦЕЛОМ образе" % bad)
    elif scenario == "payload_flip":
        objs = _kimg_objects(bytes(blob), h)
        bad = []
        for ob in objs:
            if ob["codec"] != 0:
                continue
            data = bytes(blob)[ob["off"]:ob["off"] + ob["csize"]]
            got = _blake3(data)
            if got is not None and got != ob["digest"]:
                bad.append(ob["index"])
        details["tampered_objects"] = bad
        if len(bad) != 1:
            errs.append("оракул: испорчено объектов %d, ожидался ровно 1" % len(bad))
        m = re.search(r"ОБЪЕКТ (\d+) ПОВРЕЖДЁН", text)
        if not m:
            errs.append("KERN не назвал номер испорченного объекта")
        elif bad and int(m.group(1)) != bad[0]:
            errs.append("KERN назвал объект %s, оракул — %s" % (m.group(1), bad[0]))
    elif scenario == "magic_corrupt":
        if h.get("magic_ok") is not False:
            errs.append("оракул: магия осталась валидной")
    elif scenario == "version_corrupt":
        if h.get("version") == (1, 3):
            errs.append("оракул: версия не изменилась")
    elif scenario == "hdrsize_corrupt":
        if h.get("header_size") == 128:
            errs.append("оракул: header_size не изменился")
    elif scenario == "truncated":
        if "too_small" in h:
            errs.append("оракул: файл всё ещё >= 128 байт")
        else:
            t_end = h["table_off"] + h["table_size"]
            objs = _kimg_objects(bytes(blob), h)
            obj_oob = [ob["index"] for ob in objs
                       if ob["off"] + ob["csize"] > len(blob)]
            if t_end <= len(blob) and h["payload_off"] <= len(blob) and not obj_oob:
                errs.append("оракул: границы таблицы/payload/объектов не нарушены")
            details["objects_oob"] = obj_oob
    elif scenario == "empty":
        if len(blob) != 0:
            errs.append("оракул: файл не пуст")
    return errs, details



# ---------------------------------------------------------------------------
#  БЛОК 07: ВЕРИФИЦИРУЕМАЯ НАГРАДА RLVR (`--rlvr-reward`)
# ---------------------------------------------------------------------------
# ИЗМЕРЕНО ПИЛОТОМ (точная шкала, без домыслов):
#   +1.0 `[VERIFIED REWARD, Belnap T, e=1]` — доказано, trusted: 0 | holes: 0;
#   -1.0 `[REFUTED, Belnap F]` — есть контрпример (он печатается);
#   -2.0 `[REWARD HACKING PENALTY, Belnap F]` — чит (`sys.exit` внутри функции);
#    0.0 `[ABSTAIN, Belnap N]` — нет аннотаций ИЛИ тело вне замкнутого фрагмента
#         (ИЗМЕРЕНО: `x * 2` и `part * 100 // total` дают ABSTAIN, а `x + x` — +1.0);
#   синтаксически битый файл — фатальный SyntaxError (rc != 0), награды НЕТ.
# `--rlvr-reward` ВСЕГДА выходит с rc=0, кроме этого случая: сигнал — строка R=.
#
# НЕЗАВИСИМЫЙ ОРАКУЛ: сам читает `@kern:requires/ensures`, сам исполняет кандидата
# в Python и проверяет, ЧЕМ награда заслужена: контрпример действительно нарушает
# постусловие на входе, удовлетворяющем предусловию; «доказанный» кандидат держит
# постусловие на всей сетке домена; чит содержит `sys.exit` внутри функции;
# битый файл не парсится. Плюс монотонность и (по флагу) детерминизм.

RLVR_RE = re.compile(r"\[REWARD\] R=([-+]?\d+(?:\.\d+)?)")


def _annot(code, name):
    m = re.search(r"@kern:" + name + r"\s+(.+)", code)
    return m.group(1).strip() if m else None


def _load_candidate(code):
    tree = ast.parse(code)
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if len(fns) != 1:
        raise ValueError("кандидат обязан содержать ровно одну функцию")
    ns = {}
    exec(compile(tree, "<candidate>", "exec"), ns)
    return fns[0].name, [a.arg for a in fns[0].args.args], ns


def _check_role(cand, code, errs):
    """Физическая проверка ЗАСЛУЖЕННОСТИ награды (независимо от KERN)."""
    role = cand.get("role", "proven")
    if role == "syntax":
        try:
            ast.parse(code)
        except SyntaxError:
            return {"parsed": False}
        errs.append("оракул: синтаксически битый кандидат ВДРУГ разобрался")
        return {"parsed": True}
    name, params, ns = _load_candidate(code)
    fn = ns[name]
    req = _annot(code, "requires")
    ens = _annot(code, "ensures")
    if role == "cheat":
        bad = [n.lineno for n in ast.walk(ast.parse(code))
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr in ("exit", "_exit")]
        if not bad:
            errs.append("оракул: в «чите» нет sys.exit внутри кода")
        return {"cheat_lines": bad}
    if role == "refuted":
        witness = cand.get("witness") or {}
        if req and not eval(req, {"__builtins__": {}}, dict(witness)):
            errs.append("оракул: свидетель %s НЕ удовлетворяет requires (%s)" % (witness, req))
        got = fn(**witness)
        if not ens:
            errs.append("оракул: у кандидата нет ensures — нарушать нечего")
        elif eval(ens, {"__builtins__": {}}, dict(witness, result=got)):
            errs.append("оракул: на свидетеле %s постусловие ВЫПОЛНЕНО (result=%s) — "
                        "наказание не заслужено" % (witness, got))
        return {"witness": witness, "result": got}
    if role == "crash":
        witness = cand.get("witness") or {}
        try:
            got = fn(**witness)
        except ZeroDivisionError:
            return {"witness": witness, "raised": "ZeroDivisionError"}
        except Exception as exc:
            return {"witness": witness, "raised": type(exc).__name__}
        errs.append("оракул: кандидат НЕ упал на %s (result=%s)" % (witness, got))
        return {"witness": witness, "result": got}
    if role == "weak":
        body = ast.parse(code).body[-1].body
        is_const = (len(body) == 1 and isinstance(body[0], ast.Return)
                    and isinstance(body[0].value, ast.Constant))
        if not is_const:
            errs.append("оракул: «слабое» тело — не одна константа")
        val = fn(**(cand.get("witness") or {p: 0 for p in params}))
        ok = bool(ens) and eval(ens, {"__builtins__": {}}, dict({p: 0 for p in params}, result=val))
        return {"constant": is_const, "ensures_holds": ok}
    # role == "proven": постусловие обязано держаться на ВСЕЙ сетке домена
    domain = cand.get("domain") or {}
    checked = failed = 0
    for vec in itertools.product(*[domain[p] for p in params]):
        env = dict(zip(params, vec))
        if req and not eval(req, {"__builtins__": {}}, dict(env)):
            continue
        checked += 1
        got = fn(**env)
        if ens and not eval(ens, {"__builtins__": {}}, dict(env, result=got)):
            failed += 1
    if checked == 0:
        errs.append("оракул: домен не дал ни одного входа, удовлетворяющего requires")
    if failed:
        errs.append("оракул: «доказанный» кандидат нарушает ensures на %d из %d входов"
                    % (failed, checked))
    return {"checked": checked, "failed": failed}


def check_rlvr(card, tmpdir):
    errs = []
    rewards = {}
    facts = {"candidates": {}}
    for cand in card["candidates"]:
        name = cand["name"]
        code = cand["code"]
        path = write_text(os.path.join(tmpdir, card["id"] + "_" + name + ".py"), code)
        rc, out, err = run([PY, KERN, "--rlvr-reward", path], timeout=1200)
        text = out + err
        rew = None
        m = RLVR_RE.search(text)
        if m:
            rew = float(m.group(1))
        rewards[name] = rew
        exp = cand.get("expect_reward")
        if exp is not None:
            if rew is None:
                errs.append("%s: награда не напечатана (rc=%d)" % (name, rc))
            elif abs(rew - float(exp)) > 1e-9:
                errs.append("%s: R=%s, ожидалось %s" % (name, rew, exp))
        if cand.get("expect_no_reward") and rew is not None:
            errs.append("%s: награда %s напечатана, хотя ожидался отказ без награды" % (name, rew))
        if cand.get("expect_marker") and cand["expect_marker"] not in text:
            errs.append("%s: нет маркера %r" % (name, cand["expect_marker"]))
        if cand.get("expect_rc") is not None and rc != int(cand["expect_rc"]):
            errs.append("%s: rc=%d, ожидалось %s" % (name, rc, cand["expect_rc"]))
        try:
            facts["candidates"][name] = _check_role(cand, code, errs)
        except Exception as exc:
            errs.append("%s: оракул не смог проверить кандидата: %s: %s"
                        % (name, type(exc).__name__, exc))
        if card.get("determinism"):
            rc2, out2, err2 = run([PY, KERN, "--rlvr-reward", path], timeout=1200)
            m2 = RLVR_RE.search(out2 + err2)
            rew2 = float(m2.group(1)) if m2 else None
            if rew2 != rew:
                errs.append("%s: сигнал НЕ детерминирован: %s != %s" % (name, rew, rew2))
    order = card.get("order") or []
    for a, b in zip(order, order[1:]):
        ra, rb = rewards.get(a), rewards.get(b)
        if ra is None or rb is None or not (ra > rb):
            errs.append("монотонность нарушена: reward(%s)=%s не > reward(%s)=%s"
                        % (a, ra, b, rb))
    facts["rewards"] = rewards
    return errs, facts


def run_card(card):
    with tempfile.TemporaryDirectory(prefix="full_spectrum_") as tmpdir:
        if card["kind"] == "heal":
            errs, facts = check_heal(card, tmpdir)
        elif card["kind"] == "state-inv":
            errs, facts = check_state_inv(card, tmpdir)
        elif card["kind"] == "explain":
            errs, facts = check_explain(card, tmpdir)
            core = facts.get("core") or []
            rev = facts.get("revived") or {}
            facts.update({
                "kern_note_en": "`--verify-doc`: core of %s clause(s) localized" % len(core),
                "kern_note_ru": "`--verify-doc`: ядро из %s пункт(ов) локализовано" % len(core),
                "oracle_note_en": "UNSAT set · every core element necessary · noise innocent · "
                                  "revived model eval %s" % ("OK" if rev.get("eval_ok") else "FAIL"),
                "oracle_note_ru": "набор UNSAT · каждый элемент ядра необходим · шум невиновен · "
                                  "ослабленная модель eval %s" % ("OK" if rev.get("eval_ok") else "FAIL"),
            })
        elif card["kind"] == "concolic":
            errs, facts = check_concolic(card, tmpdir)
            facts.update({
                "kern_note_en": "`--concolic`: %s run(s), %s/%s branches, dead 0, unexplored 0"
                                % (facts.get("runs"), facts.get("covered"), facts.get("expected")),
                "kern_note_ru": "`--concolic`: %s запуск(ов), %s/%s ветвей, dead 0, unexplored 0"
                                % (facts.get("runs"), facts.get("covered"), facts.get("expected")),
                "oracle_note_en": "AST-instrumented: %s branch(es), %s/%s target(s) hit by real "
                                  "witness vectors, %s vector(s)"
                                  % (facts.get("covered"), facts.get("targets_hit"),
                                     facts.get("targets"), facts.get("vectors")),
                "oracle_note_ru": "AST-инструментация: %s ветвей, %s/%s целей пробито реальными "
                                  "векторами, %s вектор(ов)"
                                  % (facts.get("covered"), facts.get("targets_hit"),
                                     facts.get("targets"), facts.get("vectors")),
            })
        elif card["kind"] == "kimg":
            errs, facts = check_kimg(card, tmpdir)
            facts.update({
                "kern_note_en": "`%s`: rc=%s, markers matched" % (facts.get("scenario"), facts.get("integrity_rc", facts.get("attest_rc"))),
                "kern_note_ru": "`%s`: rc=%s, маркеры совпали" % (facts.get("scenario"), facts.get("integrity_rc", facts.get("attest_rc"))),
                "oracle_note_en": "own header/table parse + BLAKE3 per object + Ed25519 via OpenSSL",
                "oracle_note_ru": "свой разбор заголовка/таблицы + BLAKE3 по объектам + Ed25519 через OpenSSL",
            })
        elif card["kind"] == "rlvr":
            errs, facts = check_rlvr(card, tmpdir)
            rw = facts.get("rewards") or {}
            facts.update({
                "kern_note_en": "rewards " + ", ".join("%s=%s" % (k, v) for k, v in rw.items()),
                "kern_note_ru": "награды " + ", ".join("%s=%s" % (k, v) for k, v in rw.items()),
                "oracle_note_en": "independent exec: witness violates ensures · proven holds on domain · monotone",
                "oracle_note_ru": "независимое исполнение: свидетель нарушает ensures · proven держится на домене · монотонно",
            })
        elif card["kind"] == "belnap":
            errs, facts = check_belnap(card, tmpdir)
            gaps = facts.get("gap_markers") or 0
            gap_en = (" · spec-gap markers: %d" % gaps) if gaps else ""
            facts.update({
                "kern_note_en": "%s native cell(s) via kernc belnap (Zig core)"
                                % facts.get("cells"),
                "kern_note_ru": "%s нативных клеток через kernc belnap (ядро Zig)"
                                % facts.get("cells"),
                "oracle_note_en": "bit-pair oracle agrees on %s cell(s)%s"
                                  % (facts.get("cells"), gap_en),
                "oracle_note_ru": "оракул пар битов сошёлся на %s клетках%s"
                                  % (facts.get("cells"), gap_en),
            })
        else:
            errs, facts = ["неизвестный kind=%r" % card.get("kind")], {}
    return {
        "id": card["id"],
        "kind": card["kind"],
        "block": card.get("block", "-"),
        "sphere": card.get("sphere", "-"),
        "trick": card.get("trick", "-"),
        "sphere_en": card.get("sphere_en", card.get("sphere", "-")),
        "trick_en": card.get("trick_en", card.get("trick", "-")),
        "failed": bool(errs),
        "errors": errs,
        "facts": facts,
    }


def load_cards(paths):
    cards = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            blob = json.load(fh)
        if isinstance(blob, dict) and "cards" in blob:
            blob = blob["cards"]
        if not isinstance(blob, list):
            raise SystemExit("[!] %s: ожидался список карточек" % path)
        for card in blob:
            for key in ("id", "kind", "sphere", "trick"):
                if key not in card:
                    raise SystemExit("[!] %s: карточка без поля %r" % (path, key))
            if card["kind"] in ("heal", "state-inv", "concolic") and "code" not in card:
                raise SystemExit("[!] %s: карточке %s нужен `code`" % (path, card["id"]))
            if card["kind"] == "explain" and "doc" not in card:
                raise SystemExit("[!] %s: explain-карточке %s нужен `doc`" % (path, card["id"]))
            if card["kind"] == "concolic" and not card.get("domain"):
                raise SystemExit("[!] %s: concolic-карточке %s нужен `domain`" % (path, card["id"]))
            if card["kind"] == "kimg" and not card.get("scenario"):
                raise SystemExit("[!] %s: kimg-карточке %s нужен `scenario`" % (path, card["id"]))
            if card["kind"] == "rlvr" and not card.get("candidates"):
                raise SystemExit("[!] %s: rlvr-карточке %s нужны `candidates`" % (path, card["id"]))
            if card["kind"] == "belnap" and not (card.get("calls") or card.get("mode") == "table"):
                raise SystemExit("[!] %s: belnap-карточке %s нужны `calls` или `mode: table`"
                                 % (path, card["id"]))
            cards.append(card)
    return cards


def _cell(v):
    """Markdown-ячейка: `|` внутри текста рвёт таблицу."""
    return str(v).replace("|", "\\|").replace("\n", " ")


def _rows(results, lang="en"):
    rows = []
    for i, r in enumerate(results, 1):
        f = r["facts"]
        if r["kind"] == "heal":
            if lang == "ru":
                kern = "T (1,0), краш-путей %s → %s" % (f.get("crash_before"), f.get("crash_after"))
                oracle = ("python3 rc %s → %s · гардов %s · обычные входы точны"
                          % (f.get("rc_before"), f.get("rc_after"), f.get("guards")))
            else:
                kern = "T (1,0), %s crash-paths before → %s after" % (f.get("crash_before"), f.get("crash_after"))
                oracle = "python3 rc %s → %s · %s guard(s) · normal inputs exact" % (
                    f.get("rc_before"), f.get("rc_after"), f.get("guards"))
        elif r["kind"] in ("belnap", "explain", "concolic", "kimg", "rlvr"):
            kern = f.get("kern_note_" + lang) or "-"
            oracle = f.get("oracle_note_" + lang) or "-"
        else:
            kern = f.get("kern_note_" + lang) or "[FAIL] naive + [PASS] guarded, 0 UNKNOWN"
            oracle = f.get("oracle_note_" + lang) or (
                "%s concrete violation(s) found · %s safe sequences, %s violation(s)"
                % (f.get("unsafe_violations"), f.get("safe_checks"), f.get("safe_violations")))
        rows.append((i, r, kern, oracle))
    return rows


def render_en(results, corpus_names):
    rows = _rows(results, "en")
    L = [
        "# Full Spectrum 70 — window 1: blocks 01-07 (%d of %d confirmed)" % (len(results), len(results)),
        "",
        "Every mechanism below had been shown on a single example each; here each one is",
        "run over a corpus of business cards. Every card is checked **twice**: the KERN",
        "verdict (native Zig / symbolic) and an **independent oracle** that is not a copy",
        "of the engine's tables (bit-pair semantics for B4, CPython execution for code).",
        "",
        "**Law of integrity:** `confirmed == total`. If a single card is not confirmed, the",
        "runner exits with `rc=1` and writes no showcase at all.",
        "",
        "Corpora: `%s`." % "`, `".join(corpus_names),
        "",
        "## Cards",
        "",
        "| # | block | card | sphere | business subject | KERN | physical oracle | status |",
        "|---|-------|------|--------|------------------|------|-----------------|--------|",
    ]
    for i, r, kern, oracle in rows:
        L.append("| %d | %s | `%s` | %s | %s | %s | %s | %s |" % (
            i, r["block"], r["id"], _cell(r["sphere_en"]), _cell(r["trick_en"]),
            _cell(kern), _cell(oracle), "OK" if not r["failed"] else "FAIL"))
    L += [
        "",
        "## What block 01 proves (native B4, `kernc belnap`)",
        "",
        "`kernc belnap <op> <a> [b]` prints the result of a **native** function of the Zig",
        "core (`src/core/eq2.zig`: `joinK`, `meetK`, `andT`, `orT`, `notB`). There is no",
        "truth table in the wrapper: the CLI layer only maps an operation name to a call,",
        "so \"CLI drifted from the engine\" is impossible by construction. `--bits` prints",
        "`<symbol> <code> <pos> <neg>` with `code = pos | (neg << 1)`.",
        "",
        "The oracle does **not** copy those tables: it recomputes B4 from evidence pairs",
        "`(pos, neg) in {0,1}^2` — `N=(0,0)`, `T=(1,0)`, `F=(0,1)`, `B=(1,1)` — combining",
        "knowledge component-wise (`join_k` = OR/OR, `meet_k` = AND/AND) and truth",
        "monotonically (`and_t` = AND/OR, `or_t` = OR/AND), with `not = (neg, pos)`.",
        "Every cell of every row is compared, including the full 68-row `--table` cascade.",
        "",
        "## What block 02 proves (auto-repair without an LLM, `--heal`)",
        "",
        "Each card walks the **whole arc**, not a recipe print:",
        "",
        "1. BEFORE: the file really crashes in `python3` (`ZeroDivisionError`) and",
        "   `--xray` reports the crash path;",
        "2. REPAIR: `kern_contracts.py --heal` synthesises guards by itself, inserts them",
        "   into the source and prints `T (1,0)` with `после патча: 0`;",
        "3. AFTER: the healed file runs in `python3` without a crash, `--xray` reports zero",
        "   crash paths, the contract re-check says `нарушено 0 / НЕ РЕШЕНО 0`, and **normal",
        "   inputs still return the mathematically correct value** (the guard did not turn",
        "   the function into a constant zero).",
        "",
        "The backup `<file>.bak` is checked to hold the original, unpatched source.",
        "",
        "## What block 03 proves (contradictory specs, `--verify-doc`)",
        "",
        "Each card is a clause document whose conjunction is **unsatisfiable**. KERN prints",
        "`[FAIL] CONFLICT B(1,1)` and `[CONFLICT B(1,1)] Minimal conflicting clauses: [...]`",
        "and exits with `rc=1`. The core is obtained by greedy deletion, so it is",
        "**irreducible, not necessarily minimum-cardinality** — that is stated, not hidden.",
        "",
        "The oracle recomputes the mathematics from scratch (its own Python→z3 translator,",
        "not `expr_smt`): the full set is UNSAT, removing **any** core element makes it SAT,",
        "removing any **noise** clause leaves it UNSAT, and the model of the relaxed",
        "specification is physically evaluated against every remaining predicate (`eval`),",
        "so the revived specification has a real witness vector.",
        "",
        "`--explain` is exercised as a **secondary, passport-only** surface: its printed",
        "cyclomatic complexity, SMT branch count and division-crash lines must equal an",
        "independent AST recount. It does **not** localize conflicts (measured).",
        "",
        "## What block 04 proves (state machines over time, `--state-inv`)",
        "",
        "Each card is a multi-step business automaton where every single method looks",
        "harmless, but a **chain of transitions** breaks the state invariant:",
        "",
        "1. KERN reports `[FAIL] <naive>: STATE INVARIANT VIOLATED` together with a concrete",
        "   counterexample, and `[PASS] <guarded>: PROVEN` for the protected transition; no",
        "   `[UNKNOWN]` is accepted as a proof;",
        "2. the physical oracle replays real call sequences on a real object, counts the",
        "   concrete violations it observes, and exhaustively checks that the guarded",
        "   transition never violates the invariant on the grid of sequences.",
        "",
        "Card 10 adds a **mutation check**: drop the guards of the reference escrow and the",
        "KERN proof collapses to `[FAIL]`, while the physical oracle shows the balance going",
        "negative. A proof that survives removing the guard would be worthless.",
        "",
        "## What block 05 proves (concolic branch coverage, `--concolic`)",
        "",
        "Narrow nested branches (`x == magic`, four-level ladders, anti-fraud rules) are",
        "synthesised concretely: KERN prints `[CONCOLIC] <fn>: concrete runs N, branches",
        "covered c/t (dead 0, unexplored 0)`. Measured boundary: **the engine does not print",
        "the input vectors**, only the summary counts.",
        "",
        "The oracle therefore does the physical work itself: it instruments the card's AST",
        "with its own markers, executes the real function over the declared finite domain,",
        "collects the `(line, taken)` set and a witness vector for every target line, and",
        "requires `covered == 2 × |if|`, `dead == 0`, `unexplored == 0`. A needle property is",
        "enforced: the trivial all-zero input must **not** already pass every target.",
        "",
        "## What block 06 proves (.kimg integrity and Ed25519 attestation)",
        "",
        "`kernc check-integrity` gives `rc=0` on an intact image and `rc=2` on damage,",
        "naming the exact failure: `BadMagic`, `UnsupportedVersion`, `BadHeaderSize`,",
        "`ОБЪЕКТ <i> ПОВРЕЖДЁН ... PayloadTampered`, `Образ слишком мал`.",
        "`kernc attest sign` signs with ANY 32-byte seed, while `attest verify` checks the",
        "**owner key baked into the binary** — and always exits with `rc=0`: the verdict is",
        "textual (`подпись=НЕВЕРНА|ok`, `привязка=ok|НЕ СОВПАЛА`). That gap is measured and",
        "named, not papered over.",
        "",
        "The oracle parses the 128-byte header and the 96-byte object table itself,",
        "recomputes **BLAKE3 of every object**, verifies the certificate signature with",
        "**OpenSSL Ed25519** under both our key and the owner key, and compares",
        "`SHA-256(image)` with the certificate's `contract_digest` (binding). A foreign key",
        "card shows the strong case: the signature IS valid under our key (OpenSSL says so)",
        "and invalid under the owner key — so KERN enforces the right trust root instead of",
        "rejecting everything.",
        "",
        "## What block 07 proves (verifiable RLVR reward)",
        "",
        "`--rlvr-reward` prints an exact scalar: `+1.0` verified (`trusted: 0 | holes: 0`),",
        "`-1.0` refuted (with a counterexample), `-2.0` reward hacking (`sys.exit` inside a",
        "function), `0.0` abstain (no annotations, or a body outside the closed fragment —",
        "measured: `x * 2` and `part * 100 // total` abstain, `x + x` proves). A",
        "syntactically broken answer is a fatal `SyntaxError` with **no reward at all**",
        "(fail-closed).",
        "",
        "The oracle re-reads `requires`/`ensures` itself, executes every candidate in real",
        "Python, and proves the reward is deserved: the counterexample violates the",
        "postcondition at an input that satisfies the precondition; the proven candidate",
        "keeps it across the whole declared domain; the cheat really contains `sys.exit`;",
        "the broken file really does not parse. Monotonicity and determinism are checked.",
        "",
        "## Honest boundaries",
        "",
        "- `kernc belnap` is a **pure lattice calculator** over four values. Certainty and",
        "  conflict predicates are **not** exposed as separate operations: no such native",
        "  predicate exists in `Bit`/`Eq2` today, so the CLI does not invent one; `--bits`",
        "  gives `pos`/`neg`, and a caller can derive \"definite\" or \"conflict\" from them.",
        "- The `--verify-doc` core is irreducible (removing any element revives the spec),",
        "  but it is not guaranteed to be minimum-cardinality.",
        "- `--explain` is a function passport, not a conflict localizer; it is verified as",
        "  such and no more.",
        "- `--concolic` prints only counts (no vectors) and is capped at 64 concrete runs",
        "  per function, with `assign`/`if`/`return` and linear conditions only.",
        "- `attest verify` always exits `0`; its verdict is textual only, so the gate",
        "  matches markers instead of rc (rc is not a signal here).",
        "- `--rlvr-reward` returns `+1.0` only for proofs inside the linear fragment;",
        "  `//` and variable-by-variable `*` abstain (`0.0`) instead of pretending.",
        "- A weak contract really does reward a constant (`return 0` with `result == 0`",
        "  earns `+1.0`): the reward is spec-relative, and the card says so.",
        "- `--heal` synthesises guards **only for division by zero** (`/`, `//`, `%`) —",
        "  exactly what `_crash_sites` searches for. It does **not** repair list index",
        "  out-of-range or a shifted threshold guard, so no such card is claimed here.",
        "- `--state-inv` proves the annotated invariant on **every return path** of the",
        "  annotated function; it is not a whole-program object invariant.",
        "- Cards are **data** (`benchmarks/full_spectrum/*.json`). Code is materialised into",
        "  a temporary directory, so no annotated `.py` file enters the repository tree and",
        "  `docs/contracts.lock.json` keeps sealing exactly its own specification files",
        "",
        "## Reproduce",
        "",
        "```bash",
        ".venv/bin/python tools/run_full_spectrum.py",
        "```",
        "",
        "Requires an interpreter with `z3` (the stock `.venv/bin/python`). Without `z3` the",
        "runner exits with `rc=2` and an explicit message instead of a green tick.",
        "",
        "TOTAL: cards %d | confirmed by KERN **and** the physical oracle %d | rc=0" % (
            len(results), len(results)),
        "",
    ]
    return "\n".join(L)


def render_ru(results, corpus_names):
    rows = _rows(results, "ru")
    L = [
        "# Full Spectrum 70 — окно №1: блоки 01–07 (%d из %d подтверждено)" % (len(results), len(results)),
        "",
        "Каждый механизм до сих пор был показан РОВНО на одном примере; здесь каждый",
        "прогоняется по корпусу боевых карточек. Каждая карточка проверяется **дважды**:",
        "вердикт KERN (нативный Zig / символически) и **независимый оракул**, который НЕ",
        "копирует таблицы движка (семантика пар битов для B4, исполнение CPython для кода).",
        "",
        "**Закон целостности:** `confirmed == total`. Если хотя бы одна карточка не",
        "подтверждена, раннер завершается с `rc=1` и витрины НЕ пишет вообще.",
        "",
        "Корпуса: `%s`." % "`, `".join(corpus_names),
        "",
        "## Карточки",
        "",
        "| № | блок | карточка | сфера | сюжет | KERN | физический оракул | статус |",
        "|---|------|----------|-------|-------|------|-------------------|--------|",
    ]
    for i, r, kern, oracle in rows:
        L.append("| %d | %s | `%s` | %s | %s | %s | %s | %s |" % (
            i, r["block"], r["id"], _cell(r["sphere"]), _cell(r["trick"]),
            _cell(kern), _cell(oracle), "OK" if not r["failed"] else "FAIL"))
    L += [
        "",
        "## Что доказывает блок 01 (нативная B4, `kernc belnap`)",
        "",
        "`kernc belnap <op> <a> [b]` печатает результат **нативной** функции ядра Zig",
        "(`src/core/eq2.zig`: `joinK`, `meetK`, `andT`, `orT`, `notB`). В обвязке НЕТ ни",
        "одной таблицы истинности: слой CLI только сопоставляет имя операции вызову,",
        "поэтому «CLI разошёлся с ядром» невозможно по построению. `--bits` печатает",
        "`<символ> <код> <pos> <neg>`, где `код = pos | (neg << 1)`.",
        "",
        "Оракул эти таблицы НЕ копирует: он пересчитывает B4 из пар свидетельств",
        "`(pos, neg) in {0,1}^2` — `N=(0,0)`, `T=(1,0)`, `F=(0,1)`, `B=(1,1)`, —",
        "комбинируя знание покомпонентно (`join_k` = OR/OR, `meet_k` = AND/AND), а истину",
        "монотонно (`and_t` = AND/OR, `or_t` = OR/AND), при `not = (neg, pos)`.",
        "Сверяется каждая клетка каждой строки, включая полный 68-строчный каскад `--table`.",
        "",
        "## Что доказывает блок 02 (авто-ремонт без ИИ, `--heal`)",
        "",
        "Каждая карточка проходит ВСЮ ДУГУ, а не печать рецепта:",
        "",
        "1. ДО: файл реально падает в `python3` (`ZeroDivisionError`), а `--xray`",
        "   печатает краш-путь;",
        "2. РЕМОНТ: `kern_contracts.py --heal` сам синтезирует гарды, вносит их в",
        "   исходник и печатает `T (1,0)` вместе с `после патча: 0`;",
        "3. ПОСЛЕ: вылеченный файл исполняется в `python3` без падения, `--xray` даёт",
        "   ноль краш-путей, повторная проверка контрактов — `нарушено 0 / НЕ РЕШЕНО 0`,",
        "   а **обычные входы по-прежнему дают математически верный результат** (гард не",
        "   превратил функцию в константу «0»).",
        "",
        "Бэкап `<file>.bak` проверяется на то, что в нём лежит ИСХОДНЫЙ код без патча.",
        "",
        "## Что доказывает блок 03 (противоречивые ТЗ, `--verify-doc`)",
        "",
        "Каждая карточка — документ из пунктов, конъюнкция которых **несовместна**. KERN",
        "печатает `[FAIL] CONFLICT B(1,1)` и `[CONFLICT B(1,1)] Minimal conflicting",
        "clauses: [...]` и завершается с `rc=1`. Ядро получается жадным удалением, поэтому",
        "оно **неприводимо, но не обязательно минимально по мощности** — это сказано, а не",
        "спрятано.",
        "",
        "Оракул пересчитывает математику с нуля (свой переводчик Python→z3, а не",
        "`expr_smt`): полный набор UNSAT; удаление **любого** элемента ядра даёт SAT;",
        "удаление любого **шумового** пункта оставляет UNSAT; модель ослабленной",
        "спецификации физически проверяется `eval` по всем оставшимся предикатам — то",
        "есть у оживлённой спецификации есть реальный вектор-свидетель.",
        "",
        "`--explain` проверяется как **вторичная поверхность-паспорт**: напечатанные CC,",
        "число выходов по SMT и строки падения обязаны совпасть с независимым",
        "AST-пересчётом. Конфликты он **не** локализует (измерено).",
        "",
        "## Что доказывает блок 04 (машины состояний во времени, `--state-inv`)",
        "",
        "Каждая карточка — многошаговый бизнес-автомат, где каждый метод по отдельности",
        "выглядит безобидно, но **цепочка переходов** ломает инвариант состояния:",
        "",
        "1. KERN печатает `[FAIL] <naive>: STATE INVARIANT VIOLATED` с конкретным",
        "   контрпримером и `[PASS] <guarded>: PROVEN` для защищённого перехода; ни один",
        "   `[UNKNOWN]` не принимается за доказательство;",
        "2. физический оракул реально проигрывает последовательности вызовов на объекте,",
        "   считает наблюдённые нарушения и исчерпывающе проверяет, что защищённый",
        "   переход не нарушает инвариант на сетке последовательностей.",
        "",
        "Карточка 10 добавляет **проверку мутацией**: снимите гарды эталонного эскроу —",
        "и доказательство KERN рассыпается в `[FAIL]`, а физический оракул показывает",
        "уход баланса в минус. Доказательство, которое выживает после снятия гарда, ничего",
        "не стоит.",
        "",
        "## Что доказывает блок 05 (конколическое покрытие ветвей, `--concolic`)",
        "",
        "Узкие вложенные ветвления (`x == magic`, лестницы из четырёх уровней,",
        "антифрод-правила) синтезируются конкретно: KERN печатает `[CONCOLIC] <fn>:",
        "concrete runs N, branches covered c/t (dead 0, unexplored 0)`. Измеренная",
        "граница: **движок не печатает сами входные векторы**, только счётчики.",
        "",
        "Поэтому физическую работу делает оракул: он инструментирует AST карточки своими",
        "маркерами, реально исполняет функцию по объявленному конечному домену, собирает",
        "множество `(строка, взято)` и вектор-свидетель для каждой целевой строки, и",
        "требует `covered == 2 × |if|`, `dead == 0`, `unexplored == 0`. Свойство",
        "«игольное ушко» проверяется отдельно: тривиальный вход из нулей НЕ должен",
        "проходить все целевые строки.",
        "",
        "## Что доказывает блок 06 (целостность .kimg и аттестация Ed25519)",
        "",
        "`kernc check-integrity` даёт `rc=0` на целом образе и `rc=2` на порче, называя причину: `BadMagic`, `UnsupportedVersion`, `BadHeaderSize`,",
        "`ОБЪЕКТ <i> ПОВРЕЖДЁН ... PayloadTampered`, `Образ слишком мал`. `kernc attest",
        "sign` подписывает ЛЮБЫМ 32-байтным seed, а `attest verify` проверяет **ключ",
        "владельца, вшитый в бинарник**, и ВСЕГДА выходит с `rc=0`: вердикт текстовый",
        "(`подпись=НЕВЕРНА|ok`, `привязка=ok|НЕ СОВПАЛА`). Эта граница измерена и названа.",
        "",
        "Оракул сам разбирает 128-байтный заголовок и 96-байтные записи таблицы,",
        "пересчитывает **BLAKE3 каждого объекта**, проверяет подпись сертификата через",
        "**OpenSSL Ed25519** нашим ключом И ключом владельца, и сверяет",
        "`SHA-256(образа)` с `contract_digest` сертификата (привязка). Карточка с чужим",
        "ключом показывает сильный случай: подпись ДЕЙСТВИТЕЛЬНО верна нашим ключом",
        "(OpenSSL подтверждает) и неверна ключом владельца — то есть KERN проверяет",
        "правильный корень доверия, а не отвергает всё подряд.",
        "",
        "## Что доказывает блок 07 (верифицируемая награда RLVR)",
        "",
        "`--rlvr-reward` печатает точный скаляр: `+1.0` доказано (`trusted: 0 | holes: 0`),",
        "`-1.0` опровергнуто (с контрпримером), `-2.0` чит (`sys.exit` внутри функции),",
        "`0.0` воздержание (нет аннотаций или тело вне замкнутого фрагмента — измерено:",
        "`x * 2` и `part * 100 // total` дают ABSTAIN, `x + x` доказывается).",
        "Синтаксически битый ответ — фатальный `SyntaxError` БЕЗ награды (fail-closed).",
        "",
        "Оракул сам перечитывает `requires`/`ensures`, сам исполняет каждого кандидата в",
        "Python и доказывает, что награда ЗАСЛУЖЕНА: контрпример нарушает постусловие на",
        "входе, удовлетворяющем предусловию; «доказанный» держит постусловие на всём",
        "объявленном домене; чит действительно содержит `sys.exit`; битый файл",
        "действительно не парсится. Монотонность и детерминизм проверяются.",
        "",
        "## Честные границы",
        "",
        "- `kernc belnap` — **чистый калькулятор бирешётки** на четырёх значениях. Предикаты",
        "  определённости и конфликта **не** выведены отдельными операциями: нативного",
        "  предиката такого в `Bit`/`Eq2` сегодня нет, и CLI его не выдумывает; `--bits`",
        "  отдаёт `pos`/`neg`, из которых вызывающий сам получает «определено»/«конфликт».",
        "- Ядро `--verify-doc` неприводимо (снятие любого элемента оживляет спецификацию),",
        "  но минимальность по мощности не гарантируется.",
        "- `--explain` — паспорт функции, а не локализатор конфликтов; он проверяется",
        "  ровно как паспорт и не более.",
        "- `--concolic` печатает только счётчики (векторов нет) и ограничен 64 реальными",
        "  запусками на функцию; поддерживаются `assign`/`if`/`return` и линейные условия.",
        "- `attest verify` всегда выходит с `0`; вердикт только текстовый, поэтому гейт",
        "  сверяет маркеры, а не rc (rc здесь не сигнал).",
        "- `--rlvr-reward` даёт `+1.0` только для доказательств внутри ЛИНЕЙНОГО фрагмента;",
        "  `//` и `*` переменная-на-переменную воздерживаются (`0.0`), а не притворяются.",
        "- Слабый контракт действительно награждает константу (`return 0` при `result == 0`",
        "  получает `+1.0`): награда относительна спецификации, и это сказано прямо.",
        "- `--heal` синтезирует гарды **только для деления на ноль** (`/`, `//`, `%`) —",
        "  ровно то, что ищет `_crash_sites`. Выход за границы списка и «сдвинутый порог»",
        "  он НЕ лечит, поэтому таких карточек здесь нет и не заявляется.",
        "- `--state-inv` доказывает аннотированный инвариант на **каждом пути возврата**",
        "  аннотированной функции; это не инвариант объекта на всю программу.",
        "- Карточки — **данные** (`benchmarks/full_spectrum/*.json`). Код материализуется",
        "  во временный каталог, поэтому в дерево репозитория не попадает аннотированный `.py`,",
        "  а `docs/contracts.lock.json` продолжает запечатывать ровно свои файлы спецификаций",
        "",
        "## Воспроизвести",
        "",
        "```bash",
        ".venv/bin/python tools/run_full_spectrum.py",
        "```",
        "",
        "Нужен интерпретатор с `z3` (штатно `.venv/bin/python`). Без `z3` раннер",
        "завершается с `rc=2` и явным сообщением, а не зелёной галочкой.",
        "",
        "ИТОГ: карточек %d | подтверждено KERN **и** физическим оракулом %d | rc=0" % (
            len(results), len(results)),
        "",
    ]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Full Spectrum 70: KERN-вердикт + физический оракул")
    ap.add_argument("--corpus", action="append", default=[], metavar="PATH",
                    help="JSON-корпус (по умолчанию все benchmarks/full_spectrum/*.json)")
    ap.add_argument("--no-docs", action="store_true",
                    help="только прогон, витрины не писать")
    args = ap.parse_args(argv)

    problem = preflight()
    if problem:
        print("[!] " + problem, file=sys.stderr)
        return 2

    paths = args.corpus or sorted(glob.glob(os.path.join(BENCH, "*.json")))
    paths = [p if os.path.isabs(p) else os.path.join(ROOT, p) for p in paths]
    if not paths:
        print("[!] нет корпусов в %s" % BENCH, file=sys.stderr)
        return 2
    cards = load_cards(paths)
    if not cards:
        print("[!] корпуса пусты: %s" % ", ".join(paths), file=sys.stderr)
        return 2

    results = [run_card(card) for card in cards]
    confirmed = [r for r in results if not r["failed"]]
    total = len(results)

    print("=" * 78)
    print("FULL SPECTRUM 70 | cards=%d | confirmed=%d | failed=%d"
          % (total, len(confirmed), total - len(confirmed)))
    print("=" * 78)
    for r in results:
        f = r["facts"]
        if r["kind"] == "heal":
            tail = "crash %s->%s, guards=%s, rc %s->%s" % (
                f.get("crash_before"), f.get("crash_after"), f.get("guards"),
                f.get("rc_before"), f.get("rc_after"))
        elif r["kind"] == "belnap":
            tail = "cells=%s, spec_gap_markers=%s, mode=%s" % (
                f.get("cells"), f.get("gap_markers"), f.get("mode"))
        elif r["kind"] == "explain":
            tail = "core=%s, noise=%s, revived=%s" % (
                f.get("core"), f.get("noise"), (f.get("revived") or {}).get("eval_ok"))
        elif r["kind"] == "concolic":
            tail = "runs=%s, covered=%s/%s, targets=%s/%s, vectors=%s" % (
                f.get("runs"), f.get("covered"), f.get("expected"),
                f.get("targets_hit"), f.get("targets"), f.get("vectors"))
        elif r["kind"] == "kimg":
            tail = "scenario=%s, integrity_rc=%s, sig(ours)=%s, sig(owner)=%s" % (
                f.get("scenario"), f.get("integrity_rc"),
                f.get("sig_valid_ours"), f.get("sig_valid_owner"))
        elif r["kind"] == "rlvr":
            tail = "rewards=" + ", ".join("%s:%s" % (k, v) for k, v in (f.get("rewards") or {}).items())
        else:
            tail = "violations=%s%s, safe_checks=%s, safe_violations=%s" % (
                f.get("unsafe_violations"),
                " (unguarded twin)" if "guard removal" in str(f.get("kern_note_en")) else "",
                f.get("safe_checks"), f.get("safe_violations"))
        print("  [%s] %-30s block %s | %s"
              % ("OK" if not r["failed"] else "FAIL", r["id"], r["block"], tail))
    print("=" * 78)

    if len(confirmed) != total:
        for r in results:
            if r["failed"]:
                print("\n[FAIL] %s (%s)" % (r["id"], r["kind"]))
                for e in r["errors"]:
                    print("   - " + e)
        print("\nLAW VIOLATED: confirmed != total (%d/%d) — витрины НЕ пишутся"
              % (len(confirmed), total), file=sys.stderr)
        return 1

    if not args.no_docs:
        corpus_names = sorted({os.path.basename(p) for p in paths})
        en_path = os.path.join(DOCS, "FULL_SPECTRUM_70.md")
        ru_path = os.path.join(DOCS, "FULL_SPECTRUM_70.ru.md")
        write_text(en_path, render_en(results, corpus_names))
        write_text(ru_path, render_ru(results, corpus_names))
        print("wrote %s" % os.path.relpath(en_path, ROOT))
        print("wrote %s" % os.path.relpath(ru_path, ROOT))

    print("LAW HOLDS: confirmed == total (%d/%d), rc=0" % (len(confirmed), total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
