// @kern:bitvec32
// Классический баг Джошуа Блоха (2006): переполнение в бинарном поиске.
// mid = (low + high) / 2 переполняет i32 при low + high >= 2**31.

/// @kern:requires low >= 0 and high >= 0 and low <= 2147483647 and high <= 2147483647
/// @kern:ensures result >= 0 and result <= 2147483647
pub fn mid_buggy(low: i32, high: i32) i32 {
    return (low + high) / 2;
}

/// @kern:requires low >= 0 and high >= 0 and low <= high and high <= 2147483647
/// @kern:ensures result >= 0 and result <= 2147483647
pub fn mid_safe(low: i32, high: i32) i32 {
    return low + (high - low) / 2;
}
