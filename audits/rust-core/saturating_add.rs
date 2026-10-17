// ТЕНЬ-КОНТРАКТ на СЕМАНТИКУ реальной функции стандартной библиотеки Rust:
//   rust-lang/rust, library/core/src/num/mod.rs (macro `int_impl!`, `saturating_add`)
//   документация: «Saturating integer addition. Computes `self + rhs`, saturating
//   at the numeric bounds instead of overflowing»:
//       assert_eq!(100i32.saturating_add(1), 101);
//       assert_eq!(i32::MAX.saturating_add(1), i32::MAX);
//
// ЗАЧЕМ: насыщающее сложение — стандартный приём ПРОТИВ переполнения, и его
// инвариант («при неотрицательном приращении результат не меньше входа») —
// ровно то, что ломается, если защитный гард убран.
//
// ТЕОРИЯ: QF_LIA (Int) — арифметика линейная, поэтому вывод Z3 покрывается
// пруф-чекером целиком (`[PROOF VERIFIED]`, holes: 0).
//
// ТРАНСКРИПЦИЯ (честно): в std реализация идёт через `checked_add` + `match`;
// здесь та же СЕМАНТИКА записана в поддерживаемом подмножестве (if/else).

/// @kern:requires rhs >= 0
/// @kern:ensures  result >= a
pub fn saturatingAdd(a: i32, rhs: i32) -> i32 {
    if (a > 2147483647 - rhs) return 2147483647; else return a + rhs;
}

/* КОНТРОЛЬ (мутация): защитный гард убран — обычное сложение переполняется, и
 * «насыщающее» сложение начинает УМЕНЬШАТЬ результат. */
/// @kern:requires rhs >= 0
/// @kern:ensures  result >= a
pub fn saturatingAddBuggy(a: i32, rhs: i32) -> i32 {
    return a + rhs;
}
