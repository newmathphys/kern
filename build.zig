const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    const exe = b.addExecutable(.{
        .name = "kernc",
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    b.installArtifact(exe);

    // Тесты ядра запускаются из ОБЩЕГО КОРНЯ: `zig test src/tests/...` НЕ
    // РАБОТАЕТ (импорты `../core/...` вне модуля). См. docs/KERN9_SUITE_AUDIT.md.
    const tests = b.addTest(.{
        .root_source_file = b.path("src/test_root.zig"),
        .target = target,
        .optimize = optimize,
    });
    const run_tests = b.addRunArtifact(tests);
    b.step("test", "Тесты ядра KERN").dependOn(&run_tests.step);

    // Проверка уязвимости «один байт = e=1» — отдельной командой.
    const atk = b.addExecutable(.{
        .name = "kern-attack",
        .root_source_file = b.path("src/attack.zig"),
        .target = target,
        .optimize = optimize,
    });
    b.installArtifact(atk);

    // KERN-Next: движок проекта (`kernx`). Требует libc + libsqlite3 (§9).
    const kernx = b.addExecutable(.{
        .name = "kernx",
        .root_source_file = b.path("src/next/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    kernx.linkLibC();
    kernx.linkSystemLibrary("sqlite3");
    b.installArtifact(kernx);

    // Тесты KERN-Next (parser/validate/catalog/snapshot/export/cache/engine).
    const tests_next = b.addTest(.{
        .root_source_file = b.path("src/next/test_root.zig"),
        .target = target,
        .optimize = optimize,
    });
    tests_next.linkLibC();
    tests_next.linkSystemLibrary("sqlite3");
    const run_tests_next = b.addRunArtifact(tests_next);
    b.step("test-next", "Тесты KERN-Next").dependOn(&run_tests_next.step);

    // Инъекция аппаратных сбоев памяти (SIGBUS/SIGSEGV). Требует libc:
    // sigsetjmp/siglongjmp для выхода из обработчика сигнала.
    const fault_tests = b.addTest(.{
        .root_source_file = b.path("src/fault_root.zig"),
        .target = target,
        .optimize = optimize,
    });
    fault_tests.linkLibC();
    const run_fault_tests = b.addRunArtifact(fault_tests);
    b.step("test-fault", "Инъекция сбоев памяти (SIGBUS/SIGSEGV)").dependOn(&run_fault_tests.step);
}
