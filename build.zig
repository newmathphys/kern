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
