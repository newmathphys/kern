// ТЕНЬ-КОНТРАКТ на РЕАЛЬНУЮ функцию стандартной библиотеки Rust:
//   rust-lang/rust, library/core/src/num/mod.rs:158 (macro `midpoint`, unsigned)
//   тело:  ((self ^ rhs) >> 1) + (self & rhs)
//   комментарий из исходника: «branchless algorithm from Hacker's Delight to
//   compute `(a + b) / 2` without overflowing: `((a ^ b) >> 1) + (a & b)`».
//
// ЗАЧЕМ: это ровно ответ на знаменитый баг Джошуа Блоха в бинарном поиске
// (`(low + high) / 2` переполняется). Доказываем, что безветочная формула
// равна истинному среднему (QF_BV: ^ & >> + на (_ BitVec 32)).
//
// ПРЕДУСЛОВИЕ (честно): обе стороны ограничены 31 битом, поэтому `a + b` НЕ
// переполняется и `(a + b) / 2` — истинное среднее. Проверяется именно это.

/// @kern:requires a <= 2147483647 and b <= 2147483647
/// @kern:ensures  result == (a + b) / 2
pub fn midpoint(a: u32, b: u32) u32 {
    return ((a ^ b) >> 1) + (a & b);
}

// КОНТРОЛЬ (мутация): сдвиг на 2 вместо 1 — «почти та же формула», но НЕ
// среднее. Тот же контракт и то же предусловие обязаны её опровергнуть.
/// @kern:requires a <= 2147483647 and b <= 2147483647
/// @kern:ensures  result == (a + b) / 2
pub fn midpointMutated(a: u32, b: u32) u32 {
    return ((a ^ b) >> 2) + (a & b);
}
