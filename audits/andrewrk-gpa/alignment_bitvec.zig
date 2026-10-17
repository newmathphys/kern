// ТЕНЬ-КОНТРАКТ на РЕАЛЬНОЕ выражение из andrewrk/zig-general-purpose-allocator,
// gpda.zig:1065:  const aligned_addr = (addr & ~(alignment - 1));
// Здесь проверяется ЭКВИВАЛЕНТНОСТЬ битового трюка и арифметики (addr % alignment == 0)
// при предусловии «alignment — степень двойки». Битовые операции -> QF_BV.

/// @kern:requires alignment > 0 and (alignment & (alignment - 1)) == 0
/// @kern:ensures  result == 0
pub fn alignmentAgrees(addr: i32, alignment: i32) i32 {
    const bit_test = addr & ~(alignment - 1);
    const arithmetic = addr % alignment;
    if (bit_test == addr) return arithmetic;
    if (arithmetic == 0) return 1;
    return 0;
}

// КОНТРОЛЬ: классическая ошибка (alignment - 2 вместо alignment - 1) — обязан быть контрпример.
/// @kern:requires alignment > 0 and (alignment & (alignment - 1)) == 0
/// @kern:ensures  result == 0
pub fn alignmentAgreesBuggy(addr: i32, alignment: i32) i32 {
    const bit_test = addr & ~(alignment - 2);
    const arithmetic = addr % alignment;
    if (bit_test == addr) return arithmetic;
    if (arithmetic == 0) return 1;
    return 0;
}
