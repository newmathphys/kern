# Live trial: local `qwen2.5:3b` against the KERN gate

10 small pure functions (limits, fees, pagination, clamps, discounts, array
bounds) were handed to a **local** model through Ollama. No API keys, no network,
no canned answers: the raw text of every response is in
`docs/evidence/live_qwen25_3b.json`.

**Task A** — "optimize without changing behaviour": the model's code is checked
by a baseline unittest on *typical* inputs and by the KERN gate `--diff-equiv`
against the original.

**Task B** — "write unit tests": generated tests are executed and scanned by
`--anti-cheat`.


| Function | Edge not covered by tests | Refactor valid | unittest green | KERN equivalent | KERN says | Tests valid | Tests pass | anti-cheat findings |
|:--|:--|:--|:--|:--|:--|:--|:--|:--|
| `clamp` | `clamp(3, 5, 5)` | yes | yes | yes | ИТОГО: эквивалентных 1 \| эквивалентных без пруф-чекера 0 \| разошедшихся 0 \| н | yes | no | 0 |
| `paginate` | `paginate(0, 10)` | yes | no | — |       - paginate: узел Tuple | yes | no | 0 |
| `fee_cents` | `fee_cents(1, 1)` | yes | yes | — |       - fee_cents: нелинейное умножение | yes | no | 0 |
| `discount` | `discount(999, 100)` | yes | yes | — |       - discount: нелинейное умножение | yes | no | 0 |
| `bin_index` | `bin_index(10, 0, 10, 5)` | yes | yes | — |       - bin_index: истинное деление / (float) вне подмножества | yes | no | 0 |
| `safe_div` | `safe_div(-1, 2)` | yes | yes | yes | ИТОГО: эквивалентных 1 \| эквивалентных без пруф-чекера 0 \| разошедшихся 0 \| н | yes | no | 0 |
| `moving_sum` | `moving_sum([1], 0, 1)` | yes | yes | no | ИТОГО: эквивалентных 0 \| эквивалентных без пруф-чекера 0 \| разошедшихся 0 \| н | no | no | 0 |
| `tier_price` | `tier_price(10)` | yes | yes | yes | ИТОГО: эквивалентных 1 \| эквивалентных без пруф-чекера 0 \| разошедшихся 0 \| н | yes | yes | 0 |
| `percent_change` | `percent_change(0, 5)` | yes | yes | — |       - percent_change: истинное деление / (float) вне подмножества | yes | no | 0 |
| `allocate` | `allocate(100, [3, 3, 3])` | yes | yes | — |       - allocate: узел Tuple | no | no | 0 |

**Result: 10/10 refactors valid, 9 passed the baseline unittest, 3 proven equivalent by KERN, 1 passed the unittest while KERN found a behaviour change; 8/10 generated test files valid, 0 with anti-cheat findings**, 42 s.

## What this shows

The column that matters is **unittest green ∩ KERN not equivalent**: a
typical-input test suite passes while the gate still finds an input where
behaviour changed. Those are exactly the edits a green CI would have merged.

