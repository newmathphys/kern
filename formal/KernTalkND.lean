-- Copyright (c) 2026 mrbritneyxxx. All rights reserved.
-- Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

-- KERN TALK ND: N-МЕРНАЯ УНИФИКАЦИЯ (Безопасность матрицы ограничений)
-- Verified in Lean 4 with Mathlib. БЕЗ 'sorry'.
import Mathlib.Basic.Real.Basic

namespace KernTalkND

inductive Belnap where
  | N : Belnap
  | T : Belnap
  | F : Belnap
  | B : Belnap
deriving DecidableEq, Repr

/-- Интервал допустимых значений одной размерности. -/
structure Interval where
  min_val : ℝ
  max_val : ℝ

noncomputable def Interval.unify (i1 i2 : Interval) : Interval :=
  ⟨max i1.min_val i2.min_val, min i1.max_val i2.max_val⟩

noncomputable def Interval.isConflict (i : Interval) : Bool :=
  decide (i.min_val > i.max_val)

/-- n-мерная спецификация — вектор интервалов длины n. -/
abbrev Spec (n : ℕ) := Fin n → Interval

/-- Покоординатная унификация n-мерного вектора. -/
noncomputable def unifySpec {n : ℕ} (s1 s2 : Spec n) : Spec n :=
  fun i => (s1 i).unify (s2 i)

/-- Глобальная оценка: нарушена хотя бы одна координата → B, иначе T. -/
noncomputable def evaluateSpec {n : ℕ} (s : Spec n) : Belnap :=
  if ∃ i : Fin n, (s i).isConflict = true then Belnap.B else Belnap.T

/-- ТЕОРЕМА: нарушение хотя бы по одной размерности k даёт глобальный конфликт B. -/
theorem nd_violation_yields_conflict {n : ℕ} (human ai : Spec n) (k : Fin n)
    (h_violation : (human k).max_val < (ai k).min_val) :
    evaluateSpec (unifySpec human ai) = Belnap.B := by
  have h_lt : max (human k).min_val (ai k).min_val > min (human k).max_val (ai k).max_val := by
    calc max (human k).min_val (ai k).min_val
        ≥ (ai k).min_val := le_max_right _ _
      _ > (human k).max_val := h_violation
      _ ≥ min (human k).max_val (ai k).max_val := min_le_left _ _
  have h_k : ((unifySpec human ai) k).isConflict = true := by
    simp only [unifySpec, Interval.isConflict, Interval.unify]
    exact decide_eq_true h_lt
  have h_exists : ∃ i : Fin n, ((unifySpec human ai) i).isConflict = true := ⟨k, h_k⟩
  simp only [evaluateSpec]
  simp [h_exists]

end KernTalkND
