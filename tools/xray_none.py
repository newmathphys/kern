#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""--xray-none: мини-CFG детекции разыменования None.

Решётка состояний NON_NULL/MAYBE/NULL, сужение на уровне выражений
(короткое замыкание And/Or, IfExp, is None, truthiness, isinstance, hasattr),
слияние живых ветвей, отсечение мёртвых рёбер (return/raise).
Контракт: run(path, smt) -> (rc, lines); smt(params, asserts) -> True/False/None.
"""
from __future__ import annotations
import ast
from pathlib import Path

SENTINEL = "-4611686018427387904"
NON_NULL, MAYBE, NULL = "nonnull", "maybe", "null"
ARITH = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)
ORDER = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)


def nullable_params(fn):
    out, a = set(), fn.args
    names = {x.arg for x in list(a.args) + list(a.kwonlyargs)}
    for arg in list(a.args) + list(a.kwonlyargs):
        if arg.annotation is not None:
            try:
                txt = ast.unparse(arg.annotation)
            except Exception:
                txt = ""
            if "None" in txt:
                out.add(arg.arg)
    for arg, d in zip(a.args[len(a.args) - len(a.defaults):], a.defaults):
        if isinstance(d, ast.Constant) and d.value is None:
            out.add(arg.arg)
    for arg, d in zip(a.kwonlyargs, a.kw_defaults):
        if isinstance(d, ast.Constant) and d.value is None:
            out.add(arg.arg)
    for n in ast.walk(fn):
        if isinstance(n, ast.Compare) and len(n.ops) == 1 and isinstance(n.ops[0], (ast.Is, ast.IsNot)):
            sides = [n.left] + list(n.comparators)
            if any(isinstance(s, ast.Constant) and s.value is None for s in sides):
                for s in sides:
                    if isinstance(s, ast.Name) and s.id in names:
                        out.add(s.id)
    return out


def _join_state(a, b):
    if a == b:
        return a
    if a is None:
        return b
    if b is None:
        return a
    return MAYBE


def _none_literal(node) -> bool:
    """Является ли выражение литералом None (единственный источник NULL)."""
    return isinstance(node, ast.Constant) and node.value is None


def _join_env(a, b):
    return {k: _join_state(a.get(k, NON_NULL), b.get(k, NON_NULL)) for k in set(a) | set(b)}

class Analyzer:
    def __init__(self, params, nullable, smt):
        self.params, self.nullable, self.smt, self.out = params, nullable, smt, []

    def _deref(self, line, name, kind, env, facts):
        if name not in self.params or env.get(name, NON_NULL) == NON_NULL:
            return
        if self.smt(self.params, list(facts) + ["(= %s %s)" % (name, SENTINEL)]) is True:
            self.out.append((line, name, kind))

    def check_expr(self, node, env, facts):
        if node is None:
            return
        if isinstance(node, ast.IfExp):
            (et, ft), (ef, ff) = self.refine(node.test, env, facts)
            self.check_expr(node.body, et, ft)
            self.check_expr(node.orelse, ef, ff)
            return
        if isinstance(node, ast.BoolOp):
            # короткое замыкание: правый операнд виден суженным левым
            andop = isinstance(node.op, ast.And)
            e, f = dict(env), list(facts)
            for v in node.values:
                self.check_expr(v, e, f)
                rt, rf = self.refine(v, e, f)
                e, f = rt if andop else rf
            return
        targets, kind = [], ""
        if isinstance(node, ast.BinOp) and isinstance(node.op, ARITH):
            targets, kind = [node.left, node.right], "TypeError (арифметика)"
        elif isinstance(node, ast.Compare) and any(isinstance(o, ORDER) for o in node.ops):
            targets, kind = [node.left] + list(node.comparators), "TypeError (сравнение порядка)"
        elif isinstance(node, ast.Attribute):
            targets, kind = [node.value], "AttributeError"
        elif isinstance(node, ast.Subscript):
            targets, kind = [node.value], "TypeError (подписка)"
        for t in targets:
            if isinstance(t, ast.Name):
                self._deref(getattr(node, "lineno", 0), t.id, kind, env, facts)
        for ch in ast.iter_child_nodes(node):
            self.check_expr(ch, env, facts)

    def refine(self, test, env, facts):
        et, ft = dict(env), list(facts)
        ef, ff = dict(env), list(facts)
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            (a, fa), (b, fb) = self.refine(test.operand, env, facts)
            return (b, fb), (a, fa)
        if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], (ast.Is, ast.IsNot)):
            sides = [test.left] + list(test.comparators)
            name = next((s.id for s in sides if isinstance(s, ast.Name) and s.id in self.nullable), None)
            if name and any(isinstance(s, ast.Constant) and s.value is None for s in sides):
                pos = "(= %s %s)" % (name, SENTINEL)
                neg = "(distinct %s %s)" % (name, SENTINEL)
                if isinstance(test.ops[0], ast.Is):
                    et[name], ft = NULL, ft + [pos]
                    ef[name], ff = NON_NULL, ff + [neg]
                else:
                    et[name], ft = NON_NULL, ft + [neg]
                    ef[name], ff = NULL, ff + [pos]
                return (et, ft), (ef, ff)
        if isinstance(test, ast.Name) and test.id in self.nullable:
            s = test.id
            et[s], ft = NON_NULL, ft + ["(and (distinct %s 0) (distinct %s %s))" % (s, s, SENTINEL)]
            ef[s], ff = MAYBE, ff + ["(or (= %s 0) (= %s %s))" % (s, s, SENTINEL)]
            return (et, ft), (ef, ff)
        if (isinstance(test, ast.Call) and isinstance(test.func, ast.Name)
                and test.func.id in ("isinstance", "hasattr") and test.args
                and isinstance(test.args[0], ast.Name) and test.args[0].id in self.nullable):
            nm = test.args[0].id
            tt = ast.unparse(test.args[1]) if len(test.args) > 1 else ""
            if test.func.id == "hasattr" or "None" not in tt:
                et[nm], ft = NON_NULL, ft + ["(distinct %s %s)" % (nm, SENTINEL)]
                ef[nm] = MAYBE
                return (et, ft), (ef, ff)
        if isinstance(test, ast.BoolOp) and test.values:
            if isinstance(test.op, ast.And):
                for v in test.values:
                    self.check_expr(v, et, ft)
                    et, ft = self.refine(v, et, ft)[0]
                return (et, ft), (ef, ff)
            for v in test.values:
                self.check_expr(v, ef, ff)
                ef, ff = self.refine(v, ef, ff)[1]
            return (et, ft), (ef, ff)
        self.check_expr(test, env, facts)
        return (et, ft), (ef, ff)

    def walk(self, stmts, env, facts):
        for st in stmts:
            if isinstance(st, (ast.Assign, ast.AnnAssign)):
                self.check_expr(st.value, env, facts)
                tgts = st.targets if isinstance(st, ast.Assign) else [st.target]
                for t in tgts:
                    if isinstance(t, ast.Name) and t.id in self.nullable:
                        env = dict(env)
                        v = st.value
                        if isinstance(v, ast.Constant) and v.value is None:
                            env[t.id] = NULL
                        elif (isinstance(v, ast.Constant)
                              or (isinstance(v, ast.Name) and env.get(v.id) == NON_NULL)
                              or isinstance(v, (ast.BinOp, ast.Compare, ast.Attribute,
                                                ast.Subscript, ast.Call))
                              or (isinstance(v, ast.IfExp)
                                  and not _none_literal(v.body)
                                  and not _none_literal(v.orelse))):
                            env[t.id] = NON_NULL
                        else:
                            env[t.id] = MAYBE
                continue
            if isinstance(st, ast.Expr):
                self.check_expr(st.value, env, facts)
                continue
            if isinstance(st, ast.Return):
                self.check_expr(st.value, env, facts)
                return None
            if isinstance(st, ast.Raise):
                self.check_expr(st.exc, env, facts)
                return None
            if isinstance(st, ast.If):
                (et, ft), (ef, ff) = self.refine(st.test, env, facts)
                r1 = self.walk(st.body, et, ft)
                r2 = self.walk(st.orelse, ef, ff)
                if r1 is None and r2 is None:
                    return None
                if r1 is None:
                    env, facts = r2
                elif r2 is None:
                    env, facts = r1
                else:
                    env, facts = (_join_env(r1[0], r2[0]),
                                  [f for f in r1[1] if f in r2[1]])
                continue
            if isinstance(st, (ast.Try, ast.With)):
                self.walk(getattr(st, "body", []) or [], dict(env), list(facts))
                for h in getattr(st, "handlers", []) or []:
                    self.walk(h.body, dict(env), list(facts))
                self.walk(getattr(st, "orelse", []) or [], dict(env), list(facts))
                self.walk(getattr(st, "finalbody", []) or [], dict(env), list(facts))
                continue
            for ch in ast.iter_child_nodes(st):
                if isinstance(ch, ast.expr):
                    self.check_expr(ch, env, facts)
        return env, facts


def analyze(src, smt):
    tree = ast.parse(src)
    hits, checked = [], 0
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        params = [a.arg for a in fn.args.args if a.arg not in ("self", "cls")]
        nullable = nullable_params(fn)
        if not nullable:
            continue
        checked += 1
        an = Analyzer(params, nullable, smt)
        an.walk(list(fn.body), {n: MAYBE for n in nullable}, [])
        hits.extend((fn.name,) + h for h in an.out)
    uniq, seen = [], set()
    for h in hits:
        if h not in seen:
            seen.add(h)
            uniq.append(h)
    return uniq, checked


def run(path, smt):
    src = Path(path).read_text(encoding="utf-8", errors="replace")
    hits, checked = analyze(src, smt)
    lines = ["  [CRASH PATH] %s: строка %d — разыменование None (%s): %s" % h for h in hits]
    lines.append("-" * 74)
    lines.append("[XRAY-NONE] функций с nullable-параметрами %d | находок %d" % (checked, len(hits)))
    return (1 if hits else 0), lines
