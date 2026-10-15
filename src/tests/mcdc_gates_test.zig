// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by the GNU Affero General Public License v3.0 ONLY
// (AGPL-3.0-only), or a commercial license from the copyright holder. See LICENSE.

//! KERN: MC/DC (Modified Condition/Decision Coverage) — DO-178C DAL A / ISO 26262 ASIL D.
//!
//! Для высших уровней безопасности обычного покрытия строк/веток НЕДОСТАТОЧНО.
//! Требуется доказать, что каждое отдельное условие в составном решении
//! СПОСОБНО независимо изменить исход, когда остальные зафиксированы.
//!
//! Здесь — тест-векторы на РЕАЛЬНОЕ решение Врат Истины
//! (`AdmissionGate.verifyClaimWithChecker`), а не на его модель.
const std = @import("std");
const gate = @import("../verifier/admission_gate.zig");
const Eq2 = @import("../core/eq2.zig").Eq2;

fn vProved(ctx: ?*anyopaque, allocator: std.mem.Allocator, ast: [32]u8, contract: [32]u8, proof: []const u8) gate.CheckerVerdict {
    _ = .{ ctx, allocator, ast, contract, proof };
    return .Proved;
}
fn vCounter(ctx: ?*anyopaque, allocator: std.mem.Allocator, ast: [32]u8, contract: [32]u8, proof: []const u8) gate.CheckerVerdict {
    _ = .{ ctx, allocator, ast, contract, proof };
    return .Counterexample;
}
fn vVacuous(ctx: ?*anyopaque, allocator: std.mem.Allocator, ast: [32]u8, contract: [32]u8, proof: []const u8) gate.CheckerVerdict {
    _ = .{ ctx, allocator, ast, contract, proof };
    return .VacuousPrecondition;
}

const D: [32]u8 = @as([32]u8, @splat(0x11));
const E: [32]u8 = @as([32]u8, @splat(0x22));

/// Тип функции внешнего чекера (совпадает с полем `TrustedChecker.runFn`).
const RunFn = *const fn (ctx: ?*anyopaque, allocator: std.mem.Allocator, ast_digest: [32]u8, contract_digest: [32]u8, proof: []const u8) gate.CheckerVerdict;

/// Один тест-вектор MC/DC: ast_ok / contract_ok / allowed / verdict.
fn runVector(ast_ok: bool, contract_ok: bool, allowed: bool, runFn: RunFn) !gate.AdmissionResult {
    const cert = gate.ProofCertificate{
        .target_ast_digest = D,
        .contract_digest = E,
        .checker_id = 1,
        .witness_payload = &[_]u8{0x01},
    };
    const policy = gate.VerificationPolicy{
        .require_anti_vacuity = true,
        .allowed_checkers = if (allowed) 2 else 1, // бит 1 = checker_id 1
    };
    const checker = gate.TrustedChecker{ .ctx = null, .runFn = runFn };
    return gate.AdmissionGate.verifyClaimWithChecker(
        std.testing.allocator,
        if (ast_ok) D else @as([32]u8, @splat(0x99)),
        if (contract_ok) E else @as([32]u8, @splat(0x88)),
        cert,
        policy,
        checker,
    );
}

test "MC/DC-1: базовый вектор — все условия T -> e=1 (Врата открыты)" {
    const r = try runVector(true, true, true, vProved);
    try std.testing.expectEqual(@as(u1, 1), r.e_value);
    try std.testing.expectEqual(Eq2.T, r.eq2_status);
}

test "MC/DC-2: ТОЛЬКО ast_ok=F (остальные T) -> AstHashMismatch (условие независимо)" {
    try std.testing.expectError(gate.GateError.AstHashMismatch, runVector(false, true, true, vProved));
}

test "MC/DC-3: ТОЛЬКО contract_ok=F (остальные T) -> ContractHashMismatch (независимо)" {
    try std.testing.expectError(gate.GateError.ContractHashMismatch, runVector(true, false, true, vProved));
}

test "MC/DC-4: ТОЛЬКО allowed=F (остальные T) -> UntrustedChecker (независимо)" {
    try std.testing.expectError(gate.GateError.UntrustedChecker, runVector(true, true, false, vProved));
}

test "MC/DC-5: ТОЛЬКО вердикт=Counterexample -> e=0, F (независимо)" {
    const r = try runVector(true, true, true, vCounter);
    try std.testing.expectEqual(@as(u1, 0), r.e_value);
    try std.testing.expectEqual(Eq2.F, r.eq2_status);
}

test "MC/DC-6: VacuousPrecondition + require_anti_vacuity=true -> PolicyViolation" {
    try std.testing.expectError(gate.GateError.PolicyViolation, runVector(true, true, true, vVacuous));
}

test "MC/DC-7: анти-вакуумность ИНВЕРТИРУЕТ исход при прочих равных" {
    // Тот же вход, но политика без анти-вакуума -> не ошибка, а e=0 (N).
    const cert = gate.ProofCertificate{
        .target_ast_digest = D,
        .contract_digest = E,
        .checker_id = 1,
        .witness_payload = &[_]u8{0x01},
    };
    const policy = gate.VerificationPolicy{ .require_anti_vacuity = false, .allowed_checkers = 2 };
    const checker = gate.TrustedChecker{ .ctx = null, .runFn = vVacuous };
    const r = try gate.AdmissionGate.verifyClaimWithChecker(std.testing.allocator, D, E, cert, policy, checker);
    try std.testing.expectEqual(@as(u1, 0), r.e_value);
    try std.testing.expectEqual(Eq2.N, r.eq2_status);
}

test "MC/DC-8: таблица истинности VerificationPolicy.allows (все 32 бита)" {
    // Каждый бит маски обязан независимо разрешать ровно свой checker_id.
    var bit: u32 = 0;
    while (bit < 32) : (bit += 1) {
        const mask: u32 = @as(u32, 1) << @intCast(bit);
        const p = gate.VerificationPolicy{ .require_anti_vacuity = false, .allowed_checkers = mask };
        try std.testing.expect(p.allows(bit));
        // Соседние биты НЕ разрешены (независимость условий).
        if (bit > 0) try std.testing.expect(!p.allows(bit - 1));
        if (bit < 31) try std.testing.expect(!p.allows(bit + 1));
    }
    // Нулевая маска не разрешает никого.
    const none = gate.VerificationPolicy{ .require_anti_vacuity = false, .allowed_checkers = 0 };
    try std.testing.expect(!none.allows(0));
}
