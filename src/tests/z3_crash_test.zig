// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: УСТОЙЧИВОСТЬ К КРАХУ РЕШАТЕЛЯ (IPC Broken Pipe / SIGPIPE).
//!
//! Что проверяем: если подпроцесс решателя умирает (SIGSEGV самого Z3,
//! OOM-killer, kill -9) ПОКА KERN пишет в его stdin, пайп рвётся.
//!
//! Опасность: запись в закрытый пайп посылает SIGPIPE, который по умолчанию
//! УБИВАЕТ процесс. Тогда падает не только Z3, но и сам KERN — а это уже
//! отказ системы верификации (fail-open / потеря вердикта).
//!
//! Ожидаемое поведение: KERN возвращает `.ToolError` (безопасная деградация,
//! Врата НЕ открываются) и остаётся жив.
const std = @import("std");
const z3 = @import("../verifier/z3_bridge.zig");

test "Z3 CRASH: решатель завершается сразу -> ToolError, KERN жив" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    bridge.z3_path = "/bin/false"; // процесс мгновенно выходит с кодом 1
    const r = bridge.executeQuery("(check-sat)\n");
    defer if (r.witness_model) |w| std.testing.allocator.free(w);
    try std.testing.expectEqual(z3.SmtStatus.ToolError, r.status);

    // KERN жив: последующий запрос тоже не падает.
    const r2 = bridge.executeQuery("(check-sat)\n");
    defer if (r2.witness_model) |w| std.testing.allocator.free(w);
    try std.testing.expectEqual(z3.SmtStatus.ToolError, r2.status);
}

test "Z3 CRASH: 1 МБ в мёртвый пайп -> нет SIGPIPE, ToolError" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    bridge.z3_path = "/bin/true"; // закрывает stdin и выходит
    const big = try std.testing.allocator.alloc(u8, 1 << 20);
    defer std.testing.allocator.free(big);
    @memset(big, ';'); // длинный «мусорный» скрипт

    const r = bridge.executeQuery(big);
    defer if (r.witness_model) |w| std.testing.allocator.free(w);
    // Главное: мы дошли сюда (процесс не убит SIGPIPE).
    try std.testing.expect(r.status == .ToolError or r.status == .Unknown);
}

test "Z3 CRASH: несуществующий бинарник решателя -> ToolError (spawn fail)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    bridge.z3_path = "/nonexistent/z3-binary-xyz";
    const r = bridge.executeQuery("(check-sat)\n");
    defer if (r.witness_model) |w| std.testing.allocator.free(w);
    try std.testing.expectEqual(z3.SmtStatus.ToolError, r.status);
}

test "Z3 CRASH: Врата НЕ открываются при мёртвом решателе (fail-closed)" {
    const gate = @import("../verifier/admission_gate.zig");
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    bridge.z3_path = "/bin/false";
    const d = [_]u8{0x42} ** 32;
    const cert = gate.ProofCertificate{
        .target_ast_digest = d,
        .contract_digest = d,
        .checker_id = 1,
        .witness_payload = &[_]u8{0xAA},
    };
    const policy = gate.VerificationPolicy{ .require_anti_vacuity = true, .allowed_checkers = 2 };
    const res = try gate.AdmissionGate.verifyClaimWithChecker(
        std.testing.allocator, d, d, cert, policy, z3.makeChecker(&bridge));
    // Отказ безопасен: e=0, никогда не 1.
    try std.testing.expectEqual(@as(u1, 0), res.e_value);
}
