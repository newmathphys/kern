//! Демонстрация контрактов KERN для языка ZIG (мультиязычный экстрактор).
//!
//! Аннотации — те же `@kern:requires` / `@kern:ensures`, но в `///`-комментариях.
//! Типы параметров (`i32`) дают МАШИННЫЕ границы: KERN автоматически проверяет
//! отсутствие переполнения 32-битного целого.

/// @kern:requires amount >= 0 and balance >= amount
/// @kern:ensures  result == balance - amount and result <= balance
pub fn withdraw(balance: i32, amount: i32) i32 {
    return balance - amount;
}

/// @kern:requires amount > 10 and amount < 5
/// @kern:ensures  result == balance - amount
pub fn withdrawVacuous(balance: i32, amount: i32) i32 {
    return balance + amount;
}

/// @kern:requires balance >= 0 and amount >= 0
/// @kern:ensures  result >= 0 and result <= balance
pub fn withdrawGuard(balance: i32, amount: i32) i32 {
    if (amount > balance) return 0;
    return balance - amount;
}
