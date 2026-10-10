// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: УСИЛЕННЫЙ стресс-тест — бьёт по РЕАЛЬНЫМ модулям ядра.
//! В отличие от tests/stress_1m.zig (где 0 FPR by construction), здесь
//! «0 ложных пропусков» — настоящий результат: гоняются настоящие EQ2,
//! AdmissionGate и KimgHeader на случайных входах.
//! Запуск: zig run src/stress_real.zig -O ReleaseFast
const std = @import("std");
const eq2 = @import("core/eq2.zig");
const Eq2 = eq2.Eq2;
const gate = @import("verifier/admission_gate.zig");
const kimg = @import("core/kimg_reader.zig");
const obj = @import("core/object_entry.zig");

const N: usize = 1_000_000;

fn rndEq2(rand: std.Random) Eq2 {
    return @enumFromInt(@as(u2, @truncate(rand.uintLessThan(u8, 4))));
}

pub fn main() !void {
    var prng = std.Random.DefaultPrng.init(0xDEADBEEF);
    const rand = prng.random();

    std.debug.print("🔬 УСИЛЕННЫЙ стресс-тест: {d} итераций на каждый модуль\n\n", .{N});
    var timer = try std.time.Timer.start();

    // --- 1. АЛГЕБРА БЕЛНАПА: законы решётки на случайных тройках ---
    var law_violations: usize = 0;
    var i: usize = 0;
    while (i < N) : (i += 1) {
        const a = rndEq2(rand);
        const b = rndEq2(rand);
        const c = rndEq2(rand);
        if (Eq2.joinK(a, b) != Eq2.joinK(b, a)) law_violations += 1; // коммутативность
        if (Eq2.joinK(Eq2.joinK(a, b), c) != Eq2.joinK(a, Eq2.joinK(b, c))) law_violations += 1; // ассоциативность
        if (eq2.notB(eq2.andT(a, b)) != eq2.orT(eq2.notB(a), eq2.notB(b))) law_violations += 1; // де Морган
        if (eq2.notB(eq2.notB(a)) != a) law_violations += 1; // инволюция
        if (Eq2.joinK(a, a) != a) law_violations += 1; // идемпотентность
    }

    // --- 2. KIMG-ЗАГОЛОВОК: случайные байты (фаззинг парсера) ---
    var hdr_ok: usize = 0;
    var hdr_rej: usize = 0;
    i = 0;
    while (i < N) : (i += 1) {
        var buf: [128]u8 = undefined;
        rand.bytes(&buf);
        if (kimg.KimgHeader.parse(&buf, rand.int(u64))) |_| {
            hdr_ok += 1;
        } else |_| {
            hdr_rej += 1;
        }
    }

    // --- 3. ДЕСКРИПТОР .kimg: случайные 96 байт ---
    var obj_ok: usize = 0;
    var obj_rej: usize = 0;
    i = 0;
    while (i < N) : (i += 1) {
        var buf: [96]u8 = undefined;
        rand.bytes(&buf);
        if (obj.ObjectEntry.parseSafe(&buf)) |_| {
            obj_ok += 1;
        } else |_| {
            obj_rej += 1;
        }
    }

    // --- 4. ВРАТА ИСТИНЫ: случайные сертификаты БЕЗ внешнего чекера ---
    var gate_open: usize = 0; // НАСТОЯЩИЕ ложные пропуски
    var gate_closed: usize = 0;
    i = 0;
    while (i < N) : (i += 1) {
        var ast: [32]u8 = undefined;
        rand.bytes(&ast);
        var payload: [16]u8 = undefined;
        rand.bytes(&payload);
        const cert = gate.ProofCertificate{
            .target_ast_digest = ast,
            .contract_digest = ast,
            .checker_id = rand.uintLessThan(u32, 8),
            .witness_payload = &payload,
        };
        const policy = gate.VerificationPolicy{ .require_anti_vacuity = true, .allowed_checkers = 0xFFFFFFFF };
        if (gate.AdmissionGate.verifyClaim(ast, ast, cert, policy)) |r| {
            if (r.e_value == 1) gate_open += 1 else gate_closed += 1;
        } else |_| {
            gate_closed += 1;
        }
    }

    const ns = timer.read();
    const ms = @as(f64, @floatFromInt(ns)) / 1_000_000.0;
    const total_ops = N * 4;
    const ops_sec = (@as(f64, @floatFromInt(total_ops)) / @as(f64, @floatFromInt(ns))) * 1e9;

    std.debug.print("=== РЕЗУЛЬТАТЫ (РЕАЛЬНЫЙ КОД KERN) ===\n", .{});
    std.debug.print("Время:                      {d:.2} ms\n", .{ms});
    std.debug.print("Пропускная способность:     {d:.0} проверок/сек\n", .{ops_sec});
    std.debug.print("[1] Белнап, нарушений законов: {d} (СТРОГО 0)\n", .{law_violations});
    std.debug.print("[2] KIMG-заголовок: принято {d}, отвергнуто {d} (паник нет)\n", .{ hdr_ok, hdr_rej });
    std.debug.print("[3] Дескриптор:     принято {d}, отвергнуто {d} (паник нет)\n", .{ obj_ok, obj_rej });
    std.debug.print("[4] Врата: закрыто {d}, ОТКРЫТО без доказательства: {d} (СТРОГО 0)\n", .{ gate_closed, gate_open });
}
