// ТЕНЬ-КОНТРАКТ на РЕАЛЬНУЮ функцию из TigerBeetle (финансовая БД):
//   src/stdx/stdx.zig:67  pub inline fn div_ceil(numerator, denominator)
//   тело (строки 83-85):
//     assert(denominator > 0);
//     if (numerator == 0) return 0;
//     return @divFloor(numerator - 1, denominator) + 1;
//
// МОДЕЛИРОВАНИЕ (честно): `@divFloor` — встроенная функция Zig, вне подмножества
// экстрактора, поэтому здесь она записана как `/` (SMT `div` для Int — деление
// с округлением вниз). Для НЕотрицательного числителя и положительного знаменателя
// (это и даёт `requires`) `@divFloor` и `/` совпадают, поэтому модель точна.

/// @kern:requires numerator >= 0 and denominator > 0
/// @kern:ensures  result == (numerator + denominator - 1) / denominator
pub fn divCeil(numerator: i32, denominator: i32) i32 {
    if (numerator == 0) return 0;
    return (numerator - 1) / denominator + 1;
}

// КОНТРОЛЬ (мутация): забыт вычет единицы перед делением -> n/d + 1.
/// @kern:requires numerator >= 0 and denominator > 0
/// @kern:ensures  result == (numerator + denominator - 1) / denominator
pub fn divCeilBuggy(numerator: i32, denominator: i32) i32 {
    if (numerator == 0) return 0;
    return numerator / denominator + 1;
}
