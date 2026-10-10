const std = @import("std");
const Eq2 = @import("../core/eq2.zig").Eq2;

pub const GateError = error{
    AstHashMismatch,
    ContractHashMismatch,
    UntrustedChecker,
    FakeWitnessRejected,
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
    allowed_checkers: u32,
};

/// Результат прохода через Шлюз Истины
pub const AdmissionResult = struct {
    eq2_status: Eq2,
    e_value: u1, // 1 = пропущено в прод
};

/// Внутренние статусы прувера. Объявлен на уровне ФАЙЛА (тест-сьют обращается
/// как `gate.CheckerVerdict`; вложенный в AdmissionGate был недоступен).
pub const CheckerVerdict = enum { Proved, Counterexample, VacuousPrecondition, Timeout, Unknown };

pub const AdmissionGate = struct {
    /// Главная функция допуска (Truth Gate)
    pub fn verifyClaim(
        actual_ast_digest: [32]u8,
        actual_contract_digest: [32]u8,
        cert: ProofCertificate,
        policy: VerificationPolicy,
    ) !AdmissionResult {

        // 1. Криптографическая привязка (PC3 Binding Check).
        // Если ИИ поменял код, но подсунул старый сертификат — отказ.
        if (!std.mem.eql(u8, &actual_ast_digest, &cert.target_ast_digest)) {
            return GateError.AstHashMismatch;
        }
        if (!std.mem.eql(u8, &actual_contract_digest, &cert.contract_digest)) {
            return GateError.ContractHashMismatch;
        }

        // 2. Проверка доверия к пруверу
        const checker_mask = @as(u32, 1) << @as(u5, @truncate(cert.checker_id));
        if ((policy.allowed_checkers & checker_mask) == 0) {
            return GateError.UntrustedChecker;
        }

        // 3. «Внешний» прувер
        const checker_verdict = try runTrustedChecker(cert.checker_id,
                                                      cert.witness_payload, policy);

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

    /// 🔴 ИЗВЕСТНАЯ УЯЗВИМОСТЬ (см. docs/KERN34_AUDIT.md, АТАКА 1).
    ///
    /// Эта функция НЕ вызывает Z3 или Lean. Она читает вердикт ИЗ БАЙТА
    /// ПРИСЛАННОЙ ПОЛЕЗНОЙ НАГРУЗКИ, то есть из данных, которыми управляет ИИ:
    ///
    ///     const magic = payload[0];          // <-- байт от ИИ
    ///     if (magic == 0xAA) return .Proved; // <-- ИИ управляет вердиктом
    ///
    /// Доказано на деле: сертификат с ОДНИМ байтом 0xAA даёт `e=1` —
    /// код допускается в прод без единого доказательства.
    ///
    /// ЧТО НУЖНО: вердикт обязан приходить ИЗВНЕ (реальный вызов решателя с
    /// тайм-аутом и изоляцией), а не из полезной нагрузки сертификата.
    fn runTrustedChecker(checker_id: u32, payload: []const u8,
                         policy: VerificationPolicy) !CheckerVerdict {
        _ = checker_id;
        // Отсекаются только СЛИШКОМ КОРОТКИЕ свидетели (< 8 байт).
        // Строка из 26 байт пройдёт и даст .Unknown -> N (безопасно, но
        // это НЕ «отклонение фейка», как заявлено в спецификации).
        if (payload.len < 8) return GateError.FakeWitnessRejected;

        const magic = payload[0];
        if (magic == 0xAA) return .Proved;
        if (magic == 0xBB) return .Counterexample;
        if (magic == 0xCC and policy.require_anti_vacuity) return .VacuousPrecondition;
        return .Unknown;
    }
};

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

test "CONF-30.4: отвергается короткий текстовый свидетель" {
    const ast_hash = [_]u8{0x01} ** 32;
    const bad_cert = ProofCertificate{
        .target_ast_digest = ast_hash,
        .contract_digest = ast_hash,
        .checker_id = 1,
        .witness_payload = "proved", // 6 байт < 8
    };
    const policy = VerificationPolicy{ .require_anti_vacuity = true,
                                       .allowed_checkers = 0xFFFFFFFF };
    try std.testing.expectError(GateError.FakeWitnessRejected,
        AdmissionGate.verifyClaim(ast_hash, ast_hash, bad_cert, policy));
}

test "CONF-04: анти-вакуумный шлюз захлопывается" {
    const ast_hash = [_]u8{0x01} ** 32;
    const vacuous_cert = ProofCertificate{
        .target_ast_digest = ast_hash,
        .contract_digest = ast_hash,
        .checker_id = 1,
        .witness_payload = &[_]u8{ 0xCC, 0, 0, 0, 0, 0, 0, 0 },
    };
    const policy = VerificationPolicy{ .require_anti_vacuity = true,
                                       .allowed_checkers = 0xFFFFFFFF };
    try std.testing.expectError(GateError.PolicyViolation,
        AdmissionGate.verifyClaim(ast_hash, ast_hash, vacuous_cert, policy));
}

test "успех: валидный пруф даёт Eq2.T и e=1" {
    const ast_hash = [_]u8{0x01} ** 32;
    const valid_cert = ProofCertificate{
        .target_ast_digest = ast_hash,
        .contract_digest = ast_hash,
        .checker_id = 1,
        .witness_payload = &[_]u8{ 0xAA, 0, 0, 0, 0, 0, 0, 0 },
    };
    // allowed_checkers = 2 — это бит для checker_id = 1
    const policy = VerificationPolicy{ .require_anti_vacuity = true,
                                       .allowed_checkers = 2 };
    const res = try AdmissionGate.verifyClaim(ast_hash, ast_hash, valid_cert, policy);
    try std.testing.expectEqual(Eq2.T, res.eq2_status);
    try std.testing.expectEqual(@as(u1, 1), res.e_value);
}

test "УЯЗВИМОСТЬ (фиксируем): ОДИН БАЙТ даёт e=1 без доказательства" {
    // Этот тест ЗЕЛЁНЫЙ и ДОКУМЕНТИРУЕТ уязвимость: он проходит, потому что
    // шлюз действительно обходится одним байтом 0xAA. Когда уязвимость
    // устранят, тест станет КРАСНЫМ — тогда его надо заменить на expectError.
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
    try std.testing.expectEqual(@as(u1, 1), res.e_value);
}

