
// @kern:expect-violations — ДЕМО-ФИКСТУРА: часть контрактов НАМЕРЕННО нарушена,
// поэтому pre-commit её пропускает.
//! КРАЙНИЕ СЛУЧАИ ПОЛИГЛОТ-ПАРСЕРА KERN (проверяется вручную, не в CI).
//! Каждая функция — отдельная синтаксическая форма, которую обязан понять
//! экстрактор: тернарный оператор, else-ветвь, локальные константы,
//! беззнаковый тип (underflow), чистота.

/// @kern:requires a >= 0 and b >= 0
/// @kern:ensures  result >= a and result >= b
pub fn maxOf(a: i32, b: i32) i32 {
    return a > b ? a : b;   // тернарный оператор -> SMT (ite ...)
}

/// @kern:requires n >= 0
/// @kern:ensures  result >= 0
pub fn absOf(n: i64) i64 {
    if (n >= 0) return n; else return -n;   // else-ветвь
}

/// @kern:requires x >= 0 and x <= 1000000
/// @kern:ensures  result == 2 * x
pub fn doubleViaConst(x: i64) i64 {
    const k = 2;
    return x * k;   // локальная константа
}

/// @kern:requires x >= 0
/// @kern:ensures  result >= 0
pub fn u32NoUnderflow(x: u32, y: u32) u32 {
    return x - y;   // u32: при y > x результат уходит в минус -> underflow
}

/// @kern:requires d > 0
/// @kern:ensures  result >= 0
pub fn modBuiltin(n: i32, d: i32) i32 {
    return @mod(n, d);   // встроенная функция Zig -> SKIP с ЯЗЫКОВОЙ причиной (дефект #117)
}

// УЛУЧШЕНИЕ №15: битовые операции -> теория QF_BV (`_ BitVec 32`).
// Реальный приём из системного кода (andrewrk/zig-general-purpose-allocator):
// проверка выравнивания через `addr & ~(alignment - 1)`.
/// @kern:requires alignment > 0 and (alignment & (alignment - 1)) == 0
/// @kern:ensures  result == 0
pub fn bitAlignedAgrees(addr: i32, alignment: i32) i32 {
    const bit_test = addr & ~(alignment - 1);
    const arithmetic = addr % alignment;
    if (bit_test == addr) return arithmetic;
    if (arithmetic == 0) return 1;
    return 0;
}
