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
import glob
import json
import os
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


def run_card(card):
    with tempfile.TemporaryDirectory(prefix="full_spectrum_") as tmpdir:
        if card["kind"] == "heal":
            errs, facts = check_heal(card, tmpdir)
        elif card["kind"] == "state-inv":
            errs, facts = check_state_inv(card, tmpdir)
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
            if card["kind"] in ("heal", "state-inv") and "code" not in card:
                raise SystemExit("[!] %s: карточке %s нужен `code`" % (path, card["id"]))
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
        elif r["kind"] == "belnap":
            kern = f.get("kern_note_" + lang) or "%s native cell(s)" % f.get("cells")
            oracle = f.get("oracle_note_" + lang) or "bit-pair oracle agrees"
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
        "# Full Spectrum 70 — window 1: blocks 01, 02 and 04 (%d of %d confirmed)" % (len(results), len(results)),
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
        "## Honest boundaries",
        "",
        "- `kernc belnap` is a **pure lattice calculator** over four values. Certainty and",
        "  conflict predicates are **not** exposed as separate operations: no such native",
        "  predicate exists in `Bit`/`Eq2` today, so the CLI does not invent one; `--bits`",
        "  gives `pos`/`neg`, and a caller can derive \"definite\" or \"conflict\" from them.",
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
        "# Full Spectrum 70 — окно №1: блоки 01, 02 и 04 (%d из %d подтверждено)" % (len(results), len(results)),
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
        "## Честные границы",
        "",
        "- `kernc belnap` — **чистый калькулятор бирешётки** на четырёх значениях. Предикаты",
        "  определённости и конфликта **не** выведены отдельными операциями: нативного",
        "  предиката такого в `Bit`/`Eq2` сегодня нет, и CLI его не выдумывает; `--bits`",
        "  отдаёт `pos`/`neg`, из которых вызывающий сам получает «определено»/«конфликт».",
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
