# formal/ — формальные доказательства KERN (Lean 4)

**Статус: ИЗМЕРЕНО.** Все файлы компилируются Lean 4.34.0 с **0 ошибок и
0 `sorry`** (в исходном документе в `KernTalk` был `sorry` — здесь доказано
по-настоящему). Проверка: `./formal/check.sh`.

| Файл | Что доказывает | Зависимости |
|:--|:--|:--|
| `KernAllMath.lean` | Решётка Белнапа B₄: де Морган, инволюция, коммутативность/ассоциативность/идемпотентность JOIN_K, дистрибутивность AND_T над OR_T, изоляция конфликта `T⊔F=B`, анти-вакуумный шлюз, тотальность fuel-обхода | Pure Lean 4 Core (без Mathlib) |
| `KernDfsTermination.lean` | Фундированность ⇒ завершимость обхода; тотальность обхода с топливом | Pure Lean 4 Core |
| `KernTalk.lean` | `ai_hallucination_yields_conflict`: `human.max < ai.min ⇒ unify = B`; `consistent_yields_truth` | Mathlib (ℝ) |
| `KernTalkND.lean` | `nd_violation_yields_conflict`: нарушение хотя бы по одной из N размерностей ⇒ глобальный `B` | Mathlib (ℝ) |
| `KernConvergence.lean` | СИЛЬНАЯ теорема сходимости: итерация строго убывающей адаптации достигает `isSuccess` за конечное число шагов (индукция по фундированности ℕ) + слабая формулировка из спецификации как следствие | Mathlib |

## Соответствие коду

- `KernAllMath.Belnap` ↔ `src/core/eq2.zig` (`Eq2`, кодировка `p | (n<<1)`).
- `KernAllMath.FuelBoundedDfs` ↔ `src/runtime/kern_x.zig` (топливо).
- `KernTalk`/`KernTalkND` ↔ `kernc unify` (сечение политопов).
- `KernConvergence` ↔ RLAIF-цикл (градиент ошибки).

## Запуск

```bash
./formal/check.sh          # все файлы + проверка отсутствия sorry
# или по отдельности:
lean formal/KernAllMath.lean
(cd ~/mathlib_proj && lake env lean "$PWD/formal/KernTalk.lean")
```

> Примечание: импорт в файлах с Mathlib использует новый путь
> `Mathlib.Basic.Real.Basic` (старый `Mathlib.Data.Real.Basic` устарел).
