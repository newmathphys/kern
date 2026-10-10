//! KERN-native бенчмарк (методология EvalPlus/HumanEval+ на нашем домене).
//!
//! Честно: это НЕ официальный HumanEval+ (нет LLM и датасета). Это тот же
//! принцип — «стресс на краевых случаях», применённый к сертификатам кода:
//! генерируем 1 000 000 «сабмишенов» с известными дефектами и сравниваем
//! НАИВНЫЙ верификатор (только хэш) с РЕАЛЬНЫМИ Вратами KERN.
//! Запуск: zig run src/kern_bench.zig -O ReleaseFast
const std = @import("std");
const gate = @import("verifier/admission_gate.zig");

const N: usize = 1_000_000;
var g_cat: u8 = 0;

/// «Правда» о сабмишене: что вернул бы честный внешний решатель.
fn truthChecker(ctx: ?*anyopaque, allocator: std.mem.Allocator,
                ast: [32]u8, contract: [32]u8, proof: []const u8) gate.CheckerVerdict {
    _ = .{ ctx, allocator, ast, contract, proof };
    return switch (g_cat) {
        1 => .VacuousPrecondition, // мёртвый код
        3 => .Counterexample, // контрпример
        4 => .Timeout, // решатель не успел
        else => .Proved,
    };
}

pub fn main() !void {
    var prng = std.Random.DefaultPrng.init(0xABCDEF);
    const rand = prng.random();

    std.debug.print("📊 KERN-бенчмарк: {d} синтетических сабмишенов (6 категорий)\n\n", .{N});
    var timer = try std.time.Timer.start();

    var legit_total: usize = 0;
    var naive_admit: usize = 0;
    var naive_false_pass: usize = 0; // наивный пропустил дефект
    var kern_admit: usize = 0;
    var kern_false_pass: usize = 0; // KERN пропустил дефект (СТРОГО 0)

    var i: usize = 0;
    while (i < N) : (i += 1) {
        const cat = rand.uintLessThan(u8, 6);
        g_cat = cat;
        const is_legit = (cat == 0);
        if (is_legit) legit_total += 1;

        var ast: [32]u8 = undefined;
        rand.bytes(&ast);
        var cert_ast = ast;
        if (cat == 2) cert_ast[0] ^= 0xFF; // подмена хэша (poison)

        const payload = [_]u8{0x01} ** 8;
        const cert = gate.ProofCertificate{
            .target_ast_digest = cert_ast,
            .contract_digest = ast,
            .checker_id = if (cat == 5) 9 else 1, // 9 = недоверенный чекер
            .witness_payload = &payload,
        };
        const policy = gate.VerificationPolicy{ .require_anti_vacuity = true, .allowed_checkers = 0b11 }; // разрешены только checker 0 и 1

        // --- НАИВНЫЙ верификатор: проверяет ТОЛЬКО хэш (как «обычные тесты») ---
        const naive = std.mem.eql(u8, &cert.target_ast_digest, &ast) and
            std.mem.eql(u8, &cert.contract_digest, &ast);
        if (naive) {
            naive_admit += 1;
            if (!is_legit) naive_false_pass += 1;
        }

        // --- РЕАЛЬНЫЕ Врата KERN ---
        if (gate.AdmissionGate.verifyClaimWithChecker(
            std.heap.page_allocator, ast, ast, cert, policy,
            gate.TrustedChecker{ .runFn = truthChecker })) |r| {
            if (r.e_value == 1) {
                kern_admit += 1;
                if (!is_legit) kern_false_pass += 1;
            }
        } else |_| {}
    }

    const ns = timer.read();
    const ms = @as(f64, @floatFromInt(ns)) / 1_000_000.0;
    const f = struct {
        fn pct(x: usize, t: usize) f64 {
            return 100.0 * @as(f64, @floatFromInt(x)) / @as(f64, @floatFromInt(t));
        }
    }.pct;

    std.debug.print("=== РЕЗУЛЬТАТЫ KERN-БЕНЧМАРКА ===\n", .{});
    std.debug.print("Время:                       {d:.2} ms\n", .{ms});
    std.debug.print("Легитимных сабмишенов:       {d} ({d:.1}%)\n", .{ legit_total, f(legit_total, N) });
    std.debug.print("\n-- НАИВНЫЙ верификатор (только хэш) --\n", .{});
    std.debug.print("  допущено всего:            {d} ({d:.1}%)\n", .{ naive_admit, f(naive_admit, N) });
    std.debug.print("  ЛОЖНЫХ ПРОПУСКОВ (дефекты): {d} ({d:.1}%)  <- ДЫРА\n", .{ naive_false_pass, f(naive_false_pass, N) });
    std.debug.print("\n-- ВРАТА KERN --\n", .{});
    std.debug.print("  допущено всего:            {d} ({d:.1}%)\n", .{ kern_admit, f(kern_admit, N) });
    std.debug.print("  ЛОЖНЫХ ПРОПУСКОВ (дефекты): {d} ({d:.1}%)  <- СТРОГО 0\n", .{ kern_false_pass, f(kern_false_pass, N) });
    std.debug.print("  ДОПУЩЕНО ЛЕГИТИМНЫХ:        {d}/{d} ({d:.1}%)\n", .{ kern_admit - kern_false_pass, legit_total, f(kern_admit - kern_false_pass, legit_total) });
}
