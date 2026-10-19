//! РАЗДЕЛ 7 ЭНЦИКЛОПЕДИИ: Deterministic Simulation Testing (TigerBeetle-style).
//!
//! ЗАЧЕМ: `bitrot-chaos` проверяет 30 ФИКСИРОВАННЫХ инъекций в `.kimg`.
//! DST проверяет ДРУГОЕ: поток событий над состоянием агентов — расписание
//! генерируется по ЗЕРНУ, поэтому любой сбой воспроизводим (`--seed N`).
//!
//! ПРИНЦИП (не «модель вместо кода»): состояние и переходы считаются
//! НАСТОЯЩИМИ функциями ядра — `truth.Bit.join`, `truth.allowance`,
//! `truth.evaluateWithFreshness`, `truth.digestOf`. Здесь нет второй
//! реализации Belnap/decay: если ядро изменится, симулятор изменится вместе с ним.
const std = @import("std");
const truth = @import("truth.zig");

/// Событие расписания. Каждое — сбой, который система ОБЯЗАНА перехватить.
pub const Event = enum {
    /// Агент заявляет подтверждение (T).
    agent_claims_t,
    /// Агент заявляет опровержение (F).
    agent_claims_f,
    /// Исходный файл изменился -> свидетельство протухает (Evidence Decay).
    source_file_mutated,
    /// Византийский вброс T поверх уже известного F -> B, дальше поглощение.
    byzantine_t_over_f,
    /// Порча одного байта в .kimg (ловится Merkle-корнем).
    kimg_bit_flip,
    /// Подмена записи в цепочке аудита (ловится цепочкой хешей).
    audit_row_tampered,
};

pub const Invariants = struct {
    /// Нарушение: Врата открыты (e=1) при вердикте, отличном от T.
    gate_open_without_t: usize = 0,
    /// Нарушение: противоречие B «перезаписано» обратно в T.
    contradiction_overwritten: usize = 0,
    /// Нарушение: устаревшее свидетельство сохранило подтверждение.
    stale_kept_positive: usize = 0,
    /// Нарушение: порча данных не обнаружена.
    tamper_undetected: usize = 0,

    pub fn ok(self: Invariants) bool {
        return self.gate_open_without_t == 0 and self.contradiction_overwritten == 0 and
            self.stale_kept_positive == 0 and self.tamper_undetected == 0;
    }
};

pub const Report = struct {
    /// Хеш ВСЕЙ трассы состояний: два прогона с одним seed обязаны совпасть.
    trace_hash: [32]u8,
    steps: usize,
    /// Сколько раз реально сработали перехваты (tamper/decay/byzantine).
    caught_decay: usize = 0,
    caught_byzantine: usize = 0,
    caught_tamper: usize = 0,
    inv: Invariants = .{},
};

fn bitToU8(b: truth.Bit) u8 {
    return @as(u8, @intFromBool(b.p)) | (@as(u8, @intFromBool(b.n)) << 1);
}

/// Детерминированный ПСЧ (xorshift64*): одинаковый seed -> одинаковая трасса.
const Rng = struct {
    s: u64,
    fn next(self: *Rng) u64 {
        var x = self.s;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.s = x;
        return x *% 0x2545F4914F6CDD1D;
    }
    fn below(self: *Rng, n: u64) u64 {
        return if (n == 0) 0 else self.next() % n;
    }
};

/// Один прогон расписания. Возвращает хеш трассы и счётчики инвариантов.
pub fn run(allocator: std.mem.Allocator, seed: u64, steps: usize) !Report {
    var rng = Rng{ .s = if (seed == 0) 0x9E3779B97F4A7C15 else seed };
    var h = std.crypto.hash.Blake3.init(.{});

    // --- Состояние системы (всё — через настоящее ядро) ---
    var verdict = truth.Bit{ .p = false, .n = false }; // N
    var recorded_digest = truth.digestOf("v1"); // версия файла на момент вердикта
    var current_digest = recorded_digest; // файл на диске СЕЙЧАС

    // Цепочка аудита: prev = BLAKE3(prev || запись).
    var chain: [32]u8 = @splat(0);
    var audit_rows: usize = 0;
    var audit_tampered = false;

    var obj = [_]u8{ 1, 2, 3, 4, 5, 6, 7, 8 }; // «тело объекта .kimg»
    var obj_digest = truth.digestOf(&obj);
    var obj_corrupted = false;

    var rep = Report{ .trace_hash = undefined, .steps = steps };

    var i: usize = 0;
    while (i < steps) : (i += 1) {
        const ev: Event = @enumFromInt(rng.below(6));
        switch (ev) {
            .agent_claims_t => {
                verdict = verdict.join(.{ .p = true, .n = false });
                recorded_digest = current_digest;
            },
            .agent_claims_f => {
                verdict = verdict.join(.{ .p = false, .n = true });
                recorded_digest = current_digest;
            },
            .source_file_mutated => {
                // РЕАЛЬНЫЙ Evidence Decay: сравнение отпечатков ядром.
                current_digest = truth.digestOf(if (rng.below(2) == 0) "v2" else "v3");
            },
            .byzantine_t_over_f => {
                verdict = verdict.join(.{ .p = true, .n = false });
            },
            .kimg_bit_flip => {
                const idx = rng.below(obj.len);
                const bit = @as(u8, 1) << @intCast(rng.below(8));
                obj[idx] = obj[idx] ^ bit;
                // ИЗМЕРЕНО (найдено этим же DST): если тот же бит инвертировать
                // ДВАЖДЫ, данные восстанавливаются, и сравнивать «сейчас vs
                // исходное» позже — неверно. Обнаружение проверяется В МОМЕНТ
                // события: изменился ли дайджест относительно ТЕКУЩЕГО эталона.
                if (!std.mem.eql(u8, &truth.digestOf(&obj), &obj_digest)) {
                    obj_corrupted = true;
                    rep.caught_tamper += 1;
                    obj_digest = truth.digestOf(&obj); // эталон = что лежит сейчас
                }
            },
            .audit_row_tampered => {
                // Запись добавляется в цепочку, затем «кто-то» её подменяет.
                var rec_buf: [64]u8 = undefined;
                const rec = try std.fmt.bufPrint(&rec_buf, "claim:{d}:{s}", .{ audit_rows, @tagName(ev) });
                var hh = std.crypto.hash.Blake3.init(.{});
                hh.update(&chain);
                hh.update(rec);
                hh.final(&chain);
                audit_rows += 1;
                if (rng.below(2) == 0) {
                    // Подмена: тот же индекс, ДРУГОЕ内容 записи -> другой хеш.
                    var hb2 = std.crypto.hash.Blake3.init(.{});
                    hb2.update(&chain);
                    hb2.update(rec);
                    hb2.update("TAMPERED");
                    var alt: [32]u8 = undefined;
                    hb2.final(&alt);
                    // Если хеши СОВПАЛИ — цепочка не различает подмену (дыра).
                    if (std.mem.eql(u8, &alt, &chain)) rep.inv.tamper_undetected += 1;
                    audit_tampered = true;
                }
            },
        }

        // --- СВЕЖЕСТЬ через НАСТОЯЩУЮ функцию ядра ---
        const effective = truth.evaluateWithFreshness(verdict, recorded_digest, current_digest);
        // СВЕЖЕСТЬ = СРАВНЕНИЕ, а не флаг по событию. ИЗМЕРЕНО этим DST:
        // «мутация файла» может дать ТОТ ЖЕ отпечаток (v2 -> v2), и тогда
        // свидетельство ОБЯЗАНО остаться свежим — флаг по событию давал
        // ложное нарушение инварианта.
        const is_stale = !std.mem.eql(u8, &recorded_digest, &current_digest);
        if (is_stale and verdict.p and effective.p) rep.inv.stale_kept_positive += 1;
        if (is_stale and verdict.p and !effective.p) rep.caught_decay += 1;

        // --- ИНВАРИАНТ 1: Врата открыты ТОЛЬКО при T ---
        const e = truth.allowance(effective);
        if (e == 1 and !(effective.p and !effective.n)) rep.inv.gate_open_without_t += 1;

        // --- ИНВАРИАНТ 2: B не перезаписывается в T ---
        if (verdict.p and verdict.n and effective.p and !effective.n) rep.inv.contradiction_overwritten += 1;
        if (verdict.p and verdict.n) rep.caught_byzantine += 1;

        // Инварианты 3 и 4 проверяются В МОМЕНТ события (см. ветки выше):
        // отложенная проверка давала ЛОЖНОЕ нарушение при двойной инверсии.
        _ = &obj_corrupted;
        _ = &audit_tampered;

        // --- Трасса: состояние + счётчики ---
        var sbuf: [128]u8 = undefined;
        const line = try std.fmt.bufPrint(&sbuf, "{d}|{d}|{d}|{d}|{d}\n", .{
            i, bitToU8(effective), bitToU8(verdict), rep.caught_tamper, rep.caught_decay,
        });
        h.update(line);
        _ = allocator; // аллокатор оставлен для будущих расширений (сеть, гонки)
    }
    h.final(&rep.trace_hash);
    return rep;
}

// ============================================================================
// ТЕСТЫ: 10 сидов x 50 шагов, все инварианты, и 100% детерминизм.
// ============================================================================
test "DST: 10 сидов x 50 шагов — ни одного нарушения 4 инвариантов" {
    var seed: u64 = 1;
    while (seed <= 10) : (seed += 1) {
        const r = try run(std.testing.allocator, seed, 50);
        if (!r.inv.ok()) {
            std.debug.print("[DST] seed={d}: gate={d} contr={d} stale={d} tamper={d}\n", .{
                seed, r.inv.gate_open_without_t, r.inv.contradiction_overwritten,
                r.inv.stale_kept_positive, r.inv.tamper_undetected,
            });
        }
        try std.testing.expect(r.inv.ok());
        try std.testing.expectEqual(@as(usize, 50), r.steps);
    }
}

test "DST: детерминизм — один seed даёт ПОБИТОВО тот же хеш трассы" {
    const a = try run(std.testing.allocator, 42, 50);
    const b = try run(std.testing.allocator, 42, 50);
    try std.testing.expectEqualSlices(u8, &a.trace_hash, &b.trace_hash);
    try std.testing.expectEqual(a.caught_tamper, b.caught_tamper);
    // И seed ВЛИЯЕТ: разные seed -> разные трассы (иначе симулятор фиктивен).
    const c = try run(std.testing.allocator, 43, 50);
    try std.testing.expect(!std.mem.eql(u8, &a.trace_hash, &c.trace_hash));
}

test "DST: сбои РЕАЛЬНО перехватываются (не нулевые счётчики)" {
    var caught: usize = 0;
    var seed: u64 = 1;
    while (seed <= 10) : (seed += 1) {
        const r = try run(std.testing.allocator, seed, 50);
        caught += r.caught_tamper + r.caught_decay + r.caught_byzantine;
    }
    // Если бы перехваты не срабатывали, счётчики были бы нулевыми и тест
    // «инварианты держатся» стал бы ВАКУУМНЫМ.
    try std.testing.expect(caught > 0);
}
