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
}
