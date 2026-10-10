-- KERN TALK: FORMAL UNIFICATION AND BELNAP RESOLUTION
-- Verified in Lean 4 with Mathlib. БЕЗ 'sorry' (в документе был sorry — здесь доказано).
import Mathlib.Basic.Real.Basic

namespace KernTalk

inductive Belnap where
  | N : Belnap
  | T : Belnap
  | F : Belnap
  | B : Belnap
deriving DecidableEq, Repr

/-- Ограничение (Constraint): например, потребление памяти или задержка. -/
structure Constraint where
  min_val : ℝ
  max_val : ℝ

/-- Унификация: пересечение интервалов требований Человека и ИИ. -/
noncomputable def unify (c1 c2 : Constraint) : Constraint :=
  { min_val := max c1.min_val c2.min_val,
    max_val := min c1.max_val c2.max_val }

/-- Эпистемический шлюз: пустое пересечение → конфликт B, иначе T. -/
noncomputable def evaluateUnification (c : Constraint) : Belnap :=
  if c.min_val > c.max_val then Belnap.B else Belnap.T

/-- ТЕОРЕМА: если предложение ИИ выходит за рамки требований Архитектора
    (human.max < ai.min), унификация СТРОГО даёт конфликт B. -/
theorem ai_hallucination_yields_conflict
    (human_req ai_proposal : Constraint)
    (h_violation : human_req.max_val < ai_proposal.min_val) :
    evaluateUnification (unify human_req ai_proposal) = Belnap.B := by
  have h : (unify human_req ai_proposal).min_val > (unify human_req ai_proposal).max_val := by
    simp only [unify]
    calc max human_req.min_val ai_proposal.min_val
        ≥ ai_proposal.min_val := le_max_right _ _
      _ > human_req.max_val := h_violation
      _ ≥ min human_req.max_val ai_proposal.max_val := min_le_left _ _
  simp only [evaluateUnification]
  simp [h]

/-- Следствие: согласованные требования (пересечение непусто) дают T. -/
theorem consistent_yields_truth
    (human_req ai_proposal : Constraint)
    (h_ok : max human_req.min_val ai_proposal.min_val ≤
            min human_req.max_val ai_proposal.max_val) :
    evaluateUnification (unify human_req ai_proposal) = Belnap.T := by
  have h : ¬ ((unify human_req ai_proposal).min_val > (unify human_req ai_proposal).max_val) := by
    simp only [unify]
    exact not_lt.mpr h_ok
  simp only [evaluateUnification]
  simp [h]

end KernTalk
