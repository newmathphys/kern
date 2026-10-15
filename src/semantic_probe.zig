// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by the GNU Affero General Public License v3.0 ONLY
// (AGPL-3.0-only), or a commercial license from the copyright holder. See LICENSE.

//! KERN: СЕМАНТИЧЕСКИЙ ЗОНД ДЛЯ TRANSLATION VALIDATION.
//!
//! ПРОБЛЕМА (binary-level soundness): Lean доказывает математику, Zig
//! компилируется в LLVM IR, LLVM — в машинный код. Если оптимизатор LLVM
//! ошибётся, доказанный инвариант может сломаться В БИНАРНИКЕ.
//!
//! ЧТО ДЕЛАЕМ (практический translation validation, не полный Alive2):
//! прогоняем ОДИН И ТОТ ЖЕ набор вычислений через бинарники, собранные с
//! РАЗНЫМИ уровнями оптимизации (Debug / ReleaseSafe / ReleaseFast), и
//! сравниваем КАНОНИЧЕСКИЙ ДАЙДЖЕСТ всех результатов.
//! Совпадение = оптимизации LLVM не изменили семантику на этом наборе.
//!
//! Зонд детерминирован: без времени, адресов, рандома и внешнего решателя.
const std = @import("std");
const compat = @import("compat");
const eq2 = @import("core/eq2.zig");
const Eq2 = eq2.Eq2;
const KimgHeader = @import("core/kimg_reader.zig").KimgHeader;
const ObjectEntry = @import("core/object_entry.zig").ObjectEntry;
const KernFS = @import("core/kernfs_router.zig").KernFS;
const absint = @import("verifier/abstract_interp.zig");
const dtmc = @import("verifier/dtmc.zig");
const redos = @import("verifier/redos.zig");
const nonint = @import("verifier/noninterference.zig");

/// Накопитель канонического дайджеста.
const Digest = struct {
    h: std.crypto.hash.sha2.Sha256,

    fn init() Digest {
        return .{ .h = std.crypto.hash.sha2.Sha256.init(.{}) };
    }
    fn add(self: *Digest, bytes: []const u8) void {
        self.h.update(bytes);
    }
    fn addU64(self: *Digest, v: u64) void {
        var b: [8]u8 = undefined;
        std.mem.writeInt(u64, &b, v, .little);
        self.h.update(&b);
    }
    fn addI64(self: *Digest, v: i64) void {
        self.addU64(@bitCast(v));
    }
    /// Канонизация: округляем до 1e-12, чтобы исключить разницу порядков
    /// операций с плавающей точкой между уровнями оптимизации.
    ///
    /// ЗАЩИТА: `@intFromFloat` ПАНИКУЕТ на NaN/inf и на значениях вне
    /// диапазона i64 (тот же класс, что DoS в truth.zig). Для нечисловых
    /// результатов пишем различимую канарейку — она тоже детерминирована.
    fn addF64(self: *Digest, v: f64) void {
        if (!std.math.isFinite(v)) {
            self.addU64(0xDEAD_BEEF_DEAD_BEEF);
            return;
        }
        const scaled = @round(v * 1e12);
        if (!std.math.isFinite(scaled) or scaled > 9.2233720368547758e18 or scaled < -9.2233720368547758e18) {
            self.addU64(0xCAFE_BABE_CAFE_BABE);
            return;
        }
        self.addI64(@intFromFloat(scaled));
    }
    fn final(self: *Digest) [32]u8 {
        var out: [32]u8 = undefined;
        self.h.final(&out);
        return out;
    }
};

fn buildGolden(alloc: std.mem.Allocator) ![]u8 {
    const content = "hello probe";
    const pool = "a.zig\x00" ++ content;
    var obj: [96]u8 = @as([96]u8, @splat(0));
    var dig: [32]u8 = undefined;
    std.crypto.hash.Blake3.hash(content, dig[0..32], .{});
    @memcpy(obj[0..32], &dig);
    std.mem.writeInt(u64, obj[32..40], 6, .little);
    std.mem.writeInt(u64, obj[40..48], content.len, .little);
    std.mem.writeInt(u64, obj[48..56], content.len, .little);
    std.mem.writeInt(u32, obj[56..60], 0x0002, .little);
    std.mem.writeInt(u16, obj[60..62], 0x0002, .little);
    std.mem.writeInt(u32, obj[64..68], 0, .little);
    std.mem.writeInt(u32, obj[68..72], 1, .little);

    var root: [32]u8 = undefined;
    ObjectEntry.computeRootHash(&[_][96]u8{obj}, &root);

    var header: [128]u8 = @as([128]u8, @splat(0));
    @memcpy(header[0..8], "KIMG\r\n\x1a\n");
    std.mem.writeInt(u16, header[8..10], 1, .little);
    std.mem.writeInt(u32, header[20..24], 1, .little); // hash_algo = SHA-256
    std.mem.writeInt(u16, header[10..12], 3, .little);
    std.mem.writeInt(u32, header[12..16], 128, .little);
    std.mem.writeInt(u64, header[32..40], 128, .little);
    std.mem.writeInt(u64, header[40..48], 96, .little);
    std.mem.writeInt(u64, header[48..56], 1, .little);
    std.mem.writeInt(u64, header[56..64], 224, .little);
    @memcpy(header[64..96], &root);

    var out = std.array_list.Managed(u8).init(alloc);
    try out.appendSlice(&header);
    try out.appendSlice(&obj);
    try out.appendSlice(pool);
    return out.toOwnedSlice();
}

pub fn main(init: std.process.Init) !void {
    // Zig 0.17: файловый I/O требует setIo() до первого вызова.
    compat.setIo(init.io);
    var gpa = std.heap.DebugAllocator(.{}){};
    defer _ = gpa.deinit();
    const alloc = gpa.allocator();

    var d = Digest.init();

    // 1. Решётка Белнапа B₄ — полная таблица join/meet/not.
    const vals = [_]Eq2{ .N, .T, .F, .B };
    for (vals) |a| {
        for (vals) |b| {
            d.add(&[_]u8{@intFromEnum(Eq2.joinK(a, b))});
            d.add(&[_]u8{@intFromEnum(Eq2.meetK(a, b))});
            d.add(&[_]u8{@intFromEnum(eq2.notB(a))});
        }
    }

    // 2. .kimg: разбор заголовка + Merkle + KERNFS-чтение.
    const img = try buildGolden(alloc);
    defer alloc.free(img);
    const hdr: *const [128]u8 = @ptrCast(img.ptr);
    const h = try KimgHeader.parse(hdr, img.len);
    d.addU64(h.object_count);
    d.addU64(h.object_table_offset);
    KimgHeader.verifyMerkleRoot(img, h) catch d.add("MERKLE-FAIL");
    d.add(&h.root_digest);

    var fs = try KernFS.mountFromBytes(alloc, img);
    defer fs.deinit();
    if (fs.read("/raw/a.zig")) |node| d.add(node.raw_slice) else |_| d.add("READ-FAIL");
    if (fs.read("/../etc/passwd")) |_| d.add("TRAVERSAL-ALLOWED") else |_| d.add("TRAVERSAL-DENIED");
    if (fs.read("/raw/missing")) |_| d.add("MISSING-ALLOWED") else |_| d.add("MISSING-DENIED");

    // 3. Дескриптор объекта.
    const entry: *const [96]u8 = @ptrCast(img.ptr + 128);
    const oe = try ObjectEntry.parseSafe(entry);
    d.addU64(oe.payload_offset);
    d.addU64(oe.compressed_size);
    d.addU64(oe.type_id);

    // 4. Абстрактная интерпретация (инварианты циклов).
    inline for (.{ .{ 0, 1, 10 }, .{ 0, 2, 10 }, .{ 5, 3, 20 } }) |c| {
        const r = absint.analyzeLinearLoop(c[0], c[1], c[2]);
        d.addI64(r.invariant.lo);
        d.addI64(r.invariant.hi);
        d.addI64(r.exit_state.lo);
        d.addU64(r.iterations);
    }

    // 5. DTMC: вероятности достижимости.
    {
        var m = try dtmc.Dtmc.init(alloc, 3);
        defer m.deinit();
        m.set(0, 1, 0.01);
        m.set(0, 2, 0.99);
        m.set(1, 1, 1.0);
        m.set(2, 2, 1.0);
        const target = [_]bool{ false, true, false };
        const x = try m.reachProbability(&target, 10_000);
        defer alloc.free(x);
        for (x) |v| d.addF64(v);
        d.add(&[_]u8{@intFromBool(m.isStochastic())});
    }

    // 6. ReDoS-анализ регулярных выражений.
    {
        var a = redos.Node{ .lit = 'a' };
        var plus_in = redos.Node{ .plus = &a };
        var plus_out = redos.Node{ .plus = &plus_in };
        const f1 = redos.analyze(&plus_out);
        d.add(&[_]u8{ @intFromBool(f1.vulnerable), @intFromBool(f1.nested_quantifier) });

        var b1 = redos.Node{ .lit = 'a' };
        var b2 = redos.Node{ .lit = 'b' };
        const br = [_]*redos.Node{ &b1, &b2 };
        var alt = redos.Node{ .alt = &br };
        var star = redos.Node{ .star = &alt };
        d.add(&[_]u8{@intFromBool(redos.analyze(&star).vulnerable)});
    }

    // 7. Невмешательство: taint-анализ + constant-time сравнение.
    {
        const prog = [_]nonint.Instr{
            .{ .secret = 1 },
            .{ .assign = .{ .dst = 2, .src = 1 } },
            .{ .branch_on = 2 },
        };
        const f = try nonint.analyze(alloc, &prog);
        defer alloc.free(f);
        d.addU64(f.len);
        if (f.len > 0) d.add(&[_]u8{@intFromEnum(f[0].leak)});
        d.add(&[_]u8{@intFromBool(nonint.constantTimeEqual("secret", "secret"))});
        d.add(&[_]u8{@intFromBool(nonint.constantTimeEqual("secret", "secrXt"))});
        d.add(&[_]u8{@intFromBool(nonint.earlyExitEqual("secret", "secret"))});
    }

    const hash = d.final();
    var hex: [64]u8 = undefined;
    const digits = "0123456789abcdef";
    for (hash, 0..) |byte, i| {
        hex[i * 2] = digits[byte >> 4];
        hex[i * 2 + 1] = digits[byte & 0x0f];
    }
    std.debug.print("SEMANTIC_DIGEST={s}\n", .{hex});
}
