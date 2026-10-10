// Корень модуля для прогона ВСЕХ тестов ядра.
//
// ЗАЧЕМ: документированная команда `zig test src/tests/exhaustive_suite.zig`
// НЕ РАБОТАЕТ — корнем модуля становится `src/tests/`, и импорты `../core/...`
// отвергаются как выход за пределы модуля. Обёртка в `src/` делает корнем `src/`.
//
// Проверено: без этого файла тесты Admission Gate и сьюта НЕ ЗАПУСКАЮТСЯ.
test {
    _ = @import("core/eq2.zig");
    _ = @import("core/object_entry.zig");
    _ = @import("core/kimg_reader.zig");
    _ = @import("core/kernfs_router.zig");
    _ = @import("verifier/admission_gate.zig");
    _ = @import("tests/exhaustive_suite.zig");
}
