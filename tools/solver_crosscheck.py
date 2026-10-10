#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KERN: КОНСИЛИУМ РЕШАТЕЛЕЙ — Z3 vs cvc5.

Если два независимых SMT-решателя расходятся (один UNSAT, другой SAT),
KERN фиксирует Solver Divergence — защита от багов конкретного решателя.
"""
import sys

FORMULAS = [
    # (имя, скрипт)
    ("простая SAT", "(set-logic ALL)(declare-const x Int)(assert (> x 5))(check-sat)"),
    ("простая UNSAT", "(set-logic ALL)(declare-const x Int)(assert (> x 5))(assert (< x 2))(check-sat)"),
    ("overflow u32", "(set-logic QF_BV)(declare-const x (_ BitVec 32))(assert (bvult (bvadd x #x00000001) x))(check-sat)"),
    ("NIA x*x>=0", "(set-logic QF_NIA)(declare-const x Int)(assert (< (* x x) 0))(check-sat)"),
    ("x*2 == x<<1", "(set-logic QF_BV)(declare-const x (_ BitVec 32))(assert (not (= (bvmul x #x00000002) (bvshl x #x00000001))))(check-sat)"),
    ("деление на 0", "(set-logic QF_LIA)(declare-const x Int)(declare-const y Int)(assert (= (div x 0) y))(check-sat)"),
    ("FP: NaN != NaN (fp.eq)", "(set-logic QF_FP)(declare-const x Float32)(assert (not (fp.eq x x)))(check-sat)"),
    ("BitVec(1024) экв", "(set-logic QF_BV)(declare-const x (_ BitVec 1024))(assert (not (= (bvmul x (_ bv2 1024)) (bvshl x (_ bv1 1024)))))(check-sat)"),
    ("ложная оптимизация x/2==x>>1", "(set-logic QF_BV)(declare-const x (_ BitVec 32))(assert (not (= (bvsdiv x #x00000002) (bvashr x #x00000001))))(check-sat)"),
]


def run_z3(script: str) -> str:
    import z3
    try:
        s = z3.Solver()
        s.from_string(script)
        r = s.check()
        return str(r)
    except Exception as e:
        return f"ERR:{type(e).__name__}"


def run_cvc5(script: str) -> str:
    import cvc5
    try:
        solver = cvc5.Solver()
        solver.setOption("produce-models", "true")
        parser = cvc5.InputParser(solver)
        parser.setStringInput(cvc5.InputLanguage.SMT_LIB_2_6, script, "inline")
        sm = parser.getSymbolManager()
        while True:
            cmd = parser.nextCommand()
            if cmd.isNull():
                break
            res = cmd.invoke(solver, sm)
            if res:
                txt = str(res)
                if "unsat" in txt.lower():
                    return "unsat"
                if "sat" in txt.lower():
                    return "sat"
        return "unknown"
    except Exception as e:
        return f"ERR:{type(e).__name__}"


def main():
    print(f"{'Формула':<32} | {'Z3':<8} | {'cvc5':<8} | согласие")
    print("-" * 66)
    agree = diverge = err = 0
    for name, script in FORMULAS:
        z = run_z3(script)
        c = run_cvc5(script)
        if z.startswith("ERR") or c.startswith("ERR"):
            err += 1
            mark = "⚠️ ошибка движка"
        elif z == c:
            agree += 1
            mark = "✅ согласие"
        else:
            diverge += 1
            mark = "🔴 РАСХОЖДЕНИЕ"
        print(f"{name:<32} | {z:<8} | {c:<8} | {mark}")
    print("-" * 66)
    print(f"\n📊 Консилиум решателей: согласие {agree}, расхождений {diverge}, ошибок {err}")
    if diverge:
        print("🔴 SOLVER DIVERGENCE — требует ручного разбора!")
    else:
        print("✅ Расхождений нет — вердикты Z3 подтверждены независимым решателем cvc5")


if __name__ == "__main__":
    main()
