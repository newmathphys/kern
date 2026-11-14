# Polyglot benchmarks: BigCode HumanEvalPack under KERN

Source: **`bigcode/humanevalpack`** (Hugging Face), fetched through the public
Datasets Server as JSON (the repo ships parquet and `pyarrow` is not installed here).
Each record carries the authors' pair `canonical_solution` / `buggy_solution` plus
`bug_type` - the code is not ours.

Language: **python**, tasks **164**.

| Verdict | Count |
|:--|--:|
| **DIVERGED (physically confirmed)** | **6** |
| unconfirmed (solver said diverge, runtime disagreed) | 2 |
| honest SKIP | 156 |

Bugs caught by type: {'value misuse': 1, 'excess logic': 3, 'variable misuse': 1, 'missing logic': 1}

## Honest limits

HumanEvalPack tasks are almost entirely list/string algorithms, which is outside KERN
model: the 156 skips are the declared boundary, not a hidden failure.
`DIVERGED` rows are confirmed by executing both implementations in Python on the
solver's counterexample, not by reading the solver output.

C++ and Rust splits are **not** covered here: they need the `--xray` iron criterion
(finding present on `buggy_solution` and gone on `canonical_solution`), which is a
separate pipeline.
