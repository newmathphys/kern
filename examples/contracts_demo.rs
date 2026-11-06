// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md

// @kern:expect-violations — ДЕМО-ФИКСТУРА: часть контрактов НАМЕРЕННО нарушена,
// поэтому pre-commit её пропускает.
//! Демонстрация контрактов KERN для языка RUST (мультиязычный экстрактор).
//!
//! Аннотации — `/// @kern:requires` / `/// @kern:ensures`.
//! `i32` даёт машинные границы: KERN проверит переполнение.

/// @kern:requires amount >= 0 and balance >= amount
/// @kern:ensures  result == balance - amount
pub fn withdraw(balance: i32, amount: i32) -> i32 {
    return balance - amount;
}

/// @kern:requires balance >= 0 and amount >= 0
/// @kern:ensures  result >= 0 and result <= balance
pub fn withdraw_guard(balance: i32, amount: i32) -> i32 {
    if amount > balance { return 0; }
    return balance - amount;
}

/// @kern:requires balance >= 0 and balance <= 1000
/// @kern:ensures  result >= 0
pub fn half(balance: i32) -> i32 {
    return balance / 2;
}

/// @kern:requires x >= 0
/// @kern:ensures  result >= 0
pub fn double_it(x: i32) -> i32 {
    return x + x;   // при x > 2^30 ПЕРЕПОЛНЕНИЕ i32 -> KERN обязан отвергнуть
}
