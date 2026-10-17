-- Copyright (c) 2026 Vital Kalinousky. All rights reserved.
-- Licensed under the PolyForm Noncommercial License 1.0.0.
-- Commercial use requires a license from the copyright holder. See LICENSE.

-- KERN FARKAS SOUNDNESS: формальные инварианты пруф-чекера
-- Verified in Pure Lean 4 Core (no Mathlib, no 'sorry'). Самодостаточный файл.
--
-- ЗАЧЕМ. До этого файла 32 теоремы в `formal/` говорили только о решётке
-- Белнапа B4 и топливе обхода — а САМ ПРУФ-ЧЕКЕР (`src/verifier/proof_check.zig`)
-- не был формализован. Здесь доказаны ровно те факты, на которых он стоит:
--   * целочисленное отрицание сравнения (`negLiteralAsLeZero`);
--   * звучность сертификата Фаркаша для 2 и 3 неравенств;
--   * звучность ТРЁХЗНАЧНОГО вердикта (`verified | bad | unverifiable`);
--   * математическое обоснование детектора ВАКУУМНЫХ предусловий;
--   * нейтральность «пропуска» (`N`) при слиянии вердиктов Белнапа.
import Init

namespace KernFarkas

/-! ### 1. Целочисленное отрицание сравнения -/

/-- Формула из `negLiteralAsLeZero` (`src/verifier/proof_check.zig`):
    отрицание `l ≤ r` равносильно `r - l + 1 ≤ 0` над ℤ.
    На ней ломались наивные чекеры, сравнивавшие формы СТРУКТУРНО. -/
theorem int_not_le_iff (l r : Int) : ¬(l ≤ r) ↔ r - l + 1 ≤ 0 := by
  omega

/-- Следствие: если `l ≤ r`, то `r - l + 1 > 0` (обратная форма). -/
theorem int_le_implies_pos (l r : Int) (h : l ≤ r) : 0 < r - l + 1 := by
  omega

/-! ### 2. Звучность сертификата Фаркаша -/

/-- Неотрицательная комбинация неположительных величин неположительна.
    Это ядро сертификата Фаркаша: веса `w ≥ 0`, клаузы `L ≤ 0`. -/
theorem farkas_combination_nonpos (w1 w2 L1 L2 : Int)
    (h1 : 0 ≤ w1) (h2 : 0 ≤ w2) (hl1 : L1 ≤ 0) (hl2 : L2 ≤ 0) :
    w1 * L1 + w2 * L2 ≤ 0 := by
  have a : w1 * L1 ≤ 0 := Int.mul_nonpos_of_nonneg_of_nonpos h1 hl1
  have b : w2 * L2 ≤ 0 := Int.mul_nonpos_of_nonneg_of_nonpos h2 hl2
  omega

/-- ЗВУЧНОСТЬ ФАРКАША (2 неравенства): если комбинация с неотрицательными
    весами равна ПОЛОЖИТЕЛЬНОЙ константе `c > 0`, система неразрешима.
    Именно так пруф-чекер отвергает `unsat` с поддельным сертификатом. -/
theorem farkas_2_sound (w1 w2 L1 L2 c : Int)
    (h1 : 0 ≤ w1) (h2 : 0 ≤ w2) (hl1 : L1 ≤ 0) (hl2 : L2 ≤ 0)
    (hc : 0 < c) (hcomb : w1 * L1 + w2 * L2 = c) : False := by
  have hle : w1 * L1 + w2 * L2 ≤ 0 :=
    farkas_combination_nonpos w1 w2 L1 L2 h1 h2 hl1 hl2
  omega

/-- ЗВУЧНОСТЬ ФАРКАША (3 неравенства) — расширение до реальных выводов
    `arith`/`th-lemma`, где весов обычно три и больше. -/
theorem farkas_3_sound (w1 w2 w3 L1 L2 L3 c : Int)
    (h1 : 0 ≤ w1) (h2 : 0 ≤ w2) (h3 : 0 ≤ w3)
    (hl1 : L1 ≤ 0) (hl2 : L2 ≤ 0) (hl3 : L3 ≤ 0)
    (hc : 0 < c) (hcomb : w1 * L1 + w2 * L2 + w3 * L3 = c) : False := by
  have a : w1 * L1 ≤ 0 := Int.mul_nonpos_of_nonneg_of_nonpos h1 hl1
  have b : w2 * L2 ≤ 0 := Int.mul_nonpos_of_nonneg_of_nonpos h2 hl2
  have d : w3 * L3 ≤ 0 := Int.mul_nonpos_of_nonneg_of_nonpos h3 hl3
  omega

/-! ### 3. Звучность ТРЁХЗНАЧНОГО вердикта пруф-чекера -/

/-- Трёхзначный результат проверки шага вывода. -/
inductive CheckResult where
  | verified
  | bad
  | unverifiable
  deriving DecidableEq, Repr

/-- Врата открываются ТОЛЬКО при `verified`. -/
def admit (r : CheckResult) : Bool := r == CheckResult.verified

/-- ЗВУЧНОСТЬ: если врата открылись, шаг был именно `verified`.
    Ни `bad`, ни `unverifiable` не могут быть приняты за доказанный шаг. -/
theorem three_valued_check_sound (r : CheckResult) (h : admit r = true) :
    r = CheckResult.verified := by
  cases r <;> simp [admit] at h ⊢

/-- Ни один «плохой» шаг не открывает врата (отдельная формулировка). -/
theorem bad_never_admitted : admit CheckResult.bad = false := rfl

/-! ### 4. Обоснование детектора ВАКУУМНЫХ предусловий -/

/-- ВАКУУМНОЕ ПРЕДУСЛОВИЕ (`false => anything`): если предусловие `P`
    невыполнимо ни на одном входе, то импликация `P x → Q x` истинна для
    ЛЮБОГО `Q` — даже для полностью сломанного тела.
    Это математическое обоснование того, почему KERN обязан проверять
    ВЫПОЛНИМОСТЬ `requires` отдельно. -/
theorem vacuous_requires_unsound {α : Type} (P Q : α → Prop)
    (h : ∀ x, ¬ P x) : ∀ x, P x → Q x := by
  intro x hx
  exact absurd hx (h x)

/-- Обратная сторона: если предусловие выполнимо, вакуумности нет. -/
theorem nonvacuous_has_witness {α : Type} (P : α → Prop) (x : α) (hx : P x) :
    ∃ y, P y := ⟨x, hx⟩

/-! ### 5. Нейтральность ПРОПУСКА при слиянии вердиктов Белнапа -/

/-- Минимальная модель Белнапа (локальная копия, чтобы файл был автономен). -/
structure Belnap where
  p : Bool
  n : Bool
  deriving DecidableEq, Repr

/-- `N = (0,0)` — нет свидетельств (в CLI это код возврата 2, дефект #96). -/
def Belnap.N : Belnap := ⟨false, false⟩

/-- JOIN_K: слияние свидетельств. Конфликт `T ⊔ F` даёт `B = (1,1)`. -/
def joinK (a b : Belnap) : Belnap := ⟨a.p || b.p, a.n || b.n⟩

/-- ПРОПУСК НЕЙТРАЛЕН: `JOIN_K(x, N) = x`. Пропущенное свидетельство не
    портит ни `T`, ни `F`, ни `B` — поэтому «SKIP» честно не меняет вердикт. -/
theorem skip_preserves_belnap_join (x : Belnap) : joinK x Belnap.N = x := by
  cases x with
  | mk p n => cases p <;> cases n <;> rfl

end KernFarkas
