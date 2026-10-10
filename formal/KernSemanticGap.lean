-- Copyright (c) 2026 Vital Kalinousky. All rights reserved.
-- Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

-- KERN: ЭШЕЛОН 4 — СЕМАНТИЧЕСКИЙ РАЗРЫВ (Lean-спецификация vs Zig-рантайм)
--
-- САМАЯ ОПАСНАЯ ДЫРА верификаторов: доказать свойство в БЕСКОНЕЧНОЙ
-- арифметике (ℤ), а исполнять в ОГРАНИЧЕННОЙ (i32/i64). Тогда «доказано»
-- не означает «верно в рантайме».
--
-- Здесь формально доказывается СУЩЕСТВОВАНИЕ этого разрыва и корректность
-- защитного правила KERN (guard по границе типа).

import Mathlib

namespace KernSemanticGap

/-- Домен рантайма: 32-битное знаковое целое. -/
def In32 (x : ℤ) : Prop := -2147483648 ≤ x ∧ x ≤ 2147483647

/-- В ℤ свойство «x + 1 > x» истинно для ЛЮБОГО x. -/
theorem unbounded_succ_gt (x : ℤ) : x + 1 > x := by omega

/-- РАЗРЫВ: существует значение в домене i32, для которого x + 1 ВЫХОДИТ из домена. -/
theorem int32_gap : ∃ x : ℤ, In32 x ∧ ¬ In32 (x + 1) := by
  refine ⟨2147483647, ?_, ?_⟩
  · unfold In32; omega
  · unfold In32; omega

/-- Следствие: свойство НЕЛЬЗЯ переносить с ℤ на i32 «оптом». -/
theorem no_blanket_transfer : ¬ (∀ x : ℤ, In32 x → In32 (x + 1)) := by
  intro h
  obtain ⟨x, hx, hnx⟩ := int32_gap
  exact hnx (h x hx)

/-- Правило KERN: контракт ОБЯЗАН ограничивать вход доменом рантайма.
    Без этого доказательство в ℤ недействительно для Zig i32. -/
theorem spec_must_bound (x : ℤ) (hx : x = 2147483647) : ¬ In32 (x + 1) := by
  subst hx; unfold In32; omega

/-- Защитное правило KERN: guard по границе СОХРАНЯЕТ принадлежность домену.
    Это и есть «безопасная арифметика» (std.math.add в Zig). -/
theorem guarded_add_stays_in32 (x : ℤ) (h : In32 x) :
    In32 (if x < 2147483647 then x + 1 else x) := by
  unfold In32 at *
  split
  · omega
  · omega

/-- Аналогичный разрыв для нижней границы (проверка на вычитание). -/
theorem int32_gap_lower : ∃ x : ℤ, In32 x ∧ ¬ In32 (x - 1) := by
  refine ⟨-2147483648, ?_, ?_⟩
  · unfold In32; omega
  · unfold In32; omega

/-- Позитивный перенос: если вход СТРОГО внутри домена (без границ),
    то x + 1 остаётся в домене. Показывает, что разрыв — ровно на границах. -/
theorem safe_inside_only (x : ℤ) (h : -2147483647 ≤ x ∧ x ≤ 2147483646) :
    In32 (x + 1) := by
  unfold In32; omega

/-- Итог: множество «безопасных» входов НЕ совпадает с доменом —
    границы требуют явной обработки. -/
theorem boundary_requires_guard :
    ∃ x : ℤ, In32 x ∧ ¬ In32 (x + 1) ∧ In32 (if x < 2147483647 then x + 1 else x) := by
  refine ⟨2147483647, ?_, ?_, ?_⟩
  · unfold In32; omega
  · unfold In32; omega
  · have := guarded_add_stays_in32 2147483647 (by unfold In32; omega)
    simpa using this

end KernSemanticGap
