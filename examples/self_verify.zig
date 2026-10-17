//! САМОВЕРИФИКАЦИЯ KERN (`make self-verify`).
//!
//! Контракты стоят на формулах, которые РЕАЛЬНО используются в ядре:
//!   * остаток полезной нагрузки (`payloadSlice`/`getString` в L1/L2);
//!   * целочисленное отрицание сравнения для сертификата Фаркаша
//!     (`negLiteralAsLeZero` в `src/verifier/proof_check.zig`):
//!         ¬(l ≤ r)  ↔  (r - l + 1 ≤ 0);
//!   * клампинг смещения по границе пула строк.
//!
//! KERN проверяет САМ СЕБЯ: Z3 + собственный пруф-чекер, без внешних языков.

/// @kern:requires off >= 0 and off <= len and len >= 0
/// @kern:ensures  result == len - off and result >= 0
pub fn remaining(off: i64, len: i64) i64 {
    return len - off;
}

/// @kern:requires l > r and l - r <= 1000000
/// @kern:ensures  result <= 0
pub fn farkasNegLeZero(l: i64, r: i64) i64 {
    return r - l + 1;
}

/// @kern:requires off >= 0 and len >= 0
/// @kern:ensures  result <= len
pub fn clampToPool(off: i64, len: i64) i64 {
    if (off > len) return len;
    return off;
}
