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
