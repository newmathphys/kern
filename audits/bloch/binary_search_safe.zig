// Безопасная формула Блоха в ТЕОРИИ Int (без @kern:bitvec32):
// промежуточная сумма high - low не может переполнить границы контракта.

/// @kern:requires low >= 0 and high >= 0 and low <= high
/// @kern:ensures result >= 0 and result >= low and result <= high
pub fn mid_safe_int(low: i32, high: i32) i32 {
    return low + (high - low) / 2;
}
