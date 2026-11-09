-- Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
--
-- МОСТ Lean <-> Zig: ТАБЛИЦА РЕШЁТКИ B₄ ИЗ САМОГО ОПРЕДЕЛЕНИЯ.
--
-- ЗАЧЕМ. Теоремы Lean 4 (`joinK_comm/assoc/idem`, `contradiction_isolation`,
-- `conflate_*`) доказывают ЗАКОНЫ про `Belnap`, но до этого файла ничто не
-- связывало это определение с кодом Zig: два независимых описания одной
-- алгебры. Для компонента с КОНЕЧНЫМ доменом связь закрывается ПОЛНОСТЬЮ:
--   * здесь таблица считается ОПРЕДЕЛЕНИЕМ Lean (не рукописью);
--   * `kernx belnap-table` считает ту же таблицу РЕАЛИЗАЦИЕЙ ЯДРА;
--   * `make lean-zig-bridge` сверяет их побайтово.
-- Совпадение на ВСЕХ 40 входах = равенство функций (домен исчерпан), а не
-- «сверка на нескольких примерах». Обратное расхождение — дефект КОДА.
--
-- ФОРМАТ (обязан совпадать с `src/next/main.zig`):
--   joinK|<a>|<b>|<r>     16 строк (4×4)
--   meetK|<a>|<b>|<r>     16 строк
--   notB|<a>|<r>           4 строки
--   conflate|<a>|<r>       4 строки
-- Символы: N T F B (порядок фиксирован: [N, T, F, B]).

structure Belnap where
  p : Bool
  n : Bool
deriving DecidableEq, Repr

def N : Belnap := ⟨false, false⟩
def T : Belnap := ⟨true, false⟩
def F : Belnap := ⟨false, true⟩
def B : Belnap := ⟨true, true⟩

def sym (v : Belnap) : String :=
  if v.p && v.n then "B"
  else if v.p then "T"
  else if v.n then "F"
  else "N"

/-- Слияние по порядку знаний (ровно то, что считает `Eq2.joinK`). -/
def joinK (a b : Belnap) : Belnap := ⟨a.p || b.p, a.n || b.n⟩
/-- Пересечение по порядку знаний (`Eq2.meetK`). -/
def meetK (a b : Belnap) : Belnap := ⟨a.p && b.p, a.n && b.n⟩
/-- Отрицание Белнапа: меняет местами p и n (`eq2.notB`). -/
def notB (a : Belnap) : Belnap := ⟨a.n, a.p⟩
/-- Конфляция `~`: (p,n) -> (!n,!p) (`eq2.conflate`). -/
def conflate (a : Belnap) : Belnap := ⟨!a.n, !a.p⟩

def all : List Belnap := [N, T, F, B]

def main : IO Unit := do
  for a in all do
    for b in all do
      IO.println s!"joinK|{sym a}|{sym b}|{sym (joinK a b)}"
  for a in all do
    for b in all do
      IO.println s!"meetK|{sym a}|{sym b}|{sym (meetK a b)}"
  for a in all do
    IO.println s!"notB|{sym a}|{sym (notB a)}"
  for a in all do
    IO.println s!"conflate|{sym a}|{sym (conflate a)}"
