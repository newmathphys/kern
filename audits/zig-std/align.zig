// ТЕНЬ-КОНТРАКТЫ на РЕАЛЬНЫЙ код стандартной библиотеки Zig.
// Источник: ziglang/zig, lib/std/mem.zig
//   :4826  pub fn alignBackward(...) T { return addr & ~(alignment - 1); }
//   :4693  pub fn alignForward(...) T {
//              assert(isValidAlignGeneric(T, alignment));
//              return alignBackward(T, addr + (alignment - 1), alignment);
//          }
//   Докстрока :4692 — «Asserts that rounding up the address does not cause integer overflow».
//
// Один и тот же приём `addr & ~(alignment - 1)` лежит и в Zig std, и в аллокаторе
// andrewrk/zig-general-purpose-allocator (см. audits/andrewrk-gpa) — здесь он берётся
// ИЗ СТД, чтобы привязка была к языковой библиотеке.

// СВОЙСТВО: для выравнивания-степени-двойки `addr & ~(alignment - 1)` равно `addr - addr % alignment`.
// Функция возвращает ИНДИКАТОР (0 = совпало), поэтому и контракт про индикатор:
// `result == 0` означает, что равенство выполняется при ЛЮБЫХ допустимых входах.
// Домен — БЕЗзнаковый (u32): при знаковых значениях `%` в BV-теории усекающий
// (`bvsrem`), и равенство формулировалось бы иначе — граница домена указана явно.
/// @kern:requires alignment > 0 and (alignment & (alignment - 1)) == 0
/// @kern:ensures  result == 0
pub fn alignBackwardEqMod(addr: u32, alignment: u32) u32 {
    const masked = addr & ~(alignment - 1);
    const by_mod = addr - addr % alignment;
    if (masked == by_mod) return 0;
    return 1;
}

// КОНТРОЛЬ (мутация): классическая off-by-one (`alignment - 2` вместо `alignment - 1`).
/// @kern:requires alignment > 0 and (alignment & (alignment - 1)) == 0
/// @kern:ensures  result == 0
pub fn alignBackwardBuggy(addr: u32, alignment: u32) u32 {
    const masked = addr & ~(alignment - 2);
    const by_mod = addr - addr % alignment;
    if (masked == by_mod) return 0;
    return 1;
}

// ГРАНИЦА ПЕРЕПОЛНЕНИЯ из `alignForward`: `addr + (alignment - 1)` при u32.
// Докстрока Zig честно говорит, что переполнение обязан исключить ВЫЗЫВАЮЩИЙ.
// KERN показывает ТОЧНЫЕ входы, где это условие нарушается (не «баг Zig», а граница
// применимости, о которой предупреждает сама документация).
/// @kern:requires addr >= 0 and alignment > 0
/// @kern:ensures  result >= addr
pub fn alignForwardAdd(addr: u32, alignment: u32) u32 {
    return addr + (alignment - 1);
}
