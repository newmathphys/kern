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

/-! ### 6. ПРАВИЛА, КОТОРЫМИ ЗАКРЫТ `musl abs.c` (`trusted: 15 -> 0`)

Каждое правило, добавленное в `src/verifier/proof_check.zig` при доведении
`musl src/stdlib/abs.c` до `trusted: 0`, обязано иметь теорему здесь.
-/

/-- ФОРМА 1 (`antisymmetryZero`): антисимметричность порядка. Именно это
    правило закрыло `(rewrite (= P 0) (and (<= P 0) (>= P 0)))`. -/
theorem int_eq_zero_iff_le_ge (p : Int) : p = 0 ↔ (p ≤ 0 ∧ p ≥ 0) := by
  omega

/-- ФОРМА 2 (`eqTransferZero`): перенос слагаемого через равенство.
    `X = Y` ⟺ `X + (-1)·Y = 0`. -/
theorem int_eq_iff_sub_zero (x y : Int) : x = y ↔ x + (-1) * y = 0 := by
  omega

/-- `negAlternatives`: отрицание равенства над ℤ есть ДИЗЪЮНКЦИЯ двух строгих
    неравенств (именно так раскладывается `(not (= X Y))` в расщеплении). -/
theorem int_not_eq_iff_disj (x y : Int) :
    ¬(x = y) ↔ (x - y + 1 ≤ 0 ∨ y - x + 1 ≤ 0) := by
  omega

/-- ФОРМА 3 (`iteSwapEq`): переворот условия `ite` при перестановке ветвей.
    Левое условие `a < 0` есть отрицание правого `0 ≤ a` (над ℤ). -/
theorem ite_flip_cond_eq (a t e : Int) :
    (if a < 0 then t else e) = (if 0 ≤ a then e else t) := by
  by_cases h : a < 0
  · have h2 : ¬ (0 ≤ a) := by omega
    simp [h, h2]
  · have h2 : 0 ≤ a := by omega
    simp [h, h2]

/-- ФОРМА 4 (`orCongruence`): конгруэнция дизъюнкции по второму дизъюнкту.
    Один общий дизъюнкт `A` + эквивалентные вторые — эквивалентны. -/
theorem or_congruence_right (A L2 R2 : Prop) (h : L2 ↔ R2) : (A ∨ L2) ↔ (A ∨ R2) := by
  constructor
  · intro hx
    cases hx with
    | inl ha => exact Or.inl ha
    | inr hl => exact Or.inr (h.mp hl)
  · intro hx
    cases hx with
    | inl ha => exact Or.inl ha
    | inr hr => exact Or.inr (h.mpr hr)

/-- `andDeMorganEq`: закон де Моргана для `and` — тождество ПРОПОЗИЦИОНАЛЬНОЕ,
    поэтому чекер проверяет его СТРУКТУРНО, без решателя. -/
theorem and_de_morgan_iff (P Q : Prop) : (P ∧ Q) ↔ ¬(¬P ∨ ¬Q) := by
  constructor
  · intro h hx
    cases hx with
    | inl hn => exact hn h.1
    | inr hn => exact hn h.2
  · intro h
    refine ⟨?_, ?_⟩
    · exact Classical.byContradiction (fun hp => h (Or.inl hp))
    · exact Classical.byContradiction (fun hq => h (Or.inr hq))

/-- `verifyLemma`: разрядка гипотез (RAA). Из опровержения при допущении `H`
    следует `¬H` — ровно то, что проверяет `verifyLemma`. -/
theorem lemma_raa_discharge (H : Prop) (h_false : H → False) : ¬H :=
  h_false

/-- ЗВУЧНОСТЬ `checkFalseBySplitting` (расщепление по случаям, 2×2).
    Конъюнкция с двумя дизъюнкциями несовместна ТОГДА И ТОЛЬКО ТОГДА, когда
    несовместна КАЖДАЯ из четырёх ветвей выбора литералов. Это математическая
    основа того, что перебор комбинаций в `proof_check.zig` ЗВУЧИМ. -/
theorem case_split_2x2_unsat (U A1 A2 B1 B2 : Prop) :
    (U ∧ (A1 ∨ A2) ∧ (B1 ∨ B2) → False) ↔
    ((U ∧ A1 ∧ B1 → False) ∧ (U ∧ A1 ∧ B2 → False) ∧
     (U ∧ A2 ∧ B1 → False) ∧ (U ∧ A2 ∧ B2 → False)) := by
  constructor
  · intro h
    exact ⟨fun ⟨u, a, b⟩ => h ⟨u, Or.inl a, Or.inl b⟩,
           fun ⟨u, a, b⟩ => h ⟨u, Or.inl a, Or.inr b⟩,
           fun ⟨u, a, b⟩ => h ⟨u, Or.inr a, Or.inl b⟩,
           fun ⟨u, a, b⟩ => h ⟨u, Or.inr a, Or.inr b⟩⟩
  · intro h hx
    obtain ⟨u, ha, hb⟩ := hx
    cases ha with
    | inl ha1 =>
      cases hb with
      | inl hb1 => exact h.1 ⟨u, ha1, hb1⟩
      | inr hb2 => exact h.2.1 ⟨u, ha1, hb2⟩
    | inr ha2 =>
      cases hb with
      | inl hb1 => exact h.2.2.1 ⟨u, ha2, hb1⟩
      | inr hb2 => exact h.2.2.2 ⟨u, ha2, hb2⟩


/-! ### 7. ЭШЕЛОН 2, ПУНКТ 10: STALE EVIDENCE ЗАКРЫВАЕТ ВРАТА

Свидетельство привязано к отпечатку файла. Если отпечаток НЕ совпал с текущим,
положительный бит сбрасывается, поэтому допуск `e` равен нулю.
-/

/-- Квант Белнапа как пара битов `(p, n)`. -/
abbrev B4 := Bool × Bool

/-- Функция СВЕЖЕСТИ: `same = true` — отпечатки совпали, вердикт сохраняется;
    `same = false` — файл изменился, `p` сбрасывается (`n` сохраняется). -/
def freshBit (b : B4) (same : Bool) : B4 :=
  if same then b else (false, b.2)

/-- Допуск `e`: `1` только при `T = (true, false)`, иначе `0`. -/
def allowance (b : B4) : Nat :=
  if b.1 && !b.2 then 1 else 0

/-- ТЕОРЕМА: несвежее свидетельство ВСЕГДА даёт `e = 0` (без незакрытых целей). -/
theorem stale_evidence_closes_gate (b : B4) : allowance (freshBit b false) = 0 := by
  simp [freshBit, allowance]

/-- Контроль: свежее свидетельство `T` сохраняет допуск `1`. -/
theorem fresh_evidence_keeps_allowance : allowance (freshBit (true, false) true) = 1 := by
  simp [freshBit, allowance]

-- =============================================================================
-- ТЕОРЕМЫ ДЛЯ ПРАВИЛ, ДОБАВЛЕННЫХ В ЧЕКЕР В ХОДЕ ЭТАЛОНА IEEE-754 (v2.5).
-- ИЗМЕРЕНО: эти 6 правил (`cmpEq`, `linFormsEq`, `boolFormEq`, `substBoolSimplify`,
-- `isBoolTautology`, `comboUnsatBoolSplit`) были реализованы в `proof_check.zig`,
-- но НЕ имели формального обоснования. Пробел закрыт здесь.
-- =============================================================================

-- 1. `cmpEq`: канонизация сравнений. Z3 пишет одно сравнение двумя способами
--    (`(<= 0 x)` и `(>= x 0)`) — это ОДНО отношение.
theorem ge_iff_le_swap (a b : Int) : (a ≥ b) ↔ (b ≤ a) := by omega
theorem gt_iff_lt_swap (a b : Int) : (a > b) ↔ (b < a) := by omega

-- 2. `linFormsEq`: линейные формы. `X = Y` ⟺ `X − Y = 0`, и `p = 0` ⟺ `−p = 0`
--    (сравнение с точностью до общего знака).
theorem eq_zero_iff_neg_zero (p : Int) : (p = 0) ↔ (-p = 0) := by omega
theorem eq_iff_sub_eq_zero (x y : Int) : (x = y) ↔ (x - y = 0) := by omega

-- 3. `boolFormEq`: булевы формы. `(not X)` и `(X = false)` — одно и то же;
--    `X` и `(X = true)` — тоже. И `¬(a ≤ b)` ⟺ `b < a`.
theorem bool_not_iff_eq_false (x : Bool) : (x = false) ↔ ¬(x = true) := by
  cases x <;> simp
theorem bool_iff_eq_true (x : Bool) : (x = true) ↔ x := by
  cases x <;> simp
theorem not_le_iff_gt (a b : Int) : ¬(a ≤ b) ↔ (b < a) := by omega
theorem not_lt_iff_ge (a b : Int) : ¬(a < b) ↔ (b ≤ a) := by omega

-- 4. `substBoolSimplify`: тождественные упрощения булевых связок.
theorem not_true_bool : (!true) = false := rfl
theorem not_false_bool : (!false) = true := rfl
theorem or_false_left (x : Bool) : (false || x) = x := by cases x <;> rfl
theorem and_true_left (x : Bool) : (true && x) = x := by cases x <;> rfl

-- 5. `isBoolTautology`: ПОЛНОТА ПЕРЕБОРА. Если все подстановки дают `true`,
--    то формула тождественно истинна — то есть перебор по всем значениям
--    булевых переменных НЕ ТЕРЯЕТ контрпримеров.
theorem enumeration_complete_1 (f : Bool → Bool)
    (h1 : f true = true) (h2 : f false = true) : ∀ b, f b = true := by
  intro b; cases b <;> simp_all

theorem enumeration_complete_2 (f : Bool → Bool → Bool)
    (h1 : f true true = true) (h2 : f true false = true)
    (h3 : f false true = true) (h4 : f false false = true) :
    ∀ a b, f a b = true := by
  intro a b; cases a <;> cases b <;> simp_all

-- 6. `comboUnsatBoolSplit`: ГИБРИДНАЯ НЕСОВМЕСТНОСТЬ. Если при КАЖДОЙ
--    подстановке булевых переменных линейная часть несовместна, то и вся
--    комбинация несовместна (композиция перебора и линейной проверки).
theorem bool_split_unsat (lin : Prop) (P : Bool → Prop)
    (h1 : (lin ∧ P true) → False) (h2 : (lin ∧ P false) → False) :
    (lin ∧ (P true ∨ P false)) → False := by
  intro hx
  cases hx.2 with
  | inl hp => exact h1 ⟨hx.1, hp⟩
  | inr hp => exact h2 ⟨hx.1, hp⟩

-- Контроль: если подстановка ДАЁТ выполняющую точку, гибрид обязан вернуть
-- `.sat` (то есть НЕ признать комбинацию несовместной).
theorem bool_split_not_unsat (lin : Prop) (P : Bool → Prop)
    (h : lin ∧ P true) : ¬ ((lin ∧ (P true ∨ P false)) → False) := by
  intro hbad
  exact hbad ⟨h.1, Or.inl h.2⟩

-- 7. IEEE-754 ПОРЯДКОВАЯ МОДЕЛЬ С NaN (Пункт 22): структура `(is_nan, val)`.
--    ИЗМЕРЕНО: Z3 на QF_FP делал 1289 шагов bit-blast (213 доверенных), а на этой
--    модели — 56 шагов. Здесь доказывается, ЧТО именно даёт модель.
structure IeeeFloat where
  is_nan : Bool
  val : Int

def fp_zero : IeeeFloat := ⟨false, 0⟩

/-- Порядковое сравнение IEEE-754: ЛЮБОЕ сравнение с NaN — ЛОЖНО. -/
def fp_lt (x y : IeeeFloat) : Bool :=
  (!x.is_nan) && (!y.is_nan) && decide (x.val < y.val)

def fp_geq (x y : IeeeFloat) : Bool :=
  (!x.is_nan) && (!y.is_nan) && decide (x.val ≥ y.val)

/-- БАГОВАННЫЙ гард `if x < 0.0 then 0.0 else x` ПРОПУСКАЕТ NaN:
    при `x = NaN` условие `fp_lt NaN 0` ЛОЖНО, поэтому возвращается `NaN`,
    и постусловие `result ≥ 0.0` НАРУШЕНО. Это и есть ловушка NaN. -/
theorem clamp_nan_buggy_refuted :
    let x : IeeeFloat := ⟨true, 0⟩
    let res := if fp_lt x fp_zero then fp_zero else x
    fp_geq res fp_zero = false := by
  decide

/-- ЗАЩИЩЁННЫЙ гард (с проверкой `is_nan`) даёт `result ≥ 0.0` для ЛЮБОГО `x`. -/
theorem clamp_nan_safe_proven (x : IeeeFloat) :
    let res := if x.is_nan then fp_zero else if fp_lt x fp_zero then fp_zero else x
    fp_geq res fp_zero = true := by
  by_cases hx : x.is_nan = true
  · simp [fp_geq, fp_zero, hx]
  · have hxf : x.is_nan = false := by cases hx' : x.is_nan <;> simp_all
    by_cases hl : x.val < 0
    · simp [fp_lt, fp_geq, fp_zero, hxf, hl]
    · simp [fp_lt, fp_geq, fp_zero, hxf, hl]
      omega

-- =============================================================================
-- ТЕОРЕМЫ ДЛЯ ПРАВИЛ, ДОБАВЛЕННЫХ ПРИ РАБОТЕ НАД QF_S (Эшелон 4, Пункт 23).
-- ИЗМЕРЕНО: эти правила/обобщения были добавлены в `proof_check.zig` и обязаны
-- иметь формальное обоснование.
-- =============================================================================

-- `iff-true`: из доказанного `P` следует `(= P true)`; для Bool это тождество.
theorem iff_true_sound (b : Bool) : (b = true) ↔ b := by
  cases b <;> simp

-- `iff-false`: из доказанного `¬P` следует `(= P false)`.
theorem iff_false_sound (b : Bool) : (b = false) ↔ ¬(b = true) := by
  cases b <;> simp

-- ОБОБЩЁННЫЙ ЗАКОН ДЕ МОРГАНА (для `isNegPair`/`andDeMorganOne`):
-- знаки дизъюнктов ЛЮБЫЕ: `(¬a ∧ b) ↔ ¬(a ∨ ¬b)`.
theorem de_morgan_mixed (a b : Prop) : (¬a ∧ b) ↔ ¬(a ∨ ¬b) := by
  constructor
  · intro h hab
    cases hab with
    | inl ha => exact h.1 ha
    | inr hnb => exact hnb h.2
  · intro h
    refine ⟨?_, ?_⟩
    · intro ha
      exact h (Or.inl ha)
    · exact Classical.byContradiction (fun hnb => h (Or.inr hnb))

-- Двойное отрицание в контрарной паре: `(¬(¬a)) ↔ a` — основа `isNegPair`.
theorem double_neg_iff (a : Prop) : ¬¬a ↔ a := by
  constructor
  · intro h
    exact Classical.byContradiction (fun ha => h ha)
  · intro ha hna
    exact hna ha

end KernFarkas
