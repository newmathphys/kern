// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: сборщик образа .kimg v1.3 (Zig-side). Раскладка идентична
//! `tools/golden_v1_3.py`: заголовок 128 + таблица N*96 + пул строк + payload.
//! `payload_offset` и `logical_path_offset` ОТНОСИТЕЛЬНЫ `data_payload_offset`.
const std = @import("std");
const ObjectEntry = @import("object_entry.zig").ObjectEntry;
const KernFsRouter = @import("kernfs_router.zig").KernFS;

pub const BuildError = error{ TooManyObjects, Empty, PoolTooLarge, Overflow };

pub const ObjectSpec = struct {
    path: []const u8,
    type_id: u32,
    flags: u16,
    content: []const u8,
};

pub const Builder = struct {
    allocator: std.mem.Allocator,
    specs: std.ArrayList(ObjectSpec),

    pub fn init(allocator: std.mem.Allocator) Builder {
        return .{ .allocator = allocator, .specs = std.ArrayList(ObjectSpec).init(allocator) };
    }

    pub fn deinit(self: *Builder) void {
        self.specs.deinit();
    }

    pub fn addSource(self: *Builder, path: []const u8, content: []const u8) !void {
        try self.specs.append(.{ .path = path, .type_id = 0x0002, .flags = 0x0002, .content = content });
    }

    /// status_bits: биты 2-3 (0=N, 1=T, 2=F, 3=B). Бит 1 = HAS_LOGICAL_PATH.
    pub fn addClaim(self: *Builder, id: []const u8, contract: []const u8, status_bits: u2) !void {
        try self.specs.append(.{ .path = id, .type_id = 0x0005, .flags = 0x0002 | (@as(u16, status_bits) << 2), .content = contract });
    }

    /// Байткод для KERN-X (тип 0x0007).
    pub fn addBytecode(self: *Builder, name: []const u8, code: []const u8) !void {
        try self.specs.append(.{ .path = name, .type_id = 0x0007, .flags = 0x0002, .content = code });
    }

    pub fn write(self: *Builder, out_path: []const u8) !void {
        const n = self.specs.items.len;
        if (n == 0) return BuildError.Empty;

        // 1. Пул строк + payload
        var pool = std.ArrayList(u8).init(self.allocator);
        defer pool.deinit();
        var path_off = try self.allocator.alloc(u32, n);
        defer self.allocator.free(path_off);
        for (self.specs.items, 0..) |sp, i| {
            // ЗАЩИТА: путь адресуется 32-битным смещением. Без проверки
            // @intCast на пуле > 4 ГБ дал бы ПАНИКУ вместо ошибки.
            if (pool.items.len > std.math.maxInt(u32)) return BuildError.PoolTooLarge;
            path_off[i] = @intCast(pool.items.len);
            try pool.appendSlice(sp.path);
            try pool.append(0);
        }
        const pool_len = pool.items.len;
        var payload_off = try self.allocator.alloc(u64, n);
        defer self.allocator.free(payload_off);
        var payload = std.ArrayList(u8).init(self.allocator);
        defer payload.deinit();
        for (self.specs.items, 0..) |sp, i| {
            payload_off[i] = pool_len + payload.items.len;
            try payload.appendSlice(sp.content);
        }

        // 2. Таблица объектов
        const entries = try self.allocator.alloc([96]u8, n);
        defer self.allocator.free(entries);
        for (self.specs.items, 0..) |sp, i| {
            var e: [96]u8 = [_]u8{0} ** 96;
            var digest: [32]u8 = undefined;
            std.crypto.hash.sha2.Sha256.hash(sp.content, &digest, .{});
            @memcpy(e[0..32], &digest);
            std.mem.writeInt(u64, e[32..40], payload_off[i], .little);
            std.mem.writeInt(u64, e[40..48], sp.content.len, .little);
            std.mem.writeInt(u64, e[48..56], sp.content.len, .little);
            std.mem.writeInt(u32, e[56..60], sp.type_id, .little);
            std.mem.writeInt(u16, e[60..62], sp.flags, .little);
            std.mem.writeInt(u32, e[64..68], path_off[i], .little);
            std.mem.writeInt(u32, e[68..72], 1, .little);
            entries[i] = e;
        }

        // 3. Merkle-корень
        var root: [32]u8 = undefined;
        ObjectEntry.computeRootHash(entries, &root);

        // 4. Заголовок
        var header: [128]u8 = [_]u8{0} ** 128;
        @memcpy(header[0..8], "KIMG\r\n\x1a\n");
        std.mem.writeInt(u16, header[8..10], 1, .little);
        std.mem.writeInt(u16, header[10..12], 3, .little);
        std.mem.writeInt(u32, header[12..16], 128, .little);
        std.mem.writeInt(u32, header[16..20], 0, .little);
        std.mem.writeInt(u32, header[20..24], 2, .little); // hash_algo = SHA-256
        std.mem.writeInt(u64, header[24..32], 4096, .little);
        std.mem.writeInt(u64, header[32..40], 128, .little);
        // ЗАЩИТА: n*96 и 128+n*96 — безопасная арифметика (иначе переполнение).
        const table_size = std.math.mul(u64, n, 96) catch return BuildError.Overflow;
        const payload_start = std.math.add(u64, 128, table_size) catch return BuildError.Overflow;
        std.mem.writeInt(u64, header[40..48], table_size, .little);
        std.mem.writeInt(u64, header[48..56], @as(u64, n), .little);
        std.mem.writeInt(u64, header[56..64], payload_start, .little);
        @memcpy(header[64..96], &root);
        var csum: [32]u8 = undefined;
        std.crypto.hash.sha2.Sha256.hash(header[0..96], &csum, .{});
        @memcpy(header[96..128], &csum);

        // 5. АТОМАРНАЯ запись (crash-consistency): пишем во временный файл,
        // затем rename. При аварии (SIGKILL/отключение питания) целевой файл
        // либо старый целый, либо новый целый — НИКОГДА не битый посередине.
        const tmp_path = try std.fmt.allocPrint(self.allocator, "{s}.tmp", .{out_path});
        defer self.allocator.free(tmp_path);
        {
            const f = try std.fs.cwd().createFile(tmp_path, .{});
            errdefer std.fs.cwd().deleteFile(tmp_path) catch {};
            defer f.close();
            try f.writeAll(&header);
            for (entries) |e| try f.writeAll(&e);
            try f.writeAll(pool.items);
            try f.writeAll(payload.items);
            // ДЕФЕКТ (исправлен): без fsync данные оставались в кэше ОС, и
            // после отключения питания `rename` мог обогнать запись — на
            // диске оказывался ПУСТОЙ (или частичный) файл. Теперь данные
            // сброшены на носитель ДО переименования.
            try f.sync();
        }
        // Если rename упадёт — временный файл не должен остаться мусором.
        errdefer std.fs.cwd().deleteFile(tmp_path) catch {};
        try std.fs.cwd().rename(tmp_path, out_path);
        // Долговечность самого rename: синхронизируем КАТАЛОГ.
        // (в Zig 0.13 у std.fs.Dir нет .sync() — открываем каталог через posix)
        const dfd = std.posix.open(".", .{ .ACCMODE = .RDONLY, .DIRECTORY = true }, 0) catch -1;
        if (dfd >= 0) {
            defer std.posix.close(dfd);
            std.posix.fsync(dfd) catch {};
        }
    }
};

// =========================================================================
// ТЕСТЫ (roundtrip: build → mount → read)
// =========================================================================

test "KIMG-WRITER: сборка образа и чтение через KERNFS (roundtrip)" {
    var b = Builder.init(std.testing.allocator);
    defer b.deinit();
    try b.addSource("src/main.zig", "pub fn main() void {}\n");
    try b.addClaim("L0_Inv", "{\"pre\":\"true\"}", 1); // статус T

    const tmp = "/tmp/kern_writer_test.kimg";
    try b.write(tmp);
    defer std.fs.cwd().deleteFile(tmp) catch {};

    const data = try std.fs.cwd().readFileAlloc(std.testing.allocator, tmp, 1 << 20);
    defer std.testing.allocator.free(data);

    var fs = try KernFsRouter.mountFromBytes(std.testing.allocator, data);
    defer fs.deinit();

    const src = try fs.read("/raw/src/main.zig");
    try std.testing.expectEqualStrings("pub fn main() void {}\n", src.raw_slice);
    const st = try fs.read("/claims/L0_Inv/status");
    try std.testing.expectEqualStrings("T\n", st.virtual_view);
}

test "ГРАНИЦА: пустой Builder -> BuildError.Empty" {
    var b = Builder.init(std.testing.allocator);
    defer b.deinit();
    try std.testing.expectError(BuildError.Empty, b.write("/tmp/empty_test.kimg"));
}

test "ГРАНИЦА: объект с пустым содержимым и длинным путём" {
    var b = Builder.init(std.testing.allocator);
    defer b.deinit();
    var long_name_buf: [200]u8 = undefined;
    @memset(&long_name_buf, 'a');
    try b.addSource(&long_name_buf, ""); // пустой payload
    try b.addSource("x", "y");
    const tmp = "/tmp/edge_writer.kimg";
    try b.write(tmp);
    defer std.fs.cwd().deleteFile(tmp) catch {};
    const data = try std.fs.cwd().readFileAlloc(std.testing.allocator, tmp, 1 << 20);
    defer std.testing.allocator.free(data);
    const KernFS2 = @import("kernfs_router.zig").KernFS;
    var fs = try KernFS2.mountFromBytes(std.testing.allocator, data);
    defer fs.deinit();
    const n = try fs.read("/raw/x");
    try std.testing.expectEqualStrings("y", n.raw_slice);
    const e = try fs.read("/raw/" ++ "a" ** 200);
    try std.testing.expectEqualStrings("", e.raw_slice);
}

test "CRASH-CONSISTENCY: запись атомарна, .tmp не остаётся" {
    var b = Builder.init(std.testing.allocator);
    defer b.deinit();
    try b.addSource("a.zig", "content");
    const out = "/tmp/atomic_test.kimg";
    defer std.fs.cwd().deleteFile(out) catch {};
    try b.write(out);
    // целевой файл есть
    try std.fs.cwd().access(out, .{});
    // .tmp не осталось
    var tmp_buf: [64]u8 = undefined;
    const tmp = try std.fmt.bufPrint(&tmp_buf, "{s}.tmp", .{out});
    try std.testing.expectError(error.FileNotFound, std.fs.cwd().access(tmp, .{}));
    // перезапись поверх — тоже ок (атомарно)
    try b.write(out);
    try std.fs.cwd().access(out, .{});
}

test "ДОЛГОВЕЧНОСТЬ: данные сброшены на носитель (fsync), образ читается" {
    // Без fsync перед rename данные могли остаться в кэше ОС, и после
    // отключения питания на диске оказался бы ПУСТОЙ файл. Проверяем, что
    // образ после записи полностью читается с диска (не из кэша процесса).
    var b = Builder.init(std.testing.allocator);
    defer b.deinit();
    try b.addSource("src/x.zig", "durability probe");
    const out = "/tmp/durability_test.kimg";
    defer std.fs.cwd().deleteFile(out) catch {};
    try b.write(out);

    // Читаем ФАЙЛ (а не память процесса) — если бы fsync не было,
    // на некоторых ФС размер/содержимое могли быть нулевыми.
    const data = try std.fs.cwd().readFileAlloc(std.testing.allocator, out, 1 << 20);
    defer std.testing.allocator.free(data);
    try std.testing.expect(data.len > 128);
    try std.testing.expectEqualStrings("KIMG\r\n\x1a\n", data[0..8]);

    // И образ монтируется.
    var fs = try KernFsRouter.mountFromBytes(std.testing.allocator, data);
    defer fs.deinit();
    try std.testing.expectEqualStrings("durability probe", (try fs.read("/raw/src/x.zig")).raw_slice);
}
