// DeepJIT — include/deep_jit/backend/ascend/kernel.hpp, `align_kernel_arg`
// (строки 34-36) и `kernel_arg_alignment` (строка 31):
//     template <typename T>
//     inline constexpr size_t kernel_arg_alignment = alignof(T) < 4 ? 4 : alignof(T);
//     template <typename T>
//     constexpr size_t align_kernel_arg(const size_t offset) {
//         return (offset + kernel_arg_alignment<T> - 1) & ~(kernel_arg_alignment<T> - 1);
//     }
//
// ПОЧЕМУ ЭТО НАДО ДОКАЗЫВАТЬ. Это ТА ЖЕ формула, что баг `alignForward` в
// `zig std`: `offset + (align - 1)` в беззнаковом `size_t` ЗАВОРАЧИВАЕТСЯ,
// когда `offset` близок к максимуму типа. Тогда `& ~(align-1)` даёт адрес
// МЕНЬШЕ исходного — выравнивание не вверх, а вниз через ноль. Для смещений
// аргументов ядра (мегабайты) это недостижимо, но контракт фиксирует ГРАНИЦУ
// честно: без верхней границы на `offset` инвариант `result >= offset` ЛОЖЕН.
//
// Парный контроль (buggy/guarded) — как в `audits/cwe_twins` и `audits/zig-std`.
//
// ГРАНИЦА ПРУФ-ЧЕКЕРА (ИЗМЕРЕНО, честный fail-closed). Защищённая форма НЕ
// получает `PROVEN` в таблице: Z3 формулу ДОКАЗЫВАЕТ, но чекер её не покрывает
// и печатает `SKIP — посылки не привязаны к контракту (premises_unbound)`.
// Проверено на трёх равносильных записях (символьное `align`; константное
// `align = 4` с границей `offset <= 4294967292`; с добавочным `result - offset
// <= 3`) — причина одна и та же, то есть это предел привязки БЕЗЗНАКОВЫХ
// посылок в чекере, а не ошибка перевода. Утверждение при этом НЕ потеряно:
// его несут рукописные сертификаты `align_guard.smt2` -> `PROVEN`
// (`trusted 1`) и `align_unguarded.smt2` -> `REFUTED` (контрпример
// `offset = 4294967293`), которые `make audits` проверяет отдельным разделом.
// Подделывать `PROVEN` ради зелёной строки было бы хуже, чем назвать границу.

// @kern:bitvec32
// @kern:requires align >= 4
// @kern:ensures result >= offset
unsigned int deepjit_align_unguarded(unsigned int offset, unsigned int align) {
    return (offset + align - 1) & ~(align - 1);
}

// @kern:bitvec32
// @kern:requires align >= 4 and offset <= 4294967295 - (align - 1)
// @kern:ensures result >= offset
unsigned int deepjit_align_guarded(unsigned int offset, unsigned int align) {
    return (offset + align - 1) & ~(align - 1);
}
