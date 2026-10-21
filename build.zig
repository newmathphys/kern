const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    const exe_mod = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    const exe = b.addExecutable(.{ .name = "kernc", .root_module = exe_mod });
    b.installArtifact(exe);

    // Тесты ядра запускаются из ОБЩЕГО КОРНЯ: `zig test src/tests/...` НЕ
    // РАБОТАЕТ (импорты `../core/...` вне модуля). См. docs/archive/KERN9_SUITE_AUDIT.md.
    const tests_mod = b.createModule(.{
        .root_source_file = b.path("src/test_root.zig"),
        .target = target,
        .optimize = optimize,
    });
    const tests = b.addTest(.{ .root_module = tests_mod });
    const run_tests = b.addRunArtifact(tests);
    b.step("test", "Тесты ядра KERN").dependOn(&run_tests.step);

    // РАЗДЕЛ 7 ЭНЦИКЛОПЕДИИ: детерминированная симуляция сбоев (DST).
    const dst_mod = b.createModule(.{
        .root_source_file = b.path("src/dst_main.zig"),
        .target = target,
        .optimize = .ReleaseSmall,
    });
    const dst_exe = b.addExecutable(.{ .name = "kern-dst", .root_module = dst_mod });
    b.step("dst", "DST: детерминированная симуляция сбоев").dependOn(&b.addInstallArtifact(dst_exe, .{}).step);

    // ЭШЕЛОН 8, ПУНКТ 40А: ядро в WebAssembly (0 syscalls, freestanding).
    // Только `builtin_lia` + решётка Белнапа + Хэмминг: `proof_check` тянет
    // `z3_bridge` (спавн внешнего процесса), которого в freestanding нет.
    const wasm_mod = b.createModule(.{
        .root_source_file = b.path("src/wasm_api.zig"),
        .target = b.resolveTargetQuery(.{ .cpu_arch = .wasm32, .os_tag = .freestanding }),
        .optimize = .ReleaseSmall,
    });
    const wasm = b.addExecutable(.{ .name = "kernc", .root_module = wasm_mod });
    wasm.entry = .disabled;
    wasm.rdynamic = true;
    const wasm_install = b.addInstallArtifact(wasm, .{ .dest_sub_path = "kernc.wasm" });
    b.step("wasm", "Ядро KERN в WebAssembly (kernc.wasm)").dependOn(&wasm_install.step);

    // Проверка уязвимости «один байт = e=1» — отдельной командой.
    const atk_mod = b.createModule(.{
        .root_source_file = b.path("src/attack.zig"),
        .target = target,
        .optimize = optimize,
    });
    const atk = b.addExecutable(.{ .name = "kern-attack", .root_module = atk_mod });
    b.installArtifact(atk);

    // Общий модуль авторства/аттестации: нужен и ядру (src/), и KERN-Next
    // (src/next/). Прямой `@import("../owner.zig")` невозможен — файл вне
    // корня модуля. Поэтому отдаём его как именованный модуль.
    const owner_module = b.createModule(.{
        .root_source_file = b.path("src/owner.zig"),
        .target = target,
        .optimize = optimize,
    });

    // Общий модуль атомарной записи: нужен и ядру (src/), и KERN-Next
    // (src/next/). Как и owner, отдаём именованным модулем.
    const atomic_module = b.createModule(.{
        .root_source_file = b.path("src/atomic_write.zig"),
        .target = target,
        .optimize = optimize,
    });

    // Слой совместимости Zig 0.13 -> 0.17 (std.Io): файловый I/O теперь
    // требует явный `io`, а `std.fs.cwd()`/`std.io` удалены. Модуль нужен
    // и ядру (src/), и KERN-Next (src/next/), поэтому отдаём его именованным.
    const compat_module = b.createModule(.{
        .root_source_file = b.path("src/compat.zig"),
        .target = target,
        .optimize = optimize,
    });
    exe_mod.addImport("compat", compat_module);
    tests_mod.addImport("compat", compat_module);

    // ---- Фильтрованные прогоны (Эшелоны 1 и 3) ---------------------------
    // ВАЖНО: прямой `zig test src/test_root.zig` НЕ РАБОТАЕТ — модуль `compat`
    // (слой совместимости 0.13→0.17) передаётся только сборочной системой.
    // Поэтому цели `make align` / `make pool` ходят сюда, а не в `zig test`.
    const align_tests_mod = b.createModule(.{
        .root_source_file = b.path("src/test_root.zig"),
        .target = target,
        .optimize = optimize,
    });
    align_tests_mod.addImport("compat", compat_module);
    const align_tests = b.addTest(.{
        .root_module = align_tests_mod,
        .filters = &.{ "ALIGN", "ENDIAN" },
    });
    const run_align_tests = b.addRunArtifact(align_tests);
    b.step("test-align", "Эшелон 1: выравнивание памяти и endianness").dependOn(&run_align_tests.step);

    const pool_tests_mod = b.createModule(.{
        .root_source_file = b.path("src/test_root.zig"),
        .target = target,
        .optimize = optimize,
    });
    pool_tests_mod.addImport("compat", compat_module);
    const pool_tests = b.addTest(.{
        .root_module = pool_tests_mod,
        .filters = &.{"POOL"},
    });
    const run_pool_tests = b.addRunArtifact(pool_tests);
    b.step("test-pool", "Эшелон 3: изнурение пула решателей").dependOn(&run_pool_tests.step);

    // ---- Бенчмарки и стресс-утилиты --------------------------------------
    // ВАЖНО (найдено при верификации 0.17): `zig run src/X.zig` НЕ РАБОТАЕТ,
    // если X или его транзитивные зависимости импортируют ИМЕНОВАННЫЕ модули
    // (`compat`/`owner`/`atomic`) — их передаёт только сборочная система.
    // Регистрируем каждый бенчмарк как исполняемый файл: `zig build bench-<имя>`.
    const Bench = struct { name: []const u8, file: []const u8, desc: []const u8 };
    const benches = [_]Bench{
        .{ .name = "perf", .file = "src/perf_bench.zig", .desc = "Скорость конвейера .kimg" },
        .{ .name = "kimg-stress", .file = "src/kimg_stress.zig", .desc = "Стресс 1 млн объектов" },
        .{ .name = "smt", .file = "src/smt_bench.zig", .desc = "SMT: Alive2 / Hacker's Delight" },
        .{ .name = "smt-stress", .file = "src/smt_stress.zig", .desc = "SMT-стресс (парадоксы, overflow, NIA)" },
        .{ .name = "kern", .file = "src/kern_bench.zig", .desc = "KERN-native бенчмарк" },
        .{ .name = "stress-real", .file = "src/stress_real.zig", .desc = "Стресс на реальном коде" },
        .{ .name = "stress-1m", .file = "tests/stress_1m.zig", .desc = "1 млн проектов в памяти" },
        .{ .name = "fuzz-ast", .file = "src/fuzz_ast.zig", .desc = "Фаззинг AST-парсера" },
        .{ .name = "chc", .file = "src/chc_bench.zig", .desc = "CHC/Horn бенчмарк" },
        .{ .name = "hash", .file = "src/hash_bench.zig", .desc = "SHA-256 vs BLAKE3 (узкое место Safe-чтения)" },
        .{ .name = "semantic", .file = "src/semantic_probe.zig", .desc = "Семантический зонд" },
        .{ .name = "sim", .file = "src/sim_test.zig", .desc = "Симуляция конкурентности" },
    };
    inline for (benches) |it| {
        const bench_mod = b.createModule(.{
            .root_source_file = b.path(it.file),
            .target = target,
            .optimize = .ReleaseFast,
        });
        bench_mod.addImport("compat", compat_module);
        bench_mod.addImport("owner", owner_module);
        bench_mod.addImport("atomic", atomic_module);
        const bench_exe = b.addExecutable(.{ .name = "kern-bench-" ++ it.name, .root_module = bench_mod });
        const bench_run = b.addRunArtifact(bench_exe);
        b.step("bench-" ++ it.name, it.desc).dependOn(&bench_run.step);
    }

    // Симуляция конкурентности: два фиксированных профиля (аргументы задаются
    // здесь, т.к. в Zig 0.17 у `std.Build` нет поля `b.args`).
    const sim_mod = b.createModule(.{
        .root_source_file = b.path("src/sim_test.zig"),
        .target = target,
        .optimize = .ReleaseFast,
    });
    sim_mod.addImport("compat", compat_module);
    const sim_seeds = b.addExecutable(.{ .name = "kern-sim-seeds", .root_module = sim_mod });
    const run_sim_seeds = b.addRunArtifact(sim_seeds);
    run_sim_seeds.addArgs(&.{ "--seeds", "1,2,3,0xDEADBEEF", "--ops", "20000" });
    b.step("sim-seeds", "Симуляция: детерминизм по 4 сидам").dependOn(&run_sim_seeds.step);

    const sim_threads = b.addExecutable(.{ .name = "kern-sim-threads", .root_module = sim_mod });
    const run_sim_threads = b.addRunArtifact(sim_threads);
    run_sim_threads.addArgs(&.{ "--threads", "32", "--titers", "500" });
    b.step("sim-threads", "Симуляция: 32 потока").dependOn(&run_sim_threads.step);

    atk_mod.addImport("compat", compat_module);
    atomic_module.addImport("compat", compat_module);

    // Zig 0.17: `@cImport` удалён. C-заголовок SQLite транслируется
    // сборочной системой в отдельный кэшируемый модуль `c_sqlite`.
    const sqlite_c = b.addTranslateC(.{
        .root_source_file = b.path("include/sqlite3_bridge.h"),
        .target = target,
        .optimize = optimize,
    });
    const sqlite_mod = sqlite_c.createModule();

    // KERN-Next: движок проекта (`kernx`). Требует libc + libsqlite3 (§9).
    const kernx_mod = b.createModule(.{
        .root_source_file = b.path("src/next/main.zig"),
        .target = target,
        .optimize = optimize,
        .link_libc = true,
    });
    const kernx = b.addExecutable(.{ .name = "kernx", .root_module = kernx_mod });
    kernx.root_module.addImport("owner", owner_module);
    kernx.root_module.addImport("atomic", atomic_module);
    kernx.root_module.addImport("compat", compat_module);
    kernx_mod.addImport("c_sqlite", sqlite_mod);
    kernx_mod.linkSystemLibrary("sqlite3", .{});
    b.installArtifact(kernx);

    // Phase 5: conformance oracle. Prints kernel facts as `section|key|value`
    // so `tools/conformance_check.py` can assert on the SAME functions the
    // verifier uses, instead of trusting test names.
    const conformance_mod = b.createModule(.{
        .root_source_file = b.path("src/conformance_oracle.zig"),
        .target = target,
        .optimize = optimize,
    });
    conformance_mod.addImport("compat", compat_module);
    const conformance_exe = b.addExecutable(.{ .name = "kern-conformance", .root_module = conformance_mod });
    b.installArtifact(conformance_exe);

    // Тесты KERN-Next (parser/validate/catalog/snapshot/export/cache/engine).
    const tests_next_mod = b.createModule(.{
        .root_source_file = b.path("src/next/test_root.zig"),
        .target = target,
        .optimize = optimize,
        .link_libc = true,
    });
    const tests_next = b.addTest(.{ .root_module = tests_next_mod });
    tests_next.root_module.addImport("atomic", atomic_module);
    tests_next.root_module.addImport("compat", compat_module);
    tests_next_mod.addImport("c_sqlite", sqlite_mod);
    tests_next_mod.linkSystemLibrary("sqlite3", .{});
    const run_tests_next = b.addRunArtifact(tests_next);
    b.step("test-next", "Тесты KERN-Next").dependOn(&run_tests_next.step);

    // Инъекция аппаратных сбоев памяти (SIGBUS/SIGSEGV). Требует libc:
    // sigsetjmp/siglongjmp для выхода из обработчика сигнала.
    const fault_tests_mod = b.createModule(.{
        .root_source_file = b.path("src/fault_root.zig"),
        .target = target,
        .optimize = optimize,
        .link_libc = true,
    });
    const fault_tests = b.addTest(.{ .root_module = fault_tests_mod });
    fault_tests.root_module.addImport("compat", compat_module);
    const run_fault_tests = b.addRunArtifact(fault_tests);
    b.step("test-fault", "Инъекция сбоев памяти (SIGBUS/SIGSEGV)").dependOn(&run_fault_tests.step);

    // ---- C-ABI: libkern.so / libkern.a + include/kern.h -------------------
    // Встраивание ядра в Python / Rust / Go / C++ без запуска CLI-процесса.
    const capi_mod = b.createModule(.{
        .root_source_file = b.path("src/capi.zig"),
        .target = target,
        .optimize = optimize,
    });
    capi_mod.addImport("owner", owner_module);
    capi_mod.addImport("compat", compat_module);

    const shared_mod = b.createModule(.{
        .root_source_file = b.path("src/capi.zig"),
        .target = target,
        .optimize = optimize,
        .link_libc = true,
    });
    const shared = b.addLibrary(.{ .name = "kern", .root_module = shared_mod, .linkage = .dynamic });
    shared.root_module.addImport("owner", owner_module);
    shared.root_module.addImport("compat", compat_module);
    shared.installHeader(b.path("include/kern.h"), "kern.h");
    b.installArtifact(shared);

    const static_mod = b.createModule(.{
        .root_source_file = b.path("src/capi.zig"),
        .target = target,
        .optimize = optimize,
        .link_libc = true,
    });
    const static = b.addLibrary(.{ .name = "kern", .root_module = static_mod, .linkage = .static });
    static.root_module.addImport("owner", owner_module);
    static.root_module.addImport("compat", compat_module);
    b.installArtifact(static);

    b.step("lib", "Собрать C-ABI библиотеку (libkern.so/.a + kern.h)").dependOn(&b.addInstallArtifact(shared, .{}).step);

    // ---- Герметичная (воспроизводимая) сборка ----------------------------
    // Статический musl-таргет: никаких системных библиотек, sha256 бинарника
    // воспроизводим на любой машине (требование EAL7 / DO-330).
    const musl_target = b.resolveTargetQuery(.{
        .cpu_arch = .x86_64,
        .os_tag = .linux,
        .abi = .musl,
    });
    const hermetic_exe_mod = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = musl_target,
        .optimize = .ReleaseSafe,
    });
    hermetic_exe_mod.addImport("compat", compat_module);
    const hermetic_exe = b.addExecutable(.{ .name = "kernc-hermetic", .root_module = hermetic_exe_mod });
    const hermetic_install = b.addInstallArtifact(hermetic_exe, .{});
    b.step("hermetic", "Герметичная статическая сборка (x86_64-linux-musl)").dependOn(&hermetic_install.step);
}
