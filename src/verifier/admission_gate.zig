// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

const std = @import("std");
const Eq2 = @import("../core/eq2.zig").Eq2;

pub const GateError = error{
    AstHashMismatch,
    ContractHashMismatch,
    UntrustedChecker,
    PolicyViolation,
};

/// Строгий сертификат, который ИИ обязан предоставить вместе с кодом (PC3)
pub const ProofCertificate = struct {
    target_ast_digest: [32]u8,     // хэш кода, который проверяем
    contract_digest: [32]u8,       // хэш контракта (Pre/Post условий)
    checker_id: u32,               // 0x01 = Z3 SMT, 0x02 = Lean 4
    witness_payload: []const u8,   // «бинарный терм доказательства»
};

/// Политика верификации проекта.
///
/// ⚠️ ЛОВУШКА, найденная аудитом: маска считается как `1 << checker_id`,
/// поэтому `allowed_checkers = 1` НЕ разрешает `checker_id = 1` — это бит 0.
/// Чтобы разрешить checker 1, нужно `allowed_checkers = 2`.
pub const VerificationPolicy = struct {
    require_anti_vacuity: bool,
    /// Битовая маска: checker разрешён, если выставлен бит `1 << checker_id`.
    /// ВНИМАНИЕ: `allowed_checkers = 1` разрешает checker_id = 0, а НЕ 1.
    /// Чтобы разрешить checker_id = 1, нужно `allowed_checkers = 2`.
    allowed_checkers: u32,

    pub fn allows(self: VerificationPolicy, checker_id: u32) bool {
        const mask = @as(u32, 1) << @as(u5, @truncate(checker_id));
        return (self.allowed_checkers & mask) != 0;
    }
};

/// Результат прохода через Шлюз Истины
pub const AdmissionResult = struct {
    eq2_status: Eq2,
    e_value: u1, // 1 = пропущено в прод
};

/// Внутренние статусы прувера. Объявлен на уровне ФАЙЛА (тест-сьют обращается
/// как `gate.CheckerVerdict`; вложенный в AdmissionGate был недоступен).
pub const CheckerVerdict = enum { Proved, Counterexample, VacuousPrecondition, Timeout, Unknown };

/// ВНЕШНИЙ доверенный чекер — ЕДИНСТВЕННЫЙ источник вердикта.
///
/// ИНВАРИАНТ БЕЗОПАСНОСТИ (закрывает АТАКУ 1 из docs/KERN34_AUDIT.md):
/// вердикт НЕ выводится из `cert.witness_payload` (данных, которыми управляет
/// ИИ). Payload передаётся чекеру как ВХОД (например, SMT-LIB формула).
/// Чекер — доверенный код, который в проде запускает изолированный процесс
/// решателя (Z3/Lean) с тайм-аутом.
pub const TrustedChecker = struct {
    ctx: ?*anyopaque = null,
    runFn: ?*const fn (ctx: ?*anyopaque, allocator: std.mem.Allocator,
                       ast_digest: [32]u8, contract_digest: [32]u8,
                       proof: []const u8) CheckerVerdict = null,

    /// Чекер не сконфигурирован → доказательства нет. НИКОГДА не `.Proved`.
    pub fn unavailable() TrustedChecker {
        return .{};
    }

    pub fn run(self: TrustedChecker, allocator: std.mem.Allocator,
               ast_digest: [32]u8, contract_digest: [32]u8,
               proof: []const u8) CheckerVerdict {
        const f = self.runFn orelse return .Unknown;
        return f(self.ctx, allocator, ast_digest, contract_digest, proof);
    }
};

pub const AdmissionGate = struct {
    /// Безопасный по умолчанию вход. Без внешнего чекера доказательств нет:
    /// любой сертификат, включая «один байт 0xAA», даёт `.Unknown` → e=0.
    pub fn verifyClaim(
        actual_ast_digest: [32]u8,
        actual_contract_digest: [32]u8,
        cert: ProofCertificate,
        policy: VerificationPolicy,
    ) !AdmissionResult {
        return verifyClaimWithChecker(
            std.heap.page_allocator,
            actual_ast_digest,
            actual_contract_digest,
            cert,
            policy,
            TrustedChecker.unavailable(),
        );
    }

    /// Главная функция допуска (Truth Gate) с ВНЕШНИМ чекером.
    ///
    /// Вердикт формирует ТОЛЬКО `checker`; `cert.witness_payload` — вход.
    pub fn verifyClaimWithChecker(
        allocator: std.mem.Allocator,
        actual_ast_digest: [32]u8,
        actual_contract_digest: [32]u8,
        cert: ProofCertificate,
        policy: VerificationPolicy,
        checker: TrustedChecker,
    ) !AdmissionResult {

        // 1. Криптографическая привязка (PC3 Binding Check).
        // Если ИИ поменял код, но подсунул старый сертификат — отказ.
        if (!std.mem.eql(u8, &actual_ast_digest, &cert.target_ast_digest)) {
            return GateError.AstHashMismatch;
        }
        if (!std.mem.eql(u8, &actual_contract_digest, &cert.contract_digest)) {
            return GateError.ContractHashMismatch;
        }

        // 2. Проверка доверия к пруверу (битовая маска `1 << checker_id`).
        if (!policy.allows(cert.checker_id)) {
            return GateError.UntrustedChecker;
        }

        // 3. Вердикт от ВНЕШНЕГО чекера. Payload — вход, а НЕ вердикт.
        const checker_verdict = checker.run(allocator, actual_ast_digest,
                                            actual_contract_digest,
                                            cert.witness_payload);

        // 4. Вычисление кванта KERN-EQ2
        var eq2 = Eq2.N;
        var e_val: u1 = 0;

        switch (checker_verdict) {
            .Proved => {
                eq2 = .T;
                e_val = 1; // GATE OPEN
            },
            .Counterexample => eq2 = .F,
            .VacuousPrecondition => {
                if (policy.require_anti_vacuity) {
                    return GateError.PolicyViolation; // CONF-04
                }
                eq2 = .N;
            },
            .Timeout, .Unknown => eq2 = .N, // тайм-аут не является опровержением
        }

        return AdmissionResult{ .eq2_status = eq2, .e_value = e_val };
    }

    // runTrustedChecker УДАЛЁН. Он читал вердикт из байта payload[0] (0xAA →
    // .Proved) — то есть из данных, которыми управляет ИИ (АТАКА 1,
    // docs/KERN34_AUDIT.md). Вердикт теперь формирует только `TrustedChecker`.
};

// ==========================================
// СТАБЫ ВНЕШНЕГО ЧЕКЕРА (только для тестов)
// ==========================================
fn stubProved(ctx: ?*anyopaque, allocator: std.mem.Allocator,
              ast: [32]u8, contract: [32]u8, proof: []const u8) CheckerVerdict {
    _ = .{ ctx, allocator, ast, contract, proof };
    return .Proved;
}

fn stubVacuous(ctx: ?*anyopaque, allocator: std.mem.Allocator,
               ast: [32]u8, contract: [32]u8, proof: []const u8) CheckerVerdict {
    _ = .{ ctx, allocator, ast, contract, proof };
    return .VacuousPrecondition;
}

/// Имитация ВНЕШНЕГО решателя: `.Proved` только для структурно корректного
/// SMT-свидетеля. Одиночный байт 0xAA свидетелем НЕ является.
fn stubSmtLike(ctx: ?*anyopaque, allocator: std.mem.Allocator,
               ast: [32]u8, contract: [32]u8, proof: []const u8) CheckerVerdict {
    _ = .{ ctx, allocator, ast, contract };
    if (std.mem.startsWith(u8, proof, "(model ")) return .Proved;
    if (std.mem.startsWith(u8, proof, "unsat-core")) return .Counterexample;
    return .Unknown;
}

// ==========================================
// КОНФОРМАНС-ТЕСТЫ
// ==========================================
test "CONF-30.4: отвергается устаревший сертификат (несовпадение AST)" {
    const ast_hash = [_]u8{0x01} ** 32;
    const contract_hash = [_]u8{0x02} ** 32;
    const fake_cert = ProofCertificate{
        .target_ast_digest = [_]u8{0xFF} ** 32,
        .contract_digest = contract_hash,
        .checker_id = 1,
        .witness_payload = &[_]u8{ 0xAA, 0, 0, 0, 0, 0, 0, 0 },
    };
    const policy = VerificationPolicy{ .require_anti_vacuity = true,
                                       .allowed_checkers = 0xFFFFFFFF };
    try std.testing.expectError(GateError.AstHashMismatch,
        AdmissionGate.verifyClaim(ast_hash, contract_hash, fake_cert, policy));
}

test "ФИКС АТАКИ 1: ОДИН БАЙТ 0xAA больше НЕ даёт e=1" {
    // РАНЬШЕ: шлюз читал вердикт из payload[0] → 0xAA давал e=1.
    // ТЕПЕРЬ: без внешнего чекера вердикт взять неоткуда → e=0.
    const ast_hash = [_]u8{0x01} ** 32;
    const cert = ProofCertificate{
        .target_ast_digest = ast_hash,
        .contract_digest = ast_hash,
        .checker_id = 1,
        .witness_payload = &[_]u8{ 0xAA, 0, 0, 0, 0, 0, 0, 0 }, // нет доказательства
    };
    const policy = VerificationPolicy{ .require_anti_vacuity = true,
                                       .allowed_checkers = 2 };
    const res = try AdmissionGate.verifyClaim(ast_hash, ast_hash, cert, policy);
    try std.testing.expectEqual(Eq2.N, res.eq2_status);
    try std.testing.expectEqual(@as(u1, 0), res.e_value);
}

test "ФИКС АТАКИ 1: внешний решатель-стаб НЕ принимает одиночный байт" {
    const ast_hash = [_]u8{0x01} ** 32;
    const cert = ProofCertificate{
        .target_ast_digest = ast_hash,
        .contract_digest = ast_hash,
        .checker_id = 1,
        .witness_payload = &[_]u8{ 0xAA, 0, 0, 0, 0, 0, 0, 0 },
    };
    const policy = VerificationPolicy{ .require_anti_vacuity = true,
                                       .allowed_checkers = 2 };
    const res = try AdmissionGate.verifyClaimWithChecker(
        std.testing.allocator, ast_hash, ast_hash, cert, policy,
        TrustedChecker{ .runFn = stubSmtLike });
    try std.testing.expectEqual(@as(u1, 0), res.e_value);
}

test "успех: структурно корректный свидетель от ВНЕШНЕГО чекера даёт e=1" {
    const ast_hash = [_]u8{0x01} ** 32;
    const valid_cert = ProofCertificate{
        .target_ast_digest = ast_hash,
        .contract_digest = ast_hash,
        .checker_id = 1,
        .witness_payload = "(model (define-fun x () Int 0))",
    };
    const policy = VerificationPolicy{ .require_anti_vacuity = true,
                                       .allowed_checkers = 2 };
    const res = try AdmissionGate.verifyClaimWithChecker(
        std.testing.allocator, ast_hash, ast_hash, valid_cert, policy,
        TrustedChecker{ .runFn = stubSmtLike });
    try std.testing.expectEqual(Eq2.T, res.eq2_status);
    try std.testing.expectEqual(@as(u1, 1), res.e_value);
}

test "CONF-04: анти-вакуумный шлюз захлопывается (вердикт внешнего чекера)" {
    const ast_hash = [_]u8{0x01} ** 32;
    const vacuous_cert = ProofCertificate{
        .target_ast_digest = ast_hash,
        .contract_digest = ast_hash,
        .checker_id = 1,
        .witness_payload = &[_]u8{ 0xCC, 0, 0, 0, 0, 0, 0, 0 },
    };
    const policy = VerificationPolicy{ .require_anti_vacuity = true,
                                       .allowed_checkers = 2 };
    try std.testing.expectError(GateError.PolicyViolation,
        AdmissionGate.verifyClaimWithChecker(
            std.testing.allocator, ast_hash, ast_hash, vacuous_cert, policy,
            TrustedChecker{ .runFn = stubVacuous }));
}

test "политика: allowed_checkers — битовая маска 1 << checker_id" {
    const p = VerificationPolicy{ .require_anti_vacuity = true,
                                  .allowed_checkers = 2 };
    try std.testing.expect(p.allows(1)); // бит 1
    try std.testing.expect(!p.allows(0)); // бит 0
    try std.testing.expect(!p.allows(2)); // бит 2
}

test "доверие к пруверу: запрещённый checker_id отвергается" {
    const ast_hash = [_]u8{0x01} ** 32;
    const cert = ProofCertificate{
        .target_ast_digest = ast_hash,
        .contract_digest = ast_hash,
        .checker_id = 3, // не разрешён политикой ниже
        .witness_payload = "(model)",
    };
    const policy = VerificationPolicy{ .require_anti_vacuity = true,
                                       .allowed_checkers = 2 }; // разрешён только 1
    try std.testing.expectError(GateError.UntrustedChecker,
        AdmissionGate.verifyClaimWithChecker(
            std.testing.allocator, ast_hash, ast_hash, cert, policy,
            TrustedChecker{ .runFn = stubProved }));
}

