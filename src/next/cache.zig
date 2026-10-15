// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN-Next: кэш (§11, §6.2 incremental). Хэш содержимого → пропуск
//! повторной обработки неизменённых файлов (критерий 10 из §20).
const std = @import("std");
const atomic = @import("atomic");
const compat = @import("compat");

pub fn sha256Hex(allocator: std.mem.Allocator, data: []const u8) ![]u8 {
    var digest: [32]u8 = undefined;
    std.crypto.hash.sha2.Sha256.hash(data, &digest, .{});
    const hex = "0123456789abcdef";
    const out = try allocator.alloc(u8, 64);
    for (digest, 0..) |b, i| {
        out[i * 2] = hex[b >> 4];
        out[i * 2 + 1] = hex[b & 0x0f];
    }
    return out;
}

pub fn hashFile(allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    const data = try compat.readFileAlloc(allocator, path, 1 << 28);
    defer allocator.free(data);
    return sha256Hex(allocator, data);
}

/// Кэш: путь → sha256. Формат файла — строки `<hash>\t<path>`.
pub const Cache = struct {
    allocator: std.mem.Allocator,
    map: std.StringHashMap([]const u8),

    pub fn init(allocator: std.mem.Allocator) Cache {
        return .{ .allocator = allocator, .map = std.StringHashMap([]const u8).init(allocator) };
    }

    /// Освободить кэш: карта хранит ДУБЛИКАТЫ строк (см. put/load), поэтому
    /// их надо освободить, иначе утечка (арена в CLI маскировала её).
    pub fn deinit(self: *Cache) void {
        var it = self.map.iterator();
        while (it.next()) |e| {
            self.allocator.free(e.key_ptr.*);
            self.allocator.free(e.value_ptr.*);
        }
        self.map.deinit();
    }

    pub fn load(allocator: std.mem.Allocator, path: []const u8) !Cache {
        var self = Cache.init(allocator);
        errdefer self.deinit();
        // 🔴 ДЕФЕКТ (найден аудитом, ИСПРАВЛЕН): `data` (до 16 МБ) читался и
        // НИКОГДА не освобождался — утечка на каждую загрузку кэша.
        // Строки дублируются в карту, поэтому буфер можно освободить сразу.
        const data = compat.readFileAlloc(allocator, path, 1 << 24) catch return self;
        defer allocator.free(data);
        var it = std.mem.splitScalar(u8, data, '\n');
        while (it.next()) |line| {
            if (line.len == 0) continue;
            const tab = std.mem.indexOfScalar(u8, line, '\t') orelse continue;
            const h = line[0..tab];
            const p = line[tab + 1 ..];
            try self.map.put(try allocator.dupe(u8, p), try allocator.dupe(u8, h));
        }
        return self;
    }

    pub fn save(self: *Cache, path: []const u8) !void {
        var buf = std.array_list.Managed(u8).init(self.allocator);
        defer buf.deinit();
        var it = self.map.iterator();
        while (it.next()) |e| {
            try buf.appendSlice(e.value_ptr.*);
            try buf.append('\t');
            try buf.appendSlice(e.key_ptr.*);
            try buf.append('\n');
        }
        // АТОМАРНО: битый кэш -> неверное решение «файл не изменился».
        try atomic.writeFileAtomic(self.allocator, path, buf.items);
    }

    pub fn isUnchanged(self: *Cache, path: []const u8, hash: []const u8) bool {
        const prev = self.map.get(path) orelse return false;
        return std.mem.eql(u8, prev, hash);
    }

    pub fn put(self: *Cache, path: []const u8, hash: []const u8) !void {
        const p = try self.allocator.dupe(u8, path);
        const h = try self.allocator.dupe(u8, hash);
        try self.map.put(p, h);
    }
};

test "УТЕЧКИ: Cache.load/save полностью освобождаются (testing.allocator)" {
    // ДЕФЕКТ (был): `data` (до 16 МБ) в load() не освобождался, и у Cache
    // не было deinit — дубликаты строк в карте тоже текли.
    const a = std.testing.allocator; // детектор утечек
    const path = "/tmp/kern_cache_leak.ck";
    defer compat.deleteFile(path) catch {};

    {
        var c = Cache.init(a);
        defer c.deinit();
        try c.put("a.kern", "deadbeef");
        try c.put("b.kern", "cafebabe");
        try c.save(path);
    }
    // Загрузка из файла: буфер данных должен быть освобождён.
    var c2 = try Cache.load(a, path);
    defer c2.deinit();
    try std.testing.expect(c2.isUnchanged("a.kern", "deadbeef"));
    try std.testing.expect(c2.isUnchanged("b.kern", "cafebabe"));
    try std.testing.expect(!c2.isUnchanged("a.kern", "00000000"));

    // Загрузка отсутствующего файла — пустой кэш, без утечек.
    var c3 = try Cache.load(a, "/tmp/kern_cache_no_such_file.ck");
    defer c3.deinit();
    try std.testing.expect(!c3.isUnchanged("x", "y"));
}

test "CACHE: хэш стабилен, неизменённый файл распознаётся" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();

    const h1 = try sha256Hex(a, "hello");
    const h2 = try sha256Hex(a, "hello");
    const h3 = try sha256Hex(a, "hello!");
    try std.testing.expectEqualStrings(h1, h2);
    try std.testing.expect(!std.mem.eql(u8, h1, h3));
    try std.testing.expectEqual(@as(usize, 64), h1.len);

    var c = Cache.init(a);
    try c.put("a.kern", h1);
    try std.testing.expect(c.isUnchanged("a.kern", h1));
    try std.testing.expect(!c.isUnchanged("a.kern", h3));
    try std.testing.expect(!c.isUnchanged("b.kern", h1));
}
