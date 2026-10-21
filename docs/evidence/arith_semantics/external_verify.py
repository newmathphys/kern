"""Differential check of KERN's Python integer translation, not its full gate."""
import ast
import importlib.util
import json
import pathlib
import sys
import z3

repo = pathlib.Path(sys.argv[1]).resolve()
spec = importlib.util.spec_from_file_location('kern_contracts', repo/'tools/kern_contracts.py')
kc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kc)

def candidate(a, b, op):
    # Reference adapter for PYTHON integers only. b=0 must remain a separate
    # runtime-safety obligation; other languages need their own semantics.
    q = f'(ite (> {b} 0) (div {a} {b}) (div (- {a}) (- {b})))'
    return q if op == '//' else f'(- {a} (* {b} {q}))'

def evaluate(text):
    assertion = z3.parse_smt2_string('(declare-const r Int)(assert (= r '+text+'))')[0]
    return z3.simplify(assertion.arg(1)).as_long()

old_bad = new_bad = positive_bad = total = 0
examples = []
for a in range(-10, 11):
    for b in range(-10, 11):
        if b == 0:
            continue
        for op in ('//', '%'):
            expression = f'({a}) {op} ({b})'
            expected = a//b if op == '//' else a%b
            original = kc.expr_smt(ast.parse(expression, mode='eval').body, {})
            old = evaluate(original)
            fixed = evaluate(candidate(str(a), str(b), op))
            total += 1
            old_bad += old != expected
            new_bad += fixed != expected
            positive_bad += b > 0 and old != expected
            if old != expected and len(examples) < 4:
                examples.append(dict(expression=expression, python=expected, original=old, candidate=fixed))

report = dict(evaluations=total, original_mismatches=old_bad,
              candidate_mismatches=new_bad, positive_divisor_original_mismatches=positive_bad,
              z3=z3.get_version_string(), examples=examples)
print(json.dumps(report, indent=2))
assert old_bad > 0, 'can-fail: original translator must disagree'
assert positive_bad == 0, 'control: positive divisors must agree'
assert new_bad == 0, 'candidate must agree on every checked input'
