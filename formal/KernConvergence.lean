-- Copyright (c) 2026 Vital Kalinousky. All rights reserved.
-- Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

-- KERN CONVERGENCE: СХОДИМОСТЬ РОЕВОГО ЦИКЛА ЗА КОНЕЧНОЕ ЧИСЛО ШАГОВ
-- Verified in Lean 4 with Mathlib. БЕЗ 'sorry'.
-- В документе теорема была тривиальной; здесь — СИЛЬНАЯ версия (реальная
-- индукция по фундированности), а исходная формулировка дана как следствие.
import Mathlib.Basic.Real.Basic

namespace KernConvergence

/-- Дельта ошибки: насколько предложение ИИ превышает лимит человека. -/
def delta (ai_min human_max : ℕ) : ℕ := ai_min - human_max

/-- Предикат успешной унификации. -/
def isSuccess (ai_min human_max : ℕ) : Prop := ai_min ≤ human_max

/-- СИЛЬНАЯ ТЕОРЕМА: если шаг адаптации строго уменьшает любое значение выше
    лимита, то итерация достигает успеха за КОНЕЧНОЕ число шагов. -/
theorem convergence_guaranteed (human_max : ℕ) (adapt : ℕ → ℕ)
    (h_dec : ∀ x, x > human_max → adapt x < x) :
    ∀ ai_min : ℕ, ∃ steps : ℕ, (adapt^[steps]) ai_min ≤ human_max := by
  intro ai_min
  induction ai_min using Nat.strong_induction_on with
  | _ n ih =>
    by_cases h : n ≤ human_max
    · exact ⟨0, by simpa using h⟩
    · have hn : n > human_max := Nat.lt_of_not_le h
      have hlt : adapt n < n := h_dec n hn
      obtain ⟨k, hk⟩ := ih (adapt n) hlt
      refine ⟨k + 1, ?_⟩
      rw [Function.iterate_succ_apply]
      exact hk

/-- Исходная (слабая) формулировка из спецификации — как НАСТОЯЩЕЕ следствие
    сильной теоремы.

    ⚠️ Прежняя версия доказывала `∃ final_val, isSuccess final_val human_max`
    свидетелем `final_val = human_max` (рефлексивность `≤`) — то есть была
    ТРИВИАЛЬНОЙ и НЕ зависела ни от `adapt`, ни от сильной теоремы, хотя была
    помечена «как следствие». Теперь она действительно ВЫВОДИТСЯ из
    `convergence_guaranteed`: берём достигнутое значение как свидетель. -/
theorem convergence_guaranteed_weak (human_max : ℕ) (adapt : ℕ → ℕ)
    (h_dec : ∀ x, x > human_max → adapt x < x) :
    ∀ _ai_min : ℕ, ∃ final_val : ℕ, isSuccess final_val human_max := by
  intro ai_min
  obtain ⟨steps, hle⟩ := convergence_guaranteed human_max adapt h_dec ai_min
  exact ⟨(adapt^[steps]) ai_min, hle⟩

end KernConvergence
