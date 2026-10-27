// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

// Корень модуля для прогона ВСЕХ тестов ядра.
//
// ЗАЧЕМ: документированная команда `zig test src/tests/exhaustive_suite.zig`
// НЕ РАБОТАЕТ — корнем модуля становится `src/tests/`, и импорты `../core/...`
// отвергаются как выход за пределы модуля. Обёртка в `src/` делает корнем `src/`.
test {
    _ = @import("core/eq2.zig");
    _ = @import("core/hash_algo.zig");
    _ = @import("core/codec.zig");
    _ = @import("core/blake3_simd8.zig");
    _ = @import("core/object_entry.zig");
    _ = @import("core/kimg_reader.zig");
    _ = @import("core/kernfs_router.zig");
    _ = @import("core/kimg_writer.zig");
    _ = @import("core/mmap_guard.zig");
    _ = @import("attest.zig");
    _ = @import("owner.zig");
    _ = @import("verifier/admission_gate.zig");
    _ = @import("verifier/z3_bridge.zig");
    _ = @import("verifier/unsat_core.zig");
    _ = @import("verifier/builtin_lia.zig");
    _ = @import("verifier/zig_ast_verify.zig");
    _ = @import("verifier/proof_check.zig");
    _ = @import("verifier/model_extract.zig");
    _ = @import("verifier/array_theory.zig");
    _ = @import("verifier/chc.zig");
    _ = @import("verifier/string_theory.zig");
    _ = @import("verifier/cegis.zig");
    _ = @import("verifier/dtmc.zig");
    _ = @import("verifier/abstract_interp.zig");
    _ = @import("verifier/noninterference.zig");
    _ = @import("verifier/nra_quant.zig");
    _ = @import("verifier/redos.zig");
    _ = @import("runtime/kern_x.zig");
    _ = @import("proof_cache.zig");
    _ = @import("atomic_write.zig");
    _ = @import("tests/exhaustive_suite.zig");
    _ = @import("tests/alignment_stress.zig");
    _ = @import("tests/pool_saturation.zig");
    _ = @import("tests/oom_stress.zig");
    _ = @import("tests/mcdc_gates_test.zig");
    _ = @import("tests/z3_crash_test.zig");
    _ = @import("tests/smt_incremental_test.zig");
    _ = @import("tests/litmus_memory_test.zig");
    _ = @import("tests/os_stress_test.zig");
    _ = @import("tests/pipe_stress_test.zig");
    _ = @import("concolic.zig");
    // ВАЖНО: отчёт покрытия обязан идти ПОСЛЕДНИМ — он читает счётчики,
    // набранные всеми предыдущими тестами.
    _ = @import("tests/coverage_report_test.zig");
    // ЭШЕЛОН 8, ПУНКТ 40А: тесты WASM-моста. ПРАВИЛО №10 КОДЕКСА:
    // файл, добавленный в TARGETS мутатора, ОБЯЗАН компилироваться тестовым
    // раннером — иначе мутации в нём измеряют фикцию (Дефект #131).
    _ = @import("wasm_api.zig");
}
