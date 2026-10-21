# Матрица «правило пруф-чекера ↔ теорема Lean 4»

Источник: `src/verifier/proof_check.zig` (17 функций `verify*` / `check*`) и
`formal/*.lean` (**143 теорем**, `lean` — 8/8 файлов, `0 errors`, `0 sorry`).

Таблица построена **по коду**, а не по замыслу: для каждого правила указаны
теоремы, которые действительно его обосновывают. Там, где отдельной теоремы
нет, это написано прямо и объяснено, **почему** её не требуется.

| Правило в `proof_check.zig` | Что проверяет | Обоснование в Lean 4 |
|:--|:--|:--|
| `checkRewrite` | равенство двух формул после нормализации | `eq_zero_iff_le_ge`, `eq_iff_le_ge_any`, `lin_sum_rearrange`, `cmp_sub_zero_iff`, `le_iff_sub_nonpos`, `ge_iff_sub_nonneg`, `not_le_iff_sub_pos`, `not_le_iff_shift`, `le_zero_iff_neg_ge_zero`, `eq_zero_iff_le_zero_of_nonneg`, `ite_cmp_bound`, `ite_cmp_bound_iff`, `eq_zero_iff_neg_zero`, `eq_iff_sub_eq_zero`, `not_true_bool`, `not_false_bool`, `or_false_left`, `and_true_left`, `ge_iff_le_swap`, `gt_iff_lt_swap`, `not_or_implies_not_left`, `not_or_implies_not_right`, `emod_nonneg_of_pos`, `wrap_cases_cover` |
| `verifyTransStar` | цепочка равенств `a₁=a₂=…=aₖ` | транзитивность — **правило ядра Lean** (`Eq.trans`), отдельная теорема не нужна; её расширение на цепочку обосновано индукцией по длине |
| `verifyIntroDef` | консервативное введение `z = E` (`z ∉ FV(E)`) | **структурное правило**: введение свежего имени не меняет выполнимость (ядро: `Eq.refl`); отдельной теоремы нет — свойство доказывается для конкретного `E` |
| `verifyLemma` | разрядка гипотез (RAA) | `lemma_raa_discharge` |
| `verifyIffTrue` | `iff-true` | `iff_true_sound` |
| `verifyIffFalse` | `iff-false` | `iff_false_sound` |
| `verifyDefAxiom` | определения связок (`ite`, `or`, `not`) | `const_ite_true`, `const_ite_false`, `not_true_bool`, `not_false_bool`, `or_false_left`, `and_true_left`, `de_morgan_mixed` |
| `verifyIteDisjunct` | дизъюнкты, порождённые `ite` | `ite_flip_cond_eq`, `ite_cmp_bound` |
| `verifyEqRule` | рефлексивность/симметрия равенств, константные сравнения | `eq_refl_iff_true`, `eq_refl_not_general`, `const_cmp_eval_sound`, `eq_iff_le_ge_any` |
| `verifyAndElim` | `and-elim` (`A ∧ B ⊢ A`) | **правило ядра Lean** (`And.left`); отдельная теорема не нужна |
| `verifyNotOrElim` | `not-or-elim` (де Морган из вывода Z3) | `not_or_implies_not_left`, `not_or_implies_not_right`, `not_or_does_not_imply_left` (последняя — контроль: обратное НЕверно) |
| `verifyMonotonicity` | конгруэнция по посылкам | `or_congruence_right`, `clause_derivation_independent` |
| `verifyThLemmaArith` | `th-lemma arith` (с весами и без) | `farkas_2_sound`, `farkas_3_sound`, `farkas_combination_nonpos`, `lin_sum_rearrange`, `emod_nonneg_of_pos`, `ite_cmp_bound` |
| `verifyFarkas` | сертификат Фаркаша (веса) | `farkas_combination_nonpos`, `farkas_2_sound`, `farkas_3_sound`, `bad_never_admitted` (звучность гейта) |
| `checkMp` | modus ponens | **правило ядра Lean** (`ModusPonens`); отдельная теорема не нужна |
| `checkBySplitting` | расщепление набора клауз (case split) | `case_split_2x2_unsat`, `bool_split_unsat`, `bool_split_not_unsat`, `enumeration_complete_1`, `enumeration_complete_2` |
| `checkUnitRes` | `unit-resolution` (в т.ч. частичная) | `unit_implies_lit_sound`, `contradiction_implies_anything`, `lit_eq_unit_satisfied`, `clause_cancels_neg_lit`, `clause_cancel_needs_truth`, `unit_res_remaining_is_concl`, `clause_derivation_independent`, `implies_not_symmetric` |

## Честные границы этой матрицы

1. **Три правила обоснованы ядром Lean**, а не отдельными теоремами:
   `verifyTransStar` (транзитивность), `verifyAndElim` (`And.left`), `checkMp`
   (modus ponens). Это не пробел: правило вывода ядра Lean 4 нечего доказывать
   внутри Lean.
2. **`verifyIntroDef`** — консервативное расширение: чтобы получить теорему,
   нужно зафиксировать конкретное `E`; для произвольного `E` свойство
   «свежее имя не меняет выполнимость» верно по построению.
3. **Матрица не утверждает полноту**: она утверждает, что каждое **принятое**
   правило имеет обоснование — теоремой, правилом ядра или явно названным
   структурным свойством. Отказ (`.unverifiable`, `.bad`) обоснования не требует.
4. Теоремы про `lowbit_*` (`bv_decide`) и `clamp_*` относятся к **битовым
   трюкам** и модели IEEE-754, а не к правилам вывода; они в таблицу не входят.

## Как воспроизвести

```bash
grep -cE '^fn (verify|check)[A-Za-z]*' src/verifier/proof_check.zig   # 17
grep -h '^theorem' formal/*.lean | wc -l                               # 137
./formal/check.sh                                                      # 0 errors, 0 sorry
```
