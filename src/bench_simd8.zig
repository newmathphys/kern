//! Замер пропускной способности BLAKE3 SIMD-8 (8 полос @Vector(8,u32)).
//! Зачем: `align(32)` у рабочих буферов — правка ради выравнивания под
//! 256-битные загрузки. Здесь ИЗМЕРЯЕТСЯ реальная скорость, а не заявляется.
const std = @import("std");
const b3 = @import("core/blake3_simd8.zig");

const OBJ = 4096;                 // объект 4 КиБ (типичный чанк .kimg)
const TOTAL_MB = 64;

pub fn main(init: std.process.Init) !void {
    _ = init;
    const alloc = std.heap.page_allocator;
    const iters = (TOTAL_MB * 1024 * 1024) / (OBJ * 8);
    var buf = try alloc.alloc(u8, OBJ * 8);
    defer alloc.free(buf);
    // Детерминированное содержимое (не нули: хеш нулей не отражает нагрузку).
    for (buf, 0..) |*b, i| b.* = @truncate(i *% 2654435761);

    var inputs: [8][]const u8 = undefined;
    for (0..8) |i| inputs[i] = buf[i * OBJ ..][0..OBJ];
    var out: [8][32]u8 = undefined;

    // Прогрев (кэш, страницы).
    var w: usize = 0;
    while (w < 8) : (w += 1) b3.hash8SmallObjects(inputs, &out);

    const io = std.Io.Threaded.global_single_threaded.io();
    const t0 = std.Io.Clock.now(.awake, io).nanoseconds;
    var i: usize = 0;
    while (i < iters) : (i += 1) b3.hash8SmallObjects(inputs, &out);
    const t1 = std.Io.Clock.now(.awake, io).nanoseconds;
    const elapsed: f64 = @as(f64, @floatFromInt(t1 - t0)) / 1e9;

    const bytes: f64 = @floatFromInt(iters * OBJ * 8);
    const gbs = bytes / elapsed / (1024.0 * 1024.0 * 1024.0);
    std.debug.print("[bench] SIMD-8 BLAKE3: {d:.1} MB за {d:.3} c -> {d:.2} GB/s ({d:.0} MB/s)\n",
        .{ TOTAL_MB, elapsed, gbs, gbs * 1024.0 });
}
