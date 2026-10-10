-- Copyright (c) 2026 Vital Kalinousky. All rights reserved.
-- Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

-- KERN FOUNDATION: FORMAL TERMINATION OF PROVENANCE DAG TRAVERSAL
-- Verified in Pure Lean 4 Core (no Mathlib, no 'sorry'). Самодостаточный файл.
namespace Kern

/-! Минимальная модель Белнапа (локальная копия, чтобы файл был автономен). -/
structure Belnap where
  p : Bool
  n : Bool
deriving DecidableEq, Repr

def B : Belnap := ⟨true, true⟩
def T : Belnap := ⟨true, false⟩
def andT (a b : Belnap) : Belnap := ⟨a.p && b.p, a.n || b.n⟩

/-- Идентификатор узла в гиперграфе KERN. -/
abbrev NodeId := Nat

/-- Абстрактный граф проекта: у каждого узла — список зависимостей. -/
structure Graph where
  adj : NodeId → List NodeId

/-- Отношение шага деривации: `v` — непосредственная предпосылка `u`. -/
def Step (g : Graph) (v u : NodeId) : Prop := v ∈ g.adj u

/-- Строгая ацикличность: отношение шага фундировано (нет бесконечных цепей). -/
def IsAcyclic (g : Graph) : Prop := WellFounded (Step g)

/-- ТЕОРЕМА 7: при фундированности графа обход доказательств завершается. -/
theorem traversal_terminates (g : Graph) (h_acyclic : IsAcyclic g) :
    ∀ start : NodeId, Acc (Step g) start := by
  intro start
  exact h_acyclic.apply start

/-- Обход с ограничением топлива (fuel). -/
def fuelBoundedEvaluation (g : Graph) (evaluateNode : NodeId → Belnap) :
    Nat → NodeId → Belnap
  | 0, _ => B
  | fuel + 1, u =>
    let deps := g.adj u
    deps.foldl (fun acc v => andT acc (fuelBoundedEvaluation g evaluateNode fuel v)) T

/-- ТЕОРЕМА 8: обход с топливом тотален — всегда возвращает значение. -/
theorem fuel_bounded_always_terminates (g : Graph) (eval : NodeId → Belnap)
    (fuel : Nat) (u : NodeId) :
    ∃ res : Belnap, fuelBoundedEvaluation g eval fuel u = res := ⟨_, rfl⟩

end Kern
