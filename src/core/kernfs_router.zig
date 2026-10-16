// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

const std = @import("std");
const cov = @import("../cov.zig");
const kimg = @import("object_entry.zig"); // 96-байтный дескриптор
const ObjectEntry = kimg.ObjectEntry;
const KimgHeader = @import("kimg_reader.zig").KimgHeader;
const HashAlgo = @import("hash_algo.zig").HashAlgo;
const KimgError = @import("kimg_reader.zig").KimgError;
const Eq2 = @import("eq2.zig").Eq2;       // KERN-EQ2 математика
const compat = @import("compat");

pub const KernFsError = error{
    PathTraversalAttempt, // CONF-13: запрет ..
    InvalidPathFormat,    // запрет пустых компонент и .
    FileNotFound,
    AccessDenied,         // CONF-06: запрет на запись
    PayloadTampered,      // SHA-256(payload) != digest дескриптора
};

/// Результат запроса к виртуальной ФС
pub const VfsNode = union(enum) {
    raw_slice: []const u8,    // Zero-Copy срез из mmap (для исходников)
    virtual_view: []const u8, // сгенерированный ответ (для статусов и отчётов)
};

pub const KernFS = struct {
    allocator: std.mem.Allocator,
    mmap_slice: []const u8,
    objects: []const ObjectEntry,
    /// Регион полезной нагрузки: срез от `data_payload_offset` до конца файла.
    /// И `logical_path_offset` (пул строк), и `payload_offset` ОТНОСИТЕЛЬНЫ
    /// начала этого среза — ровно как в спецификации KIMG.
    payload_region: []const u8,
    /// Алгоритм хеша образа (из поля `hash_algo` заголовка). Нужен для сверки
    /// SHA-256/BLAKE3 содержимого объекта при чтении.
    hash_algo: HashAlgo = HashAlgo.DEFAULT,

    pub fn init(allocator: std.mem.Allocator, mmap_slice: []const u8,
                objects: []const ObjectEntry, payload_region: []const u8) KernFS {
        return .{
            .allocator = allocator,
            .mmap_slice = mmap_slice,
            .objects = objects,
            .payload_region = payload_region,
        };
    }

    /// CONF-13: строгая валидация пути. Запрет path traversal.
    ///
    /// ПРОВЕРЕНО: все четыре отказа работают (нет ведущего `/`, `//`, `.`, `..`).
    pub fn validatePath(path: []const u8) !void {
        if (path.len == 0 or path[0] != '/') return KernFsError.InvalidPathFormat;

        var it = std.mem.splitScalar(u8, path, 0x2F);
        _ = it.next(); // пропуск первого пустого токена (из-за ведущего слеша)

        while (it.next()) |component| {
            if (component.len == 0) return KernFsError.InvalidPathFormat; // //
            if (std.mem.eql(u8, component, ".")) return KernFsError.InvalidPathFormat;
            if (std.mem.eql(u8, component, "..")) {
                cov.hit(.fs_traversal_denied);
                return KernFsError.PathTraversalAttempt;
            }
            if (std.mem.indexOfScalar(u8, component, 0) != null)
                return KernFsError.InvalidPathFormat; // NUL-инъекция
        }
    }

    /// Извлечение имени из пула строк. Границы проверяются (в отличие от
    /// первой версии Фазы 3, где чтение могло уйти за пул).
    fn getString(self: KernFS, offset: u32) []const u8 {
        if (offset >= self.payload_region.len) return "";
        var len: usize = 0;
        while (offset + len < self.payload_region.len and
               self.payload_region[offset + len] != 0) : (len += 1) {}
        return self.payload_region[offset .. offset + len];
    }

    /// Zero-copy срез полезной нагрузки объекта. Границы проверяются
    /// безопасной арифметикой (в отличие от первой версии Фазы 3).
    fn payloadSlice(self: KernFS, obj: ObjectEntry) ![]const u8 {
        // ДЕФЕКТ #55 (найден мутационным тестированием + аудитом 2026-10-14):
        // `payloadSlice` (путь чтения) и `objectPayloadRaw` (сырой путь)
        // выбирали размер ПРОТИВОПОЛОЖНО:
        //     payloadSlice:      codec == 0 ? compressed_size : uncompressed_size
        //     objectPayloadRaw:  codec != 0 ? compressed_size : uncompressed_size
        // При compressed_size != uncompressed_size они вернули бы РАЗНЫЕ срезы.
        // Дефект был невидим, потому что писатель (`kimg_writer`) и Python-
        // генератор ставят оба поля равными длине содержимого.
        //
        // ПРАВИЛО (единое для обоих): читатель возвращает СТОЛЬКО БАЙТ,
        // СКОЛЬКО ЛЕЖИТ В ОБРАЗЕ, то есть `compressed_size` — размер на диске.
        // `uncompressed_size` нужен только для будущей распаковки
        // (сжатие пока не реализовано — см. KNOWN_LIMITATIONS).
        const size: u64 = obj.compressed_size;
        const end = std.math.add(u64, obj.payload_offset, size) catch {
            cov.hit(.fs_not_found);
            return KernFsError.FileNotFound;
        };
        if (end > self.payload_region.len) {
            cov.hit(.fs_not_found);
            return KernFsError.FileNotFound;
        }
        const sl = self.payload_region[@intCast(obj.payload_offset)..@intCast(end)];
        // ЗАЩИТА ЦЕЛОСТНОСТИ PAYLOAD: Merkle-корень покрывает только ТАБЛИЦУ,
        // поэтому подмена содержимого файла иначе проходит незамеченной.
        // Сверяем SHA-256(payload) с digest из дескриптора.
        var got: [32]u8 = undefined;
        self.hash_algo.hash(sl, &got);
        if (!std.mem.eql(u8, &got, &obj.digest)) return KernFsError.PayloadTampered;
        cov.hit(.fs_hit);
        return sl;
    }

    /// СЫРОЙ zero-copy срез БЕЗ сверки SHA-256.
    ///
    /// ⚠️ БЕЗОПАСНОСТЬ: НЕ проверяет целостность содержимого. Использовать
    /// ТОЛЬКО для замеров производительности (perf_bench) и для внутренних
    /// путей, где образ уже проверен целиком (`kernc check-integrity`).
    /// Для чтения данных пользователем — `objectPayload` (с проверкой).
    pub fn objectPayloadRaw(self: KernFS, obj: ObjectEntry) KernFsError![]const u8 {
        // ЕДИНОЕ ПРАВИЛО с `payloadSlice` (дефект #55): читаем столько байт,
        // сколько лежит в образе, то есть `compressed_size`.
        // Раньше здесь было `if (codec != 0) compressed_size else
        // uncompressed_size` — ПРОТИВОПОЛОЖНО `payloadSlice`, из-за чего
        // безопасный и сырой пути могли вернуть РАЗНЫЕ срезы.
        const size: u64 = obj.compressed_size;
        const end = std.math.add(u64, obj.payload_offset, size) catch
            return KernFsError.FileNotFound;
        if (end > self.payload_region.len) return KernFsError.FileNotFound;
        return self.payload_region[@intCast(obj.payload_offset)..@intCast(end)];
    }

    /// Объект имеет путь, если выставлен бит 1 флагов и смещение пути не
    /// 0xFFFFFFFF (иначе объекта с путём нет).
    fn hasPath(obj: ObjectEntry) bool {
        return (obj.flags & 0x0002) != 0 and obj.logical_path_offset != 0xFFFFFFFF;
    }

    /// Публичный доступ к пути/идентификатору объекта (для CLI и отчётов).
    pub fn objectPath(self: KernFS, obj: ObjectEntry) []const u8 {
        if (!hasPath(obj)) return "";
        return self.getString(obj.logical_path_offset);
    }

    /// Публичный доступ к полезной нагрузке объекта (для CLI/KERN-X).
    pub fn objectPayload(self: KernFS, obj: ObjectEntry) ![]const u8 {
        return self.payloadSlice(obj);
    }

    /// ПАКЕТНАЯ верификация всех объектов образа: группы по 8 объектов
    /// проверяются одним векторным проходом (`HashAlgo.hashBatch8`).
    ///
    /// ЗАЧЕМ. На мелких объектах (96–200 Б) BLAKE3 работает в одну полосу и
    /// упирается в накладные расходы. Замер (`make bench-hash`): 352 МБ/с
    /// поштучно против 1939 МБ/с пакетно на 96 Б. Здесь те же 8 полос AVX2
    /// загружаются на 8 СОСЕДНИХ объектов.
    ///
    /// БЕЗОПАСНОСТЬ НЕ ОСЛАБЛЯЕТСЯ. Каждый из 8 результатов сверяется со СВОИМ
    /// 32-байтным `obj.digest` из таблицы дескрипторов. Порча одного байта в
    /// любой полосе даёт несовпадение -> `error.PayloadTampered`. Формат
    /// `.kimg` при этом не меняется ни на байт.
    ///
    /// Возвращает число проверенных объектов.
    pub fn verifyAllBatch(self: KernFS) KernFsError!usize {
        const batch_max = HashAlgo.batchMaxLen();
        var i: usize = 0;
        var verified: usize = 0;
        while (i < self.objects.len) {
            const room = self.objects.len - i;
            const group: usize = @min(room, 8);

            // Пакетный путь применим, если набралось ровно 8 объектов и все они
            // помещаются в один чанк. Иначе — честный поштучный путь.
            var all_small = group == 8;
            if (all_small) {
                for (self.objects[i .. i + 8]) |obj| {
                    if (obj.compressed_size > batch_max) {
                        all_small = false;
                        break;
                    }
                }
            }
            if (!all_small) {
                const sl = try self.payloadSlice(self.objects[i]);
                _ = sl;
                verified += 1;
                i += 1;
                continue;
            }

            var ins: [8][]const u8 = undefined;
            for (0..8) |k| ins[k] = try self.objectPayloadRaw(self.objects[i + k]);
            var outs: [8][32]u8 = undefined;
            self.hash_algo.hashBatch8(ins, &outs);
            for (0..8) |k| {
                if (!std.mem.eql(u8, &outs[k], &self.objects[i + k].digest)) {
                    return KernFsError.PayloadTampered;
                }
            }
            verified += 8;
            i += 8;
        }
        return verified;
    }

    /// Главный метод роутинга.
    ///
    /// 🔴 ИЗВЕСТНОЕ РАСХОЖДЕНИЕ (см. docs/archive/KERN34_AUDIT.md): роутер ищет
    /// объекты типов 0x0002 (source) и 0x0005 (claim) С ПУТЁМ, а золотой вектор
    /// v1.2 содержит ОДИН объект типа 0x0001 без пути. Поэтому на образе v1.2
    /// ни один путь не находится. Это НЕ ошибка роутера — это несогласованность
    /// Фазы 1 и Фазы 3, которую нужно устранить в спецификации.
    pub fn read(self: *KernFS, path: []const u8) !VfsNode {
        try validatePath(path);

        // 1. Пространство исходников (/raw/...)
        if (std.mem.startsWith(u8, path, "/raw/")) {
            const target_path = path[5..];
            for (self.objects) |obj| {
                if (obj.type_id == 0x0002 and hasPath(obj)) {
                    const obj_path = self.getString(obj.logical_path_offset);
                    if (std.mem.eql(u8, obj_path, target_path)) {
                        // ZERO-COPY: срез региона полезной нагрузки (без копии)
                        cov.hit(.fs_hit);
                        return VfsNode{ .raw_slice = try self.payloadSlice(obj) };
                    }
                }
            }
            return KernFsError.FileNotFound;
        }

        // 2. Семантическое пространство (/claims/...)
        if (std.mem.startsWith(u8, path, "/claims/")) {
            var it = std.mem.splitScalar(u8, path[8..], 0x2F);
            const claim_id = it.next() orelse return KernFsError.FileNotFound;
            const view_type = it.next() orelse return KernFsError.FileNotFound;

            for (self.objects) |obj| {
                if (obj.type_id == 0x0005 and hasPath(obj)) {
                    const obj_id = self.getString(obj.logical_path_offset);
                    if (std.mem.eql(u8, obj_id, claim_id)) {
                        // Статус синтезируется НА ЛЕТУ из битовой маски.
                        // Бит 1 (0x0002) занят флагом HAS_LOGICAL_PATH (спека),
                        // поэтому статус Белнапа живёт в битах 2-3 (маска 0b1100).
                        if (std.mem.eql(u8, view_type, "status")) {
                            const eq2_state: Eq2 = @enumFromInt((obj.flags >> 2) & 0b11);
                            const status_str = switch (eq2_state) {
                                .N => "N\n",
                                .T => "T\n",
                                .F => "F\n",
                                .B => "B\n",
                            };
                            return VfsNode{ .virtual_view = status_str };
                        }
                        if (std.mem.eql(u8, view_type, "contract.json")) {
                            return VfsNode{ .raw_slice = try self.payloadSlice(obj) };
                        }
                    }
                }
            }
            return KernFsError.FileNotFound;
        }

        // 3. Неизвестное пространство имён.
        return KernFsError.FileNotFound;
    }

    /// Освобождение ресурсов, выделенных `mountFromBytes`.
    pub fn deinit(self: *KernFS) void {
        self.allocator.free(self.objects);
    }

    /// KERNFS — ТОЛЬКО ЧТЕНИЕ. Любая запись отвергается явно (CONF-06).
    /// Раньше `AccessDenied` был объявлен, но возвращался `FileNotFound`.
    pub fn write(_: *KernFS, _: []const u8, _: []const u8) KernFsError!void {
        cov.hit(.fs_access_denied);
        return KernFsError.AccessDenied;
    }

    /// Монтирование образа из сырых байтов: разбор заголовка, сверка Merkle,
    /// безопасный разбор таблицы объектов. Единая точка входа для CLI и тестов.
    pub fn mountFromBytes(allocator: std.mem.Allocator, file_bytes: []const u8) !KernFS {
        if (file_bytes.len < 128) return KernFsError.FileNotFound;
        var hb: [128]u8 = undefined;
        @memcpy(&hb, file_bytes[0..128]);
        const h = KimgHeader.parse(&hb, file_bytes.len) catch
            return KernFsError.FileNotFound;
        try KimgHeader.verifyMerkleRoot(file_bytes, h);

        const count: usize = @intCast(h.object_count);
        const table_start: usize = @intCast(h.object_table_offset);
        // ЗАЩИТА: безопасная арифметика (count * 96 может переполниться).
        const table_bytes = std.math.mul(usize, count, 96) catch return KernFsError.FileNotFound;
        const table_end = std.math.add(usize, table_start, table_bytes) catch return KernFsError.FileNotFound;
        if (table_end > file_bytes.len) return KernFsError.FileNotFound;

        const objs = try allocator.alloc(ObjectEntry, count);
        var i: usize = 0;
        while (i < count) : (i += 1) {
            const off = table_start + i * 96; // i < count, проверено выше
            const eb: *const [96]u8 = @ptrCast(file_bytes.ptr + off);
            objs[i] = ObjectEntry.parseSafe(eb) catch
                return KernFsError.FileNotFound;
        }
        const payload = file_bytes[@intCast(h.data_payload_offset)..];
        var fs = KernFS.init(allocator, file_bytes, objs, payload);
        // Алгоритм из заголовка: образ на SHA-256 (старый) читается так же,
        // как новый на BLAKE3 — диспетчеризация по полю, а не хардкод.
        fs.hash_algo = HashAlgo.fromInt(h.hash_algo) orelse return KernFsError.FileNotFound;
        return fs;
    }
};

// ==========================================
// КОНФОРМАНС-ТЕСТЫ
// ==========================================
test "CONF-13: path traversal и валидация формата" {
    try KernFS.validatePath("/raw/src/main.zig");
    try KernFS.validatePath("/claims/123/status");

    try std.testing.expectError(KernFsError.InvalidPathFormat,
        KernFS.validatePath("raw/src")); // нет ведущего /
    try std.testing.expectError(KernFsError.InvalidPathFormat,
        KernFS.validatePath("/raw//main.zig")); // двойной слеш
    try std.testing.expectError(KernFsError.InvalidPathFormat,
        KernFS.validatePath("/raw/./main.zig")); // запрет .
    try std.testing.expectError(KernFsError.PathTraversalAttempt,
        KernFS.validatePath("/raw/../../etc/passwd")); // побег
}

test "SEC-03: NUL-инъекция и побег через /claims" {
    try std.testing.expectError(KernFsError.PathTraversalAttempt,
        KernFS.validatePath("/claims/../raw/secret.key"));
    try std.testing.expectError(KernFsError.InvalidPathFormat,
        KernFS.validatePath("/raw/file.zig\x00.md"));
}


// ==========================================
// ФИКСЫ ФАЗЫ 1: ТЕСТЫ НА СОГЛАСОВАННЫЙ ОБРАЗ v1.3
// ==========================================

/// Собирает минимальный валидный образ: 1 объект-источник + пул строк.
fn buildMinimalImage(w: anytype) !void {
    const content = "hello";
    const pool = "a.zig\x00" ++ content; // 11 байт: пул (6) + payload (5)

    var obj: [96]u8 = @as([96]u8, @splat(0));
    var dig: [32]u8 = undefined;
    std.crypto.hash.Blake3.hash(content, dig[0..32], .{});
    @memcpy(obj[0..32], &dig); // digest payload (сверяется при чтении)
    std.mem.writeInt(u64, obj[32..40], 6, .little);           // payload_offset
    std.mem.writeInt(u64, obj[40..48], content.len, .little); // uncompressed_size
    std.mem.writeInt(u64, obj[48..56], content.len, .little); // compressed_size
    std.mem.writeInt(u32, obj[56..60], 0x0002, .little);      // type = Source
    std.mem.writeInt(u16, obj[60..62], 0x0002, .little);      // HAS_LOGICAL_PATH
    std.mem.writeInt(u32, obj[64..68], 0, .little);           // path offset
    std.mem.writeInt(u32, obj[68..72], 1, .little);           // schema_version

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

    try w.writeAll(&header);
    try w.writeAll(&obj);
    try w.writeAll(pool);
}

test "ФИКС ФАЗ 1/3: mountFromBytes находит файл и отдаёт zero-copy срез" {
    var img = compat.BufWriter.init(std.testing.allocator);
    defer img.deinit();
    try buildMinimalImage(img.writer());

    var fs = try KernFS.mountFromBytes(std.testing.allocator, img.items());
    defer fs.deinit();

    const node = try fs.read("/raw/a.zig");
    try std.testing.expectEqualStrings("hello", node.raw_slice);
    try std.testing.expectEqualStrings("a.zig", fs.objectPath(fs.objects[0]));

    try std.testing.expectError(KernFsError.FileNotFound,
        fs.read("/raw/missing.zig"));
}

test "🔴 МУТАНТ: getString отвергает смещение ЗА пределами пула строк" {
    // Закрывает выжившего мутанта `offset >= len` -> `offset >> len`:
    // без этого теста граница не проверялась ни одним сценарием.
    // (Этот тест был ЗАТЁР прогоном tools/mutate_zig.py, который раньше
    //  правил исходники на месте; мутатор исправлен — теперь он работает
    //  на копии дерева.)
    var img = compat.BufWriter.init(std.testing.allocator);
    defer img.deinit();
    try buildMinimalImage(img.writer());

    var fs = try KernFS.mountFromBytes(std.testing.allocator, img.items());
    defer fs.deinit();

    try std.testing.expectEqualStrings("a.zig", fs.getString(0));

    const len: u32 = @intCast(fs.payload_region.len);
    try std.testing.expectEqualStrings("", fs.getString(len));
    try std.testing.expectEqualStrings("", fs.getString(len + 1));
    try std.testing.expectEqualStrings("", fs.getString(std.math.maxInt(u32)));
}

test "🔴 МУТАНТ: objectPayloadRaw не проверяет хеш, objectPayload — проверяет" {
    var img = compat.BufWriter.init(std.testing.allocator);
    defer img.deinit();
    try buildMinimalImage(img.writer());

    var fs = try KernFS.mountFromBytes(std.testing.allocator, img.items());
    defer fs.deinit();

    const obj = fs.objects[0];
    const safe = try fs.objectPayload(obj);
    const raw = try fs.objectPayloadRaw(obj);
    try std.testing.expectEqualStrings(safe, raw);

    var copy = try std.testing.allocator.dupe(u8, img.items());
    defer std.testing.allocator.free(copy);
    const base: usize = 128 + 1 * 96;
    copy[base + @as(usize, @intCast(obj.payload_offset))] ^= 0xFF;

    var fs2 = try KernFS.mountFromBytes(std.testing.allocator, copy);
    defer fs2.deinit();
    const obj2 = fs2.objects[0];
    try std.testing.expectError(KernFsError.PayloadTampered, fs2.objectPayload(obj2));
    _ = try fs2.objectPayloadRaw(obj2);
}

test "ФИКС МУТАНТ #2: objectPayloadRaw читает ровно compressed_size" {
    // Убивает выживший мутант в выборе размера: раньше здесь было
    // `if (codec != 0) compressed_size else uncompressed_size` —
    // ПРОТИВОПОЛОЖНО `payloadSlice` (дефект #55). Теперь правило единое:
    // читаем `compressed_size` (размер на диске) независимо от кодека.
    var region: [16]u8 = "a.zig\x00abcdefghij".*; // пул(6) + данные(10)

    var e0 = std.mem.zeroes(ObjectEntry);
    e0.payload_offset = 6;
    e0.compression_codec = 0;
    e0.compressed_size = 3;
    e0.uncompressed_size = 9; // НАМЕРЕННО не равен compressed_size
    var objs0 = [_]ObjectEntry{e0};
    var fs0 = KernFS.init(std.testing.allocator, &region, &objs0, &region);
    try std.testing.expectEqualStrings("abc", try fs0.objectPayloadRaw(e0));

    // Ненулевой кодек НЕ меняет правило: всё равно compressed_size.
    var e1 = e0;
    e1.compression_codec = 1;
    var objs1 = [_]ObjectEntry{e1};
    var fs1 = KernFS.init(std.testing.allocator, &region, &objs1, &region);
    try std.testing.expectEqualStrings("abc", try fs1.objectPayloadRaw(e1));

    // Если взять uncompressed_size (9) — получится ДРУГОЙ срез ("abcdefghi").
    // Тест фиксирует, что этого НЕ происходит.
    e1.compressed_size = 9;
    var objs2 = [_]ObjectEntry{e1};
    var fs2 = KernFS.init(std.testing.allocator, &region, &objs2, &region);
    try std.testing.expectEqualStrings("abcdefghi", try fs2.objectPayloadRaw(e1));
}

test "ГРАНИЦА: objectPayloadRaw отвергает выход за пределы payload" {
    var region: [8]u8 = "abcdefgh".*;
    var e = std.mem.zeroes(ObjectEntry);
    e.payload_offset = 6;
    e.compression_codec = 0;
    e.compressed_size = 100; // 6 + 100 > 8 (читается именно compressed_size)
    var objs = [_]ObjectEntry{e};
    var fs = KernFS.init(std.testing.allocator, &region, &objs, &region);
    try std.testing.expectError(KernFsError.FileNotFound, fs.objectPayloadRaw(e));
}

test "ФИКС CONF-06: запись в KERNFS отвергается AccessDenied" {
    var fs = KernFS.init(std.testing.allocator, &.{}, &.{}, &.{});
    try std.testing.expectError(KernFsError.AccessDenied,
        fs.write("/raw/a.zig", "x"));
}

test "ФИКС MERKLE: подмена байта в образе ломает монтирование" {
    var img = compat.BufWriter.init(std.testing.allocator);
    defer img.deinit();
    try buildMinimalImage(img.writer());
    img.items()[128 + 56] = 0x09; // порча type_id в таблице объектов
    try std.testing.expectError(KimgError.MerkleRootMismatch,
        KernFS.mountFromBytes(std.testing.allocator, img.items()));
}

// =========================================================================
// ТЕСТЫ, ЗАКРЫВАЮЩИЕ ВЫЖИВШИЕ МУТАНТЫ (мутационное тестирование)
// =========================================================================

test "ФИКС МУТАНТ: payloadSlice читает ровно compressed_size (единое правило #55)" {
    var region: [16]u8 = "a.zig\x00abcdefghij".*; // пул(6) + данные(10)

    var e0 = std.mem.zeroes(ObjectEntry);
    std.crypto.hash.Blake3.hash("abc", e0.digest[0..32], .{}); // digest = SHA256("abc")
    e0.type_id = 0x0002;
    e0.flags = 0x0002;
    e0.logical_path_offset = 0;
    e0.payload_offset = 6;
    e0.compression_codec = 0;
    e0.compressed_size = 3; // ← читается ВСЕГДА (размер на диске)
    e0.uncompressed_size = 99; // не влияет на чтение
    var objs0 = [_]ObjectEntry{e0};
    var fs0 = KernFS.init(std.testing.allocator, &region, &objs0, &region);
    try std.testing.expectEqualStrings("abc", (try fs0.read("/raw/a.zig")).raw_slice);

    // ДЕФЕКТ #55: раньше при codec != 0 размер брался из `uncompressed_size`,
    // из-за чего чтение расходилось с `objectPayloadRaw`. Теперь правило
    // ОДНО для обоих путей — `compressed_size`, независимо от codec.
    var e1 = e0;
    e1.compression_codec = 1;
    e1.uncompressed_size = 3;
    e1.compressed_size = 3; // ← по-прежнему размер на диске
    var objs1 = [_]ObjectEntry{e1};
    var fs1 = KernFS.init(std.testing.allocator, &region, &objs1, &region);
    try std.testing.expectEqualStrings("abc", (try fs1.read("/raw/a.zig")).raw_slice);

    // Обратная проверка: если объявить compressed_size БОЛЬШЕ содержимого,
    // чтение обязано отказать (а не молча вернуть чужой кусок памяти).
    var e2 = e0;
    e2.compressed_size = 100; // 6 + 100 > 16
    var objs2 = [_]ObjectEntry{e2};
    var fs2 = KernFS.init(std.testing.allocator, &region, &objs2, &region);
    try std.testing.expectError(KernFsError.FileNotFound, fs2.read("/raw/a.zig"));
}

test "ДЕФЕКТ #55: payloadSlice и objectPayloadRaw дают ОДИН срез" {
    // Суть дефекта: два пути выбирали размер ПРОТИВОПОЛОЖНО. Теперь правило
    // единое, и при compressed_size != uncompressed_size результаты совпадают.
    var region: [16]u8 = "a.zig\x00abcdefghij".*;
    var e = std.mem.zeroes(ObjectEntry);
    std.crypto.hash.Blake3.hash("abc", e.digest[0..32], .{});
    e.type_id = 0x0002;
    e.flags = 0x0002;
    e.logical_path_offset = 0;
    e.payload_offset = 6;
    e.compression_codec = 1; // НЕНУЛЕВОЙ кодек — именно здесь пути расходились
    e.compressed_size = 3;
    e.uncompressed_size = 9; // НЕ равен compressed_size
    var objs = [_]ObjectEntry{e};
    var fs = KernFS.init(std.testing.allocator, &region, &objs, &region);

    const safe = try fs.objectPayload(e); // = payloadSlice (с SHA-256)
    const raw = try fs.objectPayloadRaw(e); // без SHA-256
    try std.testing.expectEqualStrings(safe, raw);
    try std.testing.expectEqualStrings("abc", raw);
}

test "ФИКС МУТАНТ: hasPath требует флаг HAS_LOGICAL_PATH (бит 1)" {
    var region: [11]u8 = "a.zig\x00hello".*;
    var e = std.mem.zeroes(ObjectEntry);
    e.type_id = 0x0002;
    e.flags = 0x0000; // БЕЗ бита 1
    e.logical_path_offset = 0;
    e.payload_offset = 6;
    e.compressed_size = 5;
    e.uncompressed_size = 5;
    var objs = [_]ObjectEntry{e};
    var fs = KernFS.init(std.testing.allocator, &region, &objs, &region);
    try std.testing.expectError(KernFsError.FileNotFound, fs.read("/raw/a.zig"));
}

test "ФИКС МУТАНТ: /raw/ ищет только объекты типа Source (0x0002)" {
    var region: [11]u8 = "a.zig\x00hello".*;
    var e = std.mem.zeroes(ObjectEntry);
    e.type_id = 0x0005; // Claim, не Source
    e.flags = 0x0002;
    e.logical_path_offset = 0;
    e.payload_offset = 6;
    e.compressed_size = 5;
    e.uncompressed_size = 5;
    var objs = [_]ObjectEntry{e};
    var fs = KernFS.init(std.testing.allocator, &region, &objs, &region);
    try std.testing.expectError(KernFsError.FileNotFound, fs.read("/raw/a.zig"));
}

test "ФИКС МУТАНТ: /claims/ ищет только объекты типа Claim (0x0005)" {
    var region: [9]u8 = "c1\x00abcdef".*; // пул "c1\0"(3) + данные(6)
    var e = std.mem.zeroes(ObjectEntry);
    e.type_id = 0x0002; // Source, а НЕ Claim
    e.flags = 0x0002;
    e.logical_path_offset = 0; // "c1"
    e.payload_offset = 3;
    e.compressed_size = 6;
    e.uncompressed_size = 6;
    var objs = [_]ObjectEntry{e};
    var fs = KernFS.init(std.testing.allocator, &region, &objs, &region);
    try std.testing.expectError(KernFsError.FileNotFound, fs.read("/claims/c1/status"));
}

test "TAMPER: порча 1 байта в середине .kimg блокирует монтирование" {
    const Builder = @import("kimg_writer.zig").Builder;
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const ta = arena.allocator();
    var b = Builder.init(ta);
    defer b.deinit();
    var i: usize = 0;
    var nb: [48]u8 = undefined;
    while (i < 200) : (i += 1) {
        const nm = try std.fmt.bufPrint(&nb, "f{d}", .{i});
        try b.addSource(try ta.dupe(u8, nm), "data");
    }
    const tmp = "/tmp/tamper_test.kimg";
    try b.write(tmp);
    defer compat.deleteFile(tmp) catch {};

    var data = try compat.readFileAlloc(std.testing.allocator, tmp, 1 << 24);
    defer std.testing.allocator.free(data);

    // 1) валидный — монтируется
    var fs = try KernFS.mountFromBytes(std.testing.allocator, data);
    fs.deinit();

    // 2) порча РОВНО 1 байта в середине таблицы объектов
    const mid = 128 + (200 * 96) / 2;
    data[mid] ^= 0x01;
    try std.testing.expectError(KimgError.MerkleRootMismatch,
        KernFS.mountFromBytes(std.testing.allocator, data));

    // 3) порча байта в payload (после таблицы)
    data[mid] ^= 0x01; // откат
    const payload_pos = data.len - 2;
    data[payload_pos] ^= 0x80;
    // payload НЕ входит в Merkle (он только по таблице) -> монтирование ОК,
    // но это ожидаемое поведение: целостность payload проверяется отдельно.
    var fs2 = try KernFS.mountFromBytes(std.testing.allocator, data);
    fs2.deinit();
}

test "TRUNCATION: обрезанный образ отвергается без паники" {
    const Builder = @import("kimg_writer.zig").Builder;
    var b = Builder.init(std.testing.allocator);
    defer b.deinit();
    try b.addSource("a.zig", "hello world");
    try b.addSource("b.zig", "second");
    const tmp = "/tmp/trunc_test.kimg";
    try b.write(tmp);
    defer compat.deleteFile(tmp) catch {};
    const full = try compat.readFileAlloc(std.testing.allocator, tmp, 1 << 20);
    defer std.testing.allocator.free(full);

    // обрезаем по разным границам
    var cut: usize = 1;
    while (cut < full.len) : (cut += 7) {
        var m = KernFS.mountFromBytes(std.testing.allocator, full[0..cut]) catch continue;
        m.deinit(); // успешное монтирование обязано освобождаться
    }
}

test "ФИКС ЦЕЛОСТНОСТИ: подмена payload отвергается (digest-сверка)" {
    const Builder = @import("kimg_writer.zig").Builder;
    var b = Builder.init(std.testing.allocator);
    defer b.deinit();
    try b.addSource("secret.txt", "PASSWORD=12345");
    const tmp = "/tmp/payload_int.kimg";
    try b.write(tmp);
    defer compat.deleteFile(tmp) catch {};
    const data = try compat.readFileAlloc(std.testing.allocator, tmp, 1 << 20);
    defer std.testing.allocator.free(data);

    // 1) целостный — читается
    var fs = try KernFS.mountFromBytes(std.testing.allocator, data);
    defer fs.deinit();
    const ok = try fs.read("/raw/secret.txt");
    try std.testing.expectEqualStrings("PASSWORD=12345", ok.raw_slice);

    // 2) подмена байта в payload -> чтение ОТВЕРГАЕТСЯ
    const idx = std.mem.indexOf(u8, data, "12345").?;
    data[idx] = '9';
    try std.testing.expectError(KernFsError.PayloadTampered, fs.read("/raw/secret.txt"));
}

test "ГРАНИЦЫ: payload_offset за пределами региона -> FileNotFound" {
    // Образ валиден по Merkle, но дескриптор указывает ЗА пределы пула.
    const content = "hello";
    const pool = "a.zig\x00" ++ content;

    var obj: [96]u8 = @as([96]u8, @splat(0));
    var dig: [32]u8 = undefined;
    std.crypto.hash.Blake3.hash(content, dig[0..32], .{});
    @memcpy(obj[0..32], &dig);
    std.mem.writeInt(u64, obj[32..40], 1000, .little); // СМЕЩЕНИЕ ВНЕ ПУЛА
    std.mem.writeInt(u64, obj[40..48], content.len, .little);
    std.mem.writeInt(u64, obj[48..56], content.len, .little);
    std.mem.writeInt(u32, obj[56..60], 0x0002, .little); // Source
    std.mem.writeInt(u16, obj[60..62], 0x0002, .little); // HAS_LOGICAL_PATH
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

    var img = compat.BufWriter.init(std.testing.allocator);
    defer img.deinit();
    try img.appendSlice(&header);
    try img.appendSlice(&obj);
    try img.appendSlice(pool);

    var fs = try KernFS.mountFromBytes(std.testing.allocator, img.items());
    defer fs.deinit();
    // Смещение за пределами пула -> чтение отвергается, не паника.
    try std.testing.expectError(KernFsError.FileNotFound, fs.read("/raw/a.zig"));
}
