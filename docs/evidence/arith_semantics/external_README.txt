M / KERN: Python integer translation — local differential verification

Source: https://github.com/newmathphys/kern
Frozen revision: e065857e652f74fde523129572231f4dc7f8d641
Examined component: tools/kern_contracts.py, expr_smt.

M conceptual path
The solver's conclusion depends on the translated expression preserving the
meaning of the executed source. A correct proof of a different expression
does not settle the source-code claim. Arithmetic semantics is part of that
dependency, including the sign of the divisor.

Reproduction
Python 1 // -2 returns -1; the existing translator emits (div 1 (- 2)),
which Z3 evaluates to 0. Python 1 % -2 returns -1; its emitted SMT mod returns 1.

Candidate correction for Python integers, nonzero divisor b
q = ite(b > 0, div(a,b), div(-a,-b))
r = a - b*q
This uses a positive SMT divisor in either branch and preserves Python's
floor quotient and divisor-signed remainder. Division by zero still requires
the existing separate safety obligation. Python / (true division) is not
covered. Other source languages require their own arithmetic semantics.

Verification
Run with Python 3.12 and z3-solver (tested Z3 5.3.1):
  python verify.py /path/to/kern
The script imports the original translator, generates expressions through
its actual expr_smt entry point, evaluates them with Z3, and compares both
the original and reference adapter with actual Python arithmetic.
Domain: a,b in [-10,10], b != 0; both // and %: 840 evaluations.
Original: 292 mismatches. Reference adapter: zero mismatches.
Positive-divisor control: zero original mismatches. Assertions require the
original to disagree and the candidate to agree, preventing a vacuous pass.

Scope
This is a tested reference adapter, NOT an integrated upstream patch, NOT a
test of the full Zig proof checker, NOT evidence of an end-to-end false
accept or deployed exploit. No claim is made about all KERN languages.
Integration must preserve language-specific semantics in the function body,
preconditions and postconditions, with regressions and the upstream checks.
No KERN source is redistributed in this archive.

Disclosure
The repository requests private reporting for security-relevant findings.
Do not post detailed reproducers publicly before maintainer assessment.
