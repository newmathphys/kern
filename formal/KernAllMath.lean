-- =========================================================================
-- KERN FOUNDATION: FULL MATHEMATICAL SPECIFICATION & THEOREM REPOSITORY
-- Verified in Pure Lean 4 Core (Zero external dependencies, No 'sorry').
-- Источник: ai-studio-chat-2026-KERN10-10.md, раздел «Канонический базис».
-- =========================================================================
namespace KernMath

/-! ## РАЗДЕЛ 1: БИЛИНЕЙНАЯ РЕШЁТКА БЕЛНАПА-ДАННА (B₄)
Каждое утверждение кодируется парой (p, n) ∈ Bool × Bool:
  N = (false,false)  T = (true,false)  F = (false,true)  B = (true,true) -/

structure Belnap where
  p : Bool
  n : Bool
deriving DecidableEq, Repr

def N : Belnap := ⟨false, false⟩
def T : Belnap := ⟨true, false⟩
def F : Belnap := ⟨false, true⟩
def B : Belnap := ⟨true, true⟩

/-- Отрицание (порядок истинности): меняет местами p и n. -/
def notB (a : Belnap) : Belnap := ⟨a.n, a.p⟩
/-- Конъюнкция (порядок истинности). -/
def andT (a b : Belnap) : Belnap := ⟨a.p && b.p, a.n || b.n⟩
/-- Дизъюнкция (порядок истинности). -/
def orT (a b : Belnap) : Belnap := ⟨a.p || b.p, a.n && b.n⟩
/-- Слияние по порядку знаний. -/
def joinK (a b : Belnap) : Belnap := ⟨a.p || b.p, a.n || b.n⟩
/-- Пересечение по порядку знаний. -/
def meetK (a b : Belnap) : Belnap := ⟨a.p && b.p, a.n && b.n⟩

/-- Закон де Моргана для andT. -/
theorem deMorgan_andT (a b : Belnap) : notB (andT a b) = orT (notB a) (notB b) := by
  cases a with
  | mk ap an =>
    cases b with
    | mk bp bn =>
      simp [notB, andT, orT]

/-- Закон де Моргана для orT. -/
theorem deMorgan_orT (a b : Belnap) : notB (orT a b) = andT (notB a) (notB b) := by
  cases a with
  | mk ap an =>
    cases b with
    | mk bp bn =>
      simp [notB, andT, orT]

/-- Двойное отрицание — тождество. -/
theorem notB_involutive (a : Belnap) : notB (notB a) = a := by
  cases a with
  | mk ap an => simp [notB]

/-- Коммутативность слияния по знаниям. -/
theorem joinK_comm (a b : Belnap) : joinK a b = joinK b a := by
  cases a with
  | mk ap an =>
    cases b with
    | mk bp bn =>
      simp [joinK, Bool.or_comm]

/-- Ассоциативность слияния по знаниям. -/
theorem joinK_assoc (a b c : Belnap) : joinK (joinK a b) c = joinK a (joinK b c) := by
  cases a with
  | mk ap an =>
    cases b with
    | mk bp bn =>
      cases c with
      | mk cp cn =>
        simp [joinK, Bool.or_assoc]

/-- Идемпотентность слияния по знаниям. -/
theorem joinK_idem (a : Belnap) : joinK a a = a := by
  cases a with
  | mk ap an => simp [joinK, Bool.or_self]

/-- Дистрибутивность andT относительно orT (порядок истинности). -/
theorem andT_orT_distrib (a b c : Belnap) :
    andT a (orT b c) = orT (andT a b) (andT a c) := by
  cases a with
  | mk ap an =>
    cases b with
    | mk bp bn =>
      cases c with
      | mk cp cn =>
        simp only [andT, orT, Belnap.mk.injEq]
        exact ⟨Bool.and_or_distrib_left ap bp cp, Bool.or_and_distrib_left an bn cn⟩

/-- Изоляция конфликта: слияние независимых T и F даёт B. -/
theorem contradiction_isolation : joinK T F = B := rfl

/-! ## РАЗДЕЛ 2: АНТИ-ВАКУУМНЫЙ ШЛЮЗ -/

structure HoareContract (α β : Type) where
  pre : α → Prop
  post : α → β → Prop

/-- Конструктивная населённость: существует валидный вход. -/
def IsConstructive {α β : Type} (c : HoareContract α β) : Prop :=
  ∃ x : α, c.pre x

/-- ТЕОРЕМА: предусловие ≡ False не населено (вакуумный код отбрасывается). -/
theorem vacuous_precondition_impossible {α β : Type} (post : α → β → Prop) :
    ¬ IsConstructive (HoareContract.mk (fun _ => False) post) := by
  intro h
  obtain ⟨x, hx⟩ := h
  exact hx

/-! ## РАЗДЕЛ 3: ФУНДИРОВАННЫЙ ОБХОД И ТОПЛИВО (FUEL) -/

def FuelBoundedDfs (adj : Nat → List Nat) (eval : Nat → Belnap) : Nat → Nat → Belnap
  | 0, _ => B
  | fuel + 1, u =>
    let deps := adj u
    deps.foldl (fun acc v => andT acc (FuelBoundedDfs adj eval fuel v)) (eval u)

/-- ТЕОРЕМА: обход с топливом тотален — всегда возвращает значение. -/
theorem fuel_bounded_dfs_always_terminates
    (adj : Nat → List Nat) (eval : Nat → Belnap) (fuel u : Nat) :
    ∃ res : Belnap, FuelBoundedDfs adj eval fuel u = res := ⟨_, rfl⟩

end KernMath
