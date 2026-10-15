-- Copyright (c) 2026 Vital Kalinousky. All rights reserved.
-- Licensed under the PolyForm Noncommercial License 1.0.0.
-- Commercial use requires a license from the copyright holder. See LICENSE.

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

/-- ТЕОРЕМА 7: при фундированности графа обход доказательств завершается.
    ФОРМА: `WellFounded r` по определению есть `∀ a, Acc r a`, поэтому теорема
    верна, но она — РАЗВОРОТ ОПРЕДЕЛЕНИЯ, а не самостоятельный результат.
    Оставлена как явная фиксация связи «фундированность ⇒ доступность узла»;
    содержательная гарантия завершения даётся теоремой 9 (граница топлива). -/
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

/-- Множество узлов, достижимых из `u` за НЕ БОЛЕЕ чем `n` шагов. -/
def Within (adj : NodeId → List NodeId) : Nat → NodeId → NodeId → Prop
  | 0, u, v => v = u
  | n + 1, u, v => v = u ∨ ∃ w, w ∈ adj u ∧ Within adj n w v

/-- Шаг достижимости монотонен по вложению: если `w` достижим из `v` за `n`
    шагов и `v` — непосредственная зависимость `u`, то `w` достижим из `u`
    за `n+1` шаг. -/
theorem Within.step {adj : NodeId → List NodeId} {n v w u : NodeId}
    (hw : Within adj n v w) (hv : v ∈ adj u) : Within adj (n + 1) u w :=
  Or.inr ⟨v, hv, hw⟩

/-- Вспомогательная лемма: если две свёртки совпадают поэлементно, то и
    результаты `foldl` совпадают (при одинаковом начальном аккумуляторе).
    В Lean Core нет `List.foldl_congr`, поэтому доказываем сами. -/
theorem foldl_congr_list {α β : Type} (f g : β → α → β) :
    ∀ (l : List α) (acc : β), (∀ x ∈ l, ∀ a, f a x = g a x) →
      l.foldl f acc = l.foldl g acc
  | [], _, _ => rfl
  | x :: xs, acc, h => by
    simp only [List.foldl_cons]
    rw [h x (by simp) acc]
    exact foldl_congr_list f g xs (g acc x) (fun y hy a => h y (by simp [hy]) a)

/-- ТЕОРЕМА 8 (СОДЕРЖАТЕЛЬНАЯ): ТОПЛИВО ОГРАНИЧИВАЕТ ЗОНУ ВЛИЯНИЯ.

    Если два графа совпадают на ВСЕХ узлах, достижимых из `u` за ≤ `fuel`
    шагов, то fuel-bounded обход даёт ОДИНАКОВЫЙ результат.

    Это и есть настоящая гарантия предсказуемости: работа с топливом `f`
    зависит ТОЛЬКО от подграфа высоты `f` — части графа за пределами зоны
    влияния на результат не влияют. Доказательство — индукция по топливу.

    (Прежняя формулировка `∃ res, f = res` была ТАВТОЛОГИЕЙ: в Lean все
    функции тотальны, и такая «теорема» верна для ЛЮБОЙ функции.) -/
theorem fuel_bounds_influence
    (adj adj' : NodeId → List NodeId) (eval : NodeId → Belnap) (u fuel : NodeId)
    (h : ∀ v, Within adj fuel u v → adj v = adj' v) :
    fuelBoundedEvaluation ⟨adj⟩ eval fuel u = fuelBoundedEvaluation ⟨adj'⟩ eval fuel u := by
  induction fuel generalizing u with
  | zero => rfl
  | succ n ih =>
    simp only [fuelBoundedEvaluation]
    -- Зависимости узла u совпадают: u достижим из себя за 0 шагов.
    have hu : adj u = adj' u := h u (Or.inl rfl)
    rw [hu]
    -- Поэлементное совпадение свёрток на глубине n.
    apply foldl_congr_list
    intro v hv a
    have hv' : v ∈ adj u := by rw [hu]; exact hv
    rw [ih v (fun w hw => h w (Within.step hw hv'))]

end Kern
