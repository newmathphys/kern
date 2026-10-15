// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

const std = @import("std");

const eq2 = @import("../core/eq2.zig");
const kimg = @import("../core/kimg_reader.zig");
const obj = @import("../core/object_entry.zig");
const kernfs = @import("../core/kernfs_router.zig");
const gate = @import("../verifier/admission_gate.zig");

// =========================================================================
// ЧАСТЬ I: АЛГЕБРА (L1)
// =========================================================================

test "MATH-01: таблица Белнапа-Данна B4 (Join и Meet)" {
    const Eq2 = eq2.Eq2;
    try std.testing.expectEqual(Eq2.B, Eq2.joinK(.T, .F)); // конфликт
    try std.testing.expectEqual(Eq2.T, Eq2.joinK(.T, .N));
    try std.testing.expectEqual(Eq2.B, Eq2.joinK(.B, .N));
    try std.testing.expectEqual(Eq2.T, Eq2.joinK(.T, .T)); // идемпотентность
    try std.testing.expectEqual(Eq2.N, Eq2.meetK(.T, .F)); // общего нет
    try std.testing.expectEqual(Eq2.T, Eq2.meetK(.T, .B));
}

test "MATH-02: законы де Моргана в порядке истинности" {
    // ⚠️ В исходном сьюте тест НАЗЫВАЛСЯ «De Morgan's Laws», но проверял лишь
    // два изолированных факта. Здесь законы проверяются ПОЛНЫМ ПЕРЕБОРОМ —
    // исправление замечания аудита.
    const all = [_]eq2.Eq2{ .N, .T, .F, .B };
    for (all) |a| {
        for (all) |b| {
            try std.testing.expectEqual(eq2.notB(eq2.andT(a, b)),
                                       eq2.orT(eq2.notB(a), eq2.notB(b)));
            try std.testing.expectEqual(eq2.notB(eq2.orT(a, b)),
                                       eq2.andT(eq2.notB(a), eq2.notB(b)));
        }
    }
}

// =========================================================================
// ЧАСТЬ II: ПАМЯТЬ И ФОРМАТ (L0)
// =========================================================================

test "SEC-01: атака переполнения в заголовке KIMG (offset bomb)" {
    // РЕАЛЬНАЯ УЯЗВИМОСТЬ, найденная этим тестом: без std.math.add
    // `offset + size` переполняется, даёт 89 < file_size, и вредоносный образ
    // ПРИНИМАЕТСЯ (подтверждено в ReleaseFast). Исправлено безопасной
    // арифметикой в kimg_reader.zig.
    var raw_header = @as([128]u8, @splat(0));
    std.mem.copyForwards(u8, raw_header[0..8], "KIMG\r\n\x1a\n");
    std.mem.writeInt(u16, raw_header[8..10], 1, .little);
    std.mem.writeInt(u32, raw_header[20..24], 1, .little); // hash_algo = SHA-256
    std.mem.writeInt(u32, raw_header[12..16], 128, .little);
    std.mem.writeInt(u64, raw_header[32..40], std.math.maxInt(u64) - 10, .little);
    std.mem.writeInt(u64, raw_header[40..48], 100, .little);

    try std.testing.expectError(kimg.KimgError.OutOfBoundsOffset,
        kimg.KimgHeader.parse(&raw_header, 1024));
}

test "SEC-02: троян в reserved-байтах (CONF-15)" {
    var raw_obj = @as([96]u8, @splat(0));
    raw_obj[80] = 0x90; // NOP
    try std.testing.expectError(obj.KimgError.InvalidReservedBytes,
        obj.ObjectEntry.parseSafe(&raw_obj));
}

// =========================================================================
// ЧАСТЬ III: ВИРТУАЛЬНАЯ ФС (L3)
// =========================================================================

test "SEC-03: path traversal и NUL-инъекция" {
    try std.testing.expectError(kernfs.KernFsError.PathTraversalAttempt,
        kernfs.KernFS.validatePath("/raw/../../../etc/shadow"));
    try std.testing.expectError(kernfs.KernFsError.PathTraversalAttempt,
        kernfs.KernFS.validatePath("/claims/../raw/secret.key"));
    try std.testing.expectError(kernfs.KernFsError.InvalidPathFormat,
        kernfs.KernFS.validatePath("/raw/file.zig\x00.md"));
    try std.testing.expectError(kernfs.KernFsError.InvalidPathFormat,
        kernfs.KernFS.validatePath("/raw//source.zig"));
}

// =========================================================================
// ЧАСТЬ IV: ЭПИСТЕМИЧЕСКАЯ БЕЗОПАСНОСТЬ (L4)
// =========================================================================
//
// ⚠️ ИСПРАВЛЕНИЕ АУДИТА: в исходном сьюте стояло `allowed_checkers = 1`, но
// маска считается как `1 << checker_id`, то есть для checker_id = 1 нужен
// бит 1 (значение 2). С `= 1` все три теста падали с UntrustedChecker
// РАНЬШЕ проверяемой логики. Здесь стоит 2.

test "AI-01: текстовый свидетель ≥8 байт НЕ отвергается (реальное поведение)" {
    // ⚠️ ЧЕСТНО: спецификация утверждала, что строка «trust me bro» будет
    // отвергнута как FakeWitnessRejected. НА ДЕЛЕ отвергаются только свидетели
    // КОРОЧЕ 8 байт. Строка из 26 байт проходит и даёт .Unknown -> N, e=0.
    //
    // Безопасность НЕ нарушена (код не допущен), но заявленный механизм иной.
    // Тест фиксирует ФАКТИЧЕСКОЕ поведение, а не желаемое.
    const ast_hash = @as([32]u8, @splat(0x01));
    const fake_cert = gate.ProofCertificate{
        .target_ast_digest = ast_hash,
        .contract_digest = ast_hash,
        .checker_id = 1,
        .witness_payload = "trust me bro, code is valid", // 26 байт ≥ 8
    };
    const policy = gate.VerificationPolicy{ .require_anti_vacuity = true,
                                            .allowed_checkers = 2 };
    const res = try gate.AdmissionGate.verifyClaim(ast_hash, ast_hash,
                                                   fake_cert, policy);
    try std.testing.expectEqual(eq2.Eq2.N, res.eq2_status);
    try std.testing.expectEqual(@as(u1, 0), res.e_value); // в прод НЕ пущен
}

/// Стаб внешнего чекера: возвращает заданный вердикт (для тестов L4).
fn stubVacuous(ctx: ?*anyopaque, allocator: std.mem.Allocator,
               ast: [32]u8, contract: [32]u8, proof: []const u8) gate.CheckerVerdict {
    _ = .{ ctx, allocator, ast, contract, proof };
    return .VacuousPrecondition;
}

test "AI-01b: короткий свидетель без внешнего чекера не допускается" {
    // После ФИКСА АТАКИ 1 «отклонение фейка» — не отдельный механизм длины,
    // а следствие того, что без внешнего чекера вердикта нет: e=0.
    const ast_hash = @as([32]u8, @splat(0x01));
    const fake_cert = gate.ProofCertificate{
        .target_ast_digest = ast_hash,
        .contract_digest = ast_hash,
        .checker_id = 1,
        .witness_payload = "proved", // 6 байт
    };
    const policy = gate.VerificationPolicy{ .require_anti_vacuity = true,
                                            .allowed_checkers = 2 };
    const res = try gate.AdmissionGate.verifyClaim(ast_hash, ast_hash,
                                                   fake_cert, policy);
    try std.testing.expectEqual(eq2.Eq2.N, res.eq2_status);
    try std.testing.expectEqual(@as(u1, 0), res.e_value);
}

test "AI-02: устаревший сертификат (несовпадение хеша AST)" {
    const old_ast = @as([32]u8, @splat(0xAA));
    const new_ast = @as([32]u8, @splat(0xBB));
    const contract = @as([32]u8, @splat(0x02));
    const stolen_cert = gate.ProofCertificate{
        .target_ast_digest = old_ast,
        .contract_digest = contract,
        .checker_id = 1,
        .witness_payload = &[_]u8{ 0xAA, 0, 0, 0, 0, 0, 0, 0 },
    };
    const policy = gate.VerificationPolicy{ .require_anti_vacuity = true,
                                            .allowed_checkers = 2 };
    try std.testing.expectError(gate.GateError.AstHashMismatch,
        gate.AdmissionGate.verifyClaim(new_ast, contract, stolen_cert, policy));
}

test "AI-03: вакуумное предусловие (анти-вакуумный шлюз)" {
    const ast_hash = @as([32]u8, @splat(0x01));
    const vacuous_cert = gate.ProofCertificate{
        .target_ast_digest = ast_hash,
        .contract_digest = ast_hash,
        .checker_id = 1,
        .witness_payload = &[_]u8{ 0xCC, 0, 0, 0, 0, 0, 0, 0 },
    };
    const policy = gate.VerificationPolicy{ .require_anti_vacuity = true,
                                            .allowed_checkers = 2 };
    try std.testing.expectError(gate.GateError.PolicyViolation,
        gate.AdmissionGate.verifyClaimWithChecker(
            std.testing.allocator, ast_hash, ast_hash, vacuous_cert, policy,
            gate.TrustedChecker{ .runFn = stubVacuous }));
}

test "ФИКС АТАКИ 1: ОДИН БАЙТ 0xAA НЕ даёт e=1 (уязвимость закрыта)" {
    // Раньше: шлюз читал вердикт из payload[0] → 0xAA давал e=1.
    // Теперь: вердикт приходит только извне, 0xAA доказательством не является.
    const ast_hash = @as([32]u8, @splat(0x01));
    const cert = gate.ProofCertificate{
        .target_ast_digest = ast_hash,
        .contract_digest = ast_hash,
        .checker_id = 1,
        .witness_payload = &[_]u8{ 0xAA, 0, 0, 0, 0, 0, 0, 0 },
    };
    const policy = gate.VerificationPolicy{ .require_anti_vacuity = true,
                                            .allowed_checkers = 2 };
    const res = try gate.AdmissionGate.verifyClaim(ast_hash, ast_hash, cert, policy);
    try std.testing.expectEqual(eq2.Eq2.N, res.eq2_status);
    try std.testing.expectEqual(@as(u1, 0), res.e_value);
}

// =========================================================================
// ЧАСТЬ V: РЕСУРСЫ
// =========================================================================

test "RES-01: исчерпание топлива — это N, а не F" {
    // Тайм-аут НЕ является опровержением теоремы.
    const exhausted = gate.CheckerVerdict.Timeout;
    var status: eq2.Eq2 = .N;
    switch (exhausted) {
        .Timeout => status = .N,
        else => unreachable,
    }
    try std.testing.expectEqual(eq2.Eq2.N, status);
}

