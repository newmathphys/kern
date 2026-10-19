//! РАЗДЕЛ 7 ЭНЦИКЛОПЕДИИ: CLI детерминированной симуляции сбоев.
//!
//! Запуск: `kern-dst [--seeds N] [--steps M]`
//! Печатает хеш трассы по каждому сиду, проверяет детерминизм (двойной прогон)
//! и инварианты безопасности. Ненулевой код возврата = инвариант нарушен.
const std = @import("std");
const dst = @import("next/dst_sim.zig");

pub fn main(init: std.process.Init) !void {
    var seeds: u64 = 10;
    var steps: usize = 50;
    var it = init.minimal.args.iterate();
    _ = it.next(); // имя программы
    while (it.next()) |arg| {
        if (std.mem.eql(u8, arg, "--seeds")) {
            if (it.next()) |v| seeds = std.fmt.parseInt(u64, v, 10) catch seeds;
        } else if (std.mem.eql(u8, arg, "--steps")) {
            if (it.next()) |v| steps = std.fmt.parseInt(usize, v, 10) catch steps;
        }
    }

    const alloc = std.heap.page_allocator;
    var bad: usize = 0;
    var caught_total: usize = 0;
    var s: u64 = 1;
    while (s <= seeds) : (s += 1) {
        const r = try dst.run(alloc, s, steps);
        caught_total += r.caught_tamper + r.caught_decay + r.caught_byzantine;
        var hex: [64]u8 = undefined;
        const h = std.fmt.bufPrint(&hex, "{x}", .{r.trace_hash}) catch "?";
        if (!r.inv.ok()) {
            bad += 1;
            std.debug.print("[DST] seed={d} НАРУШЕНИЕ: gate={d} contr={d} stale={d} tamper={d}\n", .{
                s, r.inv.gate_open_without_t, r.inv.contradiction_overwritten,
                r.inv.stale_kept_positive, r.inv.tamper_undetected,
            });
        } else {
            std.debug.print("[DST] seed={d} steps={d} trace={s}\n", .{ s, r.steps, h[0..16] });
        }
    }

    // ДЕТЕРМИНИЗМ: тот же seed обязан дать побитово тот же хеш.
    const a = try dst.run(alloc, 42, steps);
    const b = try dst.run(alloc, 42, steps);
    const det = std.mem.eql(u8, &a.trace_hash, &b.trace_hash);

    std.debug.print("[DST] seeds={d} steps={d} инварианты={s} детерминизм={s} перехватов={d}\n", .{
        seeds, steps * seeds,
        if (bad == 0) "OK" else "НАРУШЕНЫ",
        if (det) "ДА" else "НЕТ",
        caught_total,
    });
    if (bad != 0 or !det or caught_total == 0) std.process.exit(1);
}
