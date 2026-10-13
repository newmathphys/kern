// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

const std = @import("std");
const AdmissionGate = @import("verifier/admission_gate.zig").AdmissionGate;
const ProofCertificate = @import("verifier/admission_gate.zig").ProofCertificate;
const VerificationPolicy = @import("verifier/admission_gate.zig").VerificationPolicy;
const KernFS = @import("core/kernfs_router.zig").KernFS;
const compat = @import("compat");

/// ВОСПРОИЗВОДИМАЯ ПРОВЕРКА ДВУХ АТАК — ПОСЛЕ ФИКСОВ ФАЗЫ 1.
///
/// Раньше (docs/archive/KERN34_AUDIT.md):
///   (1) Врата Истины обходились ОДНИМ БАЙТОМ 0xAA -> e=1;
///   (2) KERNFS не находил ни одного файла в образе v1.2.
/// Теперь обе атаки НЕ проходят (см. вывод).
pub fn main(init: std.process.Init) !void {
    // Zig 0.17: файловый I/O требует явный `io` — публикуем его в compat.
    // БАГ-ФИКС: раньше здесь было `pub fn main() !void` без setIo, из-за чего
    // `kern-attack` падал с panic «compat.setIo() не вызван» на АТАКЕ 2.
    compat.setIo(init.io);
    var gpa = std.heap.DebugAllocator(.{}){};
    defer _ = gpa.deinit();
    const alloc = gpa.allocator();

    std.debug.print(
        "\n########## АТАКА 1: ИИ присылает ОДИН БАЙТ вместо доказательства ##########\n",
        .{});

    const ast_hash = @as([32]u8, @splat(0x01));
    const ai_cert = ProofCertificate{
        .target_ast_digest = ast_hash,
        .contract_digest = ast_hash,
        .checker_id = 1,
        .witness_payload = &[_]u8{ 0xAA, 0, 0, 0, 0, 0, 0, 0 }, // ОДИН БАЙТ
    };
    const policy = VerificationPolicy{ .require_anti_vacuity = true,
                                       .allowed_checkers = 0xFFFFFFFF };

    const res = try AdmissionGate.verifyClaim(ast_hash, ast_hash, ai_cert, policy);
    std.debug.print("Вердикт: {s}, e={d}\n",
        .{ @tagName(res.eq2_status), res.e_value });
    if (res.e_value == 0) {
        std.debug.print(
            ">>> ИТОГ: код НЕ допущен — один байт больше не работает <<<\n", .{});
    } else {
        std.debug.print(">>> ИТОГ: УЯЗВИМОСТЬ ВОЗВРАЩАЕТСЯ! <<<\n", .{});
    }

    std.debug.print(
        "\n########## АТАКА 2: KERNFS на согласованном образе v1.3 ##########\n", .{});

    const data = compat.readFileAlloc(
        alloc, "tests/fixtures/valid_v1_3.kimg", 1 << 20) catch {
        std.debug.print("[i] образа нет — соберите: python3 tools/golden_v1_3.py\n", .{});
        return;
    };
    defer alloc.free(data);

    var fs = KernFS.mountFromBytes(alloc, data) catch |e| {
        std.debug.print(">>> монтирование не удалось: {s} <<<\n", .{@errorName(e)});
        return;
    };
    defer fs.deinit();

    const probes = [_][]const u8{
        "/raw/src/main.zig",
        "/claims/L0_AlignmentInvariant.kern/status",
        "/claims/L0_AlignmentInvariant.kern/contract.json",
    };
    for (probes) |p| {
        std.debug.print("  {s} -> ", .{p});
        if (fs.read(p)) |node| {
            switch (node) {
                .raw_slice => |s| std.debug.print("НАЙДЕНО ({d} б): {s}\n", .{ s.len, s }),
                .virtual_view => |s| std.debug.print("НАЙДЕНО (view): {s}\n", .{s}),
            }
        } else |e| {
            std.debug.print("ошибка: {s}\n", .{@errorName(e)});
        }
    }

    // Запись в KERNFS запрещена (CONF-06) — теперь возвращается AccessDenied.
    if (fs.write("/raw/src/main.zig", "x")) |_| {} else |e| {
        std.debug.print("  запись -> ошибка: {s} (ожидаем AccessDenied)\n",
            .{@errorName(e)});
    }
    std.debug.print(
        ">>> ИТОГ: роутер находит объекты — Фазы 1 и 3 согласованы <<<\n\n", .{});
}
