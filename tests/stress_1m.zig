// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: процедурный стресс-тест на 1 000 000 «проектов» (Тактика 3).
//!
//! ЧЕСТНАЯ ОГОВОРКА: `false_positives` здесь = 0 ПО ПОСТРОЕНИЮ — маппинг
//! устроен так, что e=1 возможен лишь при is_legit=true. Этот тест доказывает
//! ПРОПУСКНУЮ СПОСОБНОСТЬ и отсутствие падений в памяти, а НЕ безопасность.
//! Настоящая проверка безопасности — в tests/stress_real.zig (бьёт по реальным
//! модулям EQ2 / AdmissionGate / KimgHeader).
const std = @import("std");
const compat = @import("compat");

pub fn main(init: std.process.Init) !void {
    // Zig 0.17: файловый I/O требует setIo() до первого вызова.
    compat.setIo(init.io);
    const total_projects: usize = 1_000_000;
    var prng = std.Random.DefaultPrng.init(0x1337);
    const rand = prng.random();

    std.debug.print("🚀 Стресс-тест на 1,000,000 проектов в памяти...\n", .{});

    var timer = compat.Timer.start();
    var legitimate_passes: usize = 0;
    var caught_vacuous: usize = 0;
    var caught_conflicts: usize = 0;
    var caught_poison: usize = 0;
    var false_positives: usize = 0;

    for (0..total_projects) |i| {
        const defect_type = rand.uintLessThan(u8, 4);
        const is_legit = (defect_type == 0);
        const has_witness = (defect_type != 1);
        const hash_matches = (defect_type != 2);
        const is_conflict = (defect_type == 3);

        const belnap_is_true = !is_conflict;
        const gate_passed = has_witness and hash_matches;
        const e_val: u1 = if (belnap_is_true and gate_passed) 1 else 0;

        if (e_val == 1) {
            if (!is_legit) false_positives += 1;
            legitimate_passes += 1;
        } else {
            if (defect_type == 1) caught_vacuous += 1;
            if (defect_type == 2) caught_poison += 1;
            if (defect_type == 3) caught_conflicts += 1;
        }

        if (i % 250_000 == 0 and i > 0) {
            std.debug.print("  -> Обработано {d} проектов...\n", .{i});
        }
    }

    const elapsed_ns = timer.read();
    const elapsed_ms = @as(f64, @floatFromInt(elapsed_ns)) / 1_000_000.0;
    const ops_sec = (@as(f64, @floatFromInt(total_projects)) / @as(f64, @floatFromInt(elapsed_ns))) * 1_000_000_000.0;

    std.debug.print("\n=== РЕЗУЛЬТАТЫ СТРЕСС-ТЕСТА KERN (1,000,000 ПРОЕКТОВ) ===\n", .{});
    std.debug.print("Время выполнения:         {d:.2} ms\n", .{elapsed_ms});
    std.debug.print("Пропускная способность:   {d:.0} проектов/сек\n", .{ops_sec});
    std.debug.print("Легитимно допущено (e=1): {d}\n", .{legitimate_passes});
    std.debug.print("Отловлено вакуумных атак: {d}\n", .{caught_vacuous});
    std.debug.print("Отловлено подмен AST:     {d}\n", .{caught_poison});
    std.debug.print("Изолировано конфликтов:   {d}\n", .{caught_conflicts});
    std.debug.print("ЛОЖНЫЕ ПРОПУСКИ (БАГИ):   {d}\n", .{false_positives});
    // K2: ложные пропуски — инвариант, а не текст.
    if (false_positives != 0) {
        std.debug.print("[!] ИНВАРИАНТ НАРУШЕН: {d} ложных пропусков (ожидалось 0)\n", .{false_positives});
        std.process.exit(2);
    }
}
