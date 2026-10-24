# Code-checking corpus (four languages, hard `FP = 0` gate)

Each file carries the expected verdict in `<file>.expect.json`; the verdict
itself is **computed** by `tools/kern_contracts.py` + `kernc` + Z3 and never read
from the expectation. `make codecheck` prints the confusion matrix and fails if
`FP != 0` or `FN != 0`.

| File | Language | Contract | Expected | What it demonstrates |
|---|---|---|---|---|
| `py_abs_ok.py` | Python | `ensures result >= 0 and (result == x or result == -x)` | T | correct code is PROVED, not merely "not refuted" |
| `py_clamp_ok.py` | Python | `ensures result >= lo and result <= hi` | T | branches (`ite`) proved |
| `py_abs_bad.py` | Python | same as `py_abs_ok` | F | refuted with a real counterexample |
| `py_clamp_bad.py` | Python | same as `py_clamp_ok` | F | refuted |
| `py_nonlinear.py` | Python | `x * x` | N | outside the subset - honest "cannot decide" |
| `py_recursion.py` | Python | recursive body | N | unrolling is an under-approximation (#207) |
| `zig_clean.zig` | **Zig** | `ensures result == a + b` | T | Zig contracts ARE checked |
| `zig_div.zig` | **Zig** | `ensures result == a / b`, no guard | F | division-by-zero obligation fires |
| `zig_bounds.zig` | Zig | slice indexing | N | index reasoning outside the subset |
| `zig_loop.zig` | Zig | loop body | N | loops need CHC/loop-check |
| `c_clean.c` | **C** | `ensures result == a + b` | T | C contracts checked with `int` bounds |
| `c_unguarded.c` | **C** | `ensures result == a / b`, no guard | F | division-by-zero in C |
| `rust_clean.rs` | **Rust** | `ensures result == a + b` | T | Rust contracts checked |
| `rust_overflow.rs` | **Rust** | `requires a >= 0 and b >= 0`, `ensures result >= a` | F | **i32 overflow**: `a = 2147483647, b = 1 -> 2147483648` |
| `zig_allman.zig` | **Zig** | same as `zig_clean`, but `{` on the NEXT line | T | **defect #325**: Allman style must be RECOGNISED (it used to be silently skipped) |
| `rust_allman.rs` | **Rust** | same as `rust_overflow`, but `{` on the NEXT line | F | **defect #325**: a defect written in Allman style must be FOUND, not skipped |

`UNKNOWN` is a first-class outcome: "cannot decide" is honest, "guessed F" is
not. Only `FP` (accusing correct code) and `FN` (missing a real defect) fail the
gate.
