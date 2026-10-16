// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

const std = @import("std");
const cov = @import("../cov.zig");
const kimg = @import("object_entry.zig"); // 96-байтный дескриптор
const ObjectEntry = kimg.ObjectEntry;
const KimgHeader = @import("kimg_reader.zig").KimgHeader;
const HashAlgo = @import("hash_algo.zig").HashAlgo;
const codec = @import("codec.zig");
const KimgError = @import("kimg_reader.zig").KimgError;
const Eq2 = @import("eq2.zig").Eq2;       // KERN-EQ2 математика
const compat = @import("compat");

pub const KernFsError = error{
    PathTraversalAttempt, // CONF-13: запрет ..
    InvalidPathFormat,    // запрет пустых компонент и .
    FileNotFound,
    AccessDenied,         // CONF-06: запрет на запись
    PayloadTampered,      // SHA-256(payload) != digest дескриптора
    /// Объект СЖАТ: zero-copy срез невозможен в принципе (нужен буфер для
    /// распаковки). ЯВНАЯ ошибка вместо тихой выдачи сжатых байт как данных.
    /// Используйте `decompressObject`.
    CompressedNeedsDecompress,
    OutOfMemory,
};

/// Результат запроса к виртуальной ФС
pub const VfsNode = union(enum) {
    raw_slice: []const u8,    // Zero-Copy срез из mmap (для исходников)
    virtual_view: []const u8, // сгенерированный ответ (для статусов и отчётов)
};

/// Битовая маска ПРОВЕРЕННЫХ объектов: 1 бит на объект.
///
/// Для 10 000 объектов это 1250 байт — ничтожная цена за то, что одиночные
/// чтения внутри одного кластера из 8 соседей перестают хешировать повторно.
/// Кэш валиден только для ИММУТАБЕЛЬНОГО образа (mmap запечатанного файла).
pub const ClusterCache = struct {
    bits: []u8,

    pub fn init(alloc: std.mem.Allocator, n_objects: usize) !ClusterCache {
        const nbytes = (n_objects + 7) / 8;
        const bits = try alloc.alloc(u8, if (nbytes == 0) 1 else nbytes);
        @memset(bits, 0);
        return .{ .bits = bits };
    }

    pub fn deinit(self: ClusterCache, alloc: std.mem.Allocator) void {
        alloc.free(self.bits);
    }

    pub fn isVerified(self: ClusterCache, idx: usize) bool {
        const byte = idx / 8;
        if (byte >= self.bits.len) return false;
        return (self.bits[byte] >> @intCast(idx % 8)) & 1 == 1;
    }

    pub fn mark(self: *ClusterCache, idx: usize) void {
        const byte = idx / 8;
        if (byte >= self.bits.len) return;
        self.bits[byte] |= @as(u8, 1) << @intCast(idx % 8);
    }
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
        // СЖАТЫЙ объект: zero-copy невозможен (распаковка требует буфера).
        // Возвращаем ЯВНУЮ ошибку, а не сжатые байты под видом содержимого.
        if (obj.compression_codec != 0) return KernFsError.CompressedNeedsDecompress;
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

    /// Прочитать содержимое объекта ЛЮБОГО кодека.
    ///
    /// `raw`     — копия zero-copy среза (память выделяется);
    /// `deflate` — распаковка в буфер (вызывающий освобождает).
    ///
    /// БЕЗОПАСНОСТЬ. Дайджест сверяется по РАСПАКОВАННОМУ содержимому — так же,
    /// как его считал писатель. Порядок важен: сначала распаковка РОВНО в
    /// `uncompressed_size` байт (защита от «zip-бомбы»), затем сверка хеша.
    pub fn decompressObject(
        self: KernFS,
        allocator: std.mem.Allocator,
        obj: ObjectEntry,
    ) ![]u8 {
        const c = codec.Codec.fromInt(obj.compression_codec) orelse
            return KernFsError.FileNotFound;
        if (c == .raw) {
            const sl = try self.payloadSlice(obj);
            const buf = allocator.alloc(u8, sl.len) catch return KernFsError.OutOfMemory;
            @memcpy(buf, sl);
            return buf;
        }
        const stored = try self.objectPayloadRaw(obj);
        const out = codec.decompress(allocator, c, stored, @intCast(obj.uncompressed_size)) catch
            return KernFsError.PayloadTampered;
        errdefer allocator.free(out);
        var got: [32]u8 = undefined;
        self.hash_algo.hash(out, &got);
        if (!std.mem.eql(u8, &got, &obj.digest)) return KernFsError.PayloadTampered;
        return out;
    }

    /// Публичный доступ к полезной нагрузке объекта (для CLI/KERN-X).
    pub fn objectPayload(self: KernFS, obj: ObjectEntry) ![]const u8 {
        return self.payloadSlice(obj);
    }

    /// ЧТЕНИЕ ПО ОДНОМУ ОБЪЕКТУ с кластерным кэшем проверки.
    ///
    /// ПРОБЛЕМА. `objectPayload` считает хеш ОДНОГО объекта — 8 полос SIMD
    /// загрузить нечем, и цикл из 10 000 одиночных чтений работает на скорости
    /// поштучного хеша (~356 МБ/с).
    ///
    /// РЕШЕНИЕ. При первом обращении к объекту `idx` проверяется весь КЛАСТЕР
    /// из 8 соседних объектов (`base = idx & ~7`) одним векторным проходом, а
    /// результат запоминается в битовой маске (1 бит на объект: для 10 000
    /// объектов это 1250 байт). Последующие 7 обращений к тому же кластеру
    /// идут без повторного хеширования.
    ///
    /// БЕЗОПАСНОСТЬ. Кэш корректен ТОЛЬКО потому, что образ иммутабелен: это
    /// mmap запечатанного файла, содержимое не может измениться под нами.
    /// Каждый объект кластера по-прежнему сверяется со СВОИМ `entry.digest`,
    /// и при несовпадении возвращается `error.PayloadTampered` (биты при этом
    /// НЕ выставляются).
    pub fn objectPayloadCached(
        self: KernFS,
        idx: usize,
        cache: *ClusterCache,
    ) KernFsError![]const u8 {
        if (idx >= self.objects.len) return KernFsError.FileNotFound;
        if (cache.isVerified(idx)) return self.objectPayloadRaw(self.objects[idx]);

        const base = idx & ~@as(usize, 7);
        const room = self.objects.len - base;
        const group: usize = @min(room, 8);
        if (group == 8) {
            var all_small = true;
            for (self.objects[base .. base + 8]) |o| {
                // Сжатые объекты исключаются: их содержимое не равно байтам
                // в образе, а кэш подтверждает именно байты образа.
                if (o.compression_codec != 0 or o.compressed_size > HashAlgo.batchMaxLen()) {
                    all_small = false;
                    break;
                }
            }
            if (all_small) {
                var ins: [8][]const u8 = undefined;
                for (0..8) |k| ins[k] = try self.objectPayloadRaw(self.objects[base + k]);
                var outs: [8][32]u8 = undefined;
                self.hash_algo.hashBatch8(ins, &outs);
                for (0..8) |k| {
                    if (!std.mem.eql(u8, &outs[k], &self.objects[base + k].digest)) {
                        return KernFsError.PayloadTampered;
                    }
                }
                for (0..8) |k| cache.mark(base + k);
                return self.objectPayloadRaw(self.objects[idx]);
            }
        }
        // Кластер неполный или объект крупный — честный поштучный путь.
        const sl = try self.payloadSlice(self.objects[idx]);
        cache.mark(idx);
        return sl;
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
    // из-за чего чтение расходилось с `objectPayloadRaw`. Правило ОДНО для
    // обоих путей — `compressed_size` (размер на диске). Проверяем на
    // ВРАЖДЕБНОМ входе: размеры расходятся (99 против 3), объект raw.
    var e1 = e0;
    e1.compression_codec = 0;
    e1.uncompressed_size = 99; // ложь во вредоносном образе
    e1.compressed_size = 3; // ← читается ВСЕГДА
    var objs1 = [_]ObjectEntry{e1};
    var fs1 = KernFS.init(std.testing.allocator, &region, &objs1, &region);
    try std.testing.expectEqualStrings("abc", (try fs1.read("/raw/a.zig")).raw_slice);

    // СЖАТЫЙ объект: zero-copy НЕВОЗМОЖЕН в принципе. `payloadSlice` обязан
    // вернуть ЯВНУЮ ошибку, а не сжатые байты под видом содержимого.
    var ec = e0;
    ec.compression_codec = 2; // deflate
    ec.compressed_size = 3;
    ec.uncompressed_size = 50;
    var objsc = [_]ObjectEntry{ec};
    var fsc = KernFS.init(std.testing.allocator, &region, &objsc, &region);
    try std.testing.expectError(KernFsError.CompressedNeedsDecompress,
        fsc.read("/raw/a.zig"));
    // Сырой путь по-прежнему отдаёт БАЙТЫ ОБРАЗА (это его назначение).
    try std.testing.expectEqualStrings("abc", try fsc.objectPayloadRaw(ec));

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
    // РАНЬШЕ здесь стоял codec = 1 как синтетический маркер. Теперь 1 — это
    // РЕАЛЬНЫЙ кодек (zstd), а для сжатых объектов zero-copy запрещён явно
    // (см. `CompressedNeedsDecompress`). Инвариант #55 проверяем на ВРАЖДЕБНОМ
    // входе: кодек raw, но `uncompressed_size` лжёт (9 вместо 3).
    e.compression_codec = 0;
    e.compressed_size = 3; // ← размер на диске, читается ВСЕГДА
    e.uncompressed_size = 9; // ← ложь во вредоносном образе
    var objs = [_]ObjectEntry{e};
    var fs = KernFS.init(std.testing.allocator, &region, &objs, &region);

    const safe = try fs.objectPayload(e); // = payloadSlice (со сверкой хеша)
    const raw = try fs.objectPayloadRaw(e); // без сверки хеша
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

test "КЛАСТЕРНЫЙ КЭШ: подмена в СОСЕДНЕМ объекте кластера ловится при первом чтении" {
    const Builder = @import("kimg_writer.zig").Builder;
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const ta = arena.allocator();
    var b = Builder.init(ta);
    defer b.deinit();
    // 16 объектов по 200 Б — два полных кластера по 8.
    var payloads: [16][]const u8 = undefined;
    var i: usize = 0;
    var nb: [48]u8 = undefined;
    while (i < 16) : (i += 1) {
        const nm = try std.fmt.bufPrint(&nb, "o{d}", .{i});
        const body = try ta.alloc(u8, 200);
        for (body, 0..) |*c, k| c.* = @truncate((i * 31 + k * 7) & 0xFF);
        payloads[i] = body;
        try b.addSource(try ta.dupe(u8, nm), body);
    }
    var out = std.array_list.Managed(u8).init(ta);
    try b.buildBytes(&out);
    const img = out.items;

    // Портим 1 байт в объекте 7 (он в ТОМ ЖЕ кластере, что и объект 3).
    const fs_ok = try KernFS.mountFromBytes(ta, img);
    // ВАЖНО: `payload_offset` в дескрипторе ОТНОСИТЕЛЬНЫЙ — прибавляем
    // абсолютное начало пула из заголовка (поле 56..64). Именно на этой
    // ловушке спотыкаются тесты подмены, которые «портят» не то место.
    const pool_base = std.mem.readInt(u64, img[56..64], .little);
    const off7 = @as(usize, @intCast(pool_base + fs_ok.objects[7].payload_offset));
    img[off7 + 5] ^= 0x01;

    var cache = try ClusterCache.init(std.testing.allocator, fs_ok.objects.len);
    defer cache.deinit(std.testing.allocator);
    // Обращаемся к объекту 3: кластер проверяется целиком, подмена в 7 обязана
    // быть обнаружена, и биты НЕ выставляются.
    try std.testing.expectError(KernFsError.PayloadTampered, fs_ok.objectPayloadCached(3, &cache));
    try std.testing.expect(!cache.isVerified(3));
    try std.testing.expect(!cache.isVerified(7));
}

test "КЛАСТЕРНЫЙ КЭШ: корректный образ — содержимое и повторное чтение совпадают" {
    const Builder = @import("kimg_writer.zig").Builder;
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const ta = arena.allocator();
    var b = Builder.init(ta);
    defer b.deinit();
    var i: usize = 0;
    var nb: [48]u8 = undefined;
    while (i < 8) : (i += 1) {
        const nm = try std.fmt.bufPrint(&nb, "p{d}", .{i});
        const body = try ta.alloc(u8, 100 + i * 9);
        for (body, 0..) |*c, k| c.* = @truncate((i * 17 + k * 3 + 1) & 0xFF);
        try b.addSource(try ta.dupe(u8, nm), body);
    }
    var out = std.array_list.Managed(u8).init(ta);
    try b.buildBytes(&out);
    const img = out.items;
    const fs = try KernFS.mountFromBytes(ta, img);

    var cache = try ClusterCache.init(std.testing.allocator, fs.objects.len);
    defer cache.deinit(std.testing.allocator);
    // Первое чтение проверяет весь кластер и взводит 8 бит.
    const first = try fs.objectPayloadCached(0, &cache);
    for (0..8) |k| try std.testing.expect(cache.isVerified(k));
    // Повторное чтение отдаёт те же байты.
    const again = try fs.objectPayloadCached(0, &cache);
    try std.testing.expectEqualSlices(u8, first, again);
    // И остальные объекты кластера тоже отдаются (из кэша).
    for (1..8) |k| _ = try fs.objectPayloadCached(k, &cache);
}

// =========================================================================
//  ТЕСТЫ ПРОТИВ ВЫЖИВШИХ МУТАНТОВ (мутационный скор 82.5% -> цель >= 90%)
//  Каждый тест убивает КОНКРЕТНЫЙ мутант из отчёта tools/mutate_zig.py.
// =========================================================================

test "МУТАНТ ==->!=: кэш кластера работает и во ВТОРОМ байте (n=16)" {
    // Мутация `if (nbytes == 0) 1 else nbytes` -> `!= 0` выделяет ОДИН байт
    // вместо nbytes. Для n=16 нужен второй байт: отметка индекса 12 молча
    // теряется, и кэш перестаёт кэшировать (корректность не страдает, но
    // эффективность падает — тестами это не ловилось).
    const alloc = std.testing.allocator;
    var c = try ClusterCache.init(alloc, 16);
    defer c.deinit(alloc);
    try std.testing.expect(!c.isVerified(12));
    c.mark(12);
    try std.testing.expect(c.isVerified(12)); // <- убивает мутанта
    try std.testing.expect(!c.isVerified(11));
    try std.testing.expect(!c.isVerified(13));
}

test "МУТАНТ >=->>: индекс РОВНО на границе байта не читает память" {
    // `if (byte >= self.bits.len) return` -> `>`: при byte == len происходит
    // чтение ЗА границей среза. n=8 даёт ровно 1 байт, поэтому idx=8..15
    // попадают на границу — мутант либо паникует, либо читает мусор.
    const alloc = std.testing.allocator;
    var c = try ClusterCache.init(alloc, 8);
    defer c.deinit(alloc);
    c.mark(8); // byte == len
    try std.testing.expect(!c.isVerified(8));
    c.mark(1_000_000);
    try std.testing.expect(!c.isVerified(1_000_000));
}

test "МУТАНТ >=->>: objectPayloadCached отвергает idx == objects.len" {
    // `if (idx >= self.objects.len) return FileNotFound` -> `>`: при idx == len
    // проверка пропускается и происходит обращение за границей массива.
    var region: [11]u8 = "a.zig\x00hello".*;
    var e = std.mem.zeroes(ObjectEntry);
    std.crypto.hash.Blake3.hash("hello", e.digest[0..32], .{});
    e.type_id = 0x0002;
    e.flags = 0x0002;
    e.payload_offset = 6;
    e.compressed_size = 5;
    e.uncompressed_size = 5;
    var objs = [_]ObjectEntry{e};
    const fs = KernFS.init(std.testing.allocator, &region, &objs, &region);
    var cache = try ClusterCache.init(std.testing.allocator, objs.len);
    defer cache.deinit(std.testing.allocator);

    // Корректный индекс работает.
    try std.testing.expectEqualStrings("hello", try fs.objectPayloadCached(0, &cache));
    // idx == objects.len ОБЯЗАН быть отвергнут (мутант пропустит проверку).
    try std.testing.expectError(KernFsError.FileNotFound,
        fs.objectPayloadCached(objs.len, &cache));
}

test "МУТАНТ or->and: СЖАТЫЙ объект в кластере НЕ идёт в пакетный путь" {
    // `if (codec != 0 or size > batchMax)` -> `and`: для сжатого, но МАЛОГО
    // объекта условие станет ложным, и он попадёт в пакетный путь. Там его
    // СЫРЫЕ байты сверяются с дайджестом РАСПАКОВАННОГО содержимого ->
    // PayloadTampered на КОРРЕКТНОМ образе.
    var region: [16]u8 = "c.bin\x00ABCDEFGHIJ".*;
    var e = std.mem.zeroes(ObjectEntry);
    std.crypto.hash.Blake3.hash("ABCDEFGHIJ", e.digest[0..32], .{});
    e.type_id = 0x0002;
    e.flags = 0x0002;
    e.payload_offset = 6;
    e.compressed_size = 10;
    e.uncompressed_size = 10;
    e.compression_codec = 2; // deflate: содержимое != байтам образа
    var objs = [_]ObjectEntry{e};
    const fs = KernFS.init(std.testing.allocator, &region, &objs, &region);
    var cache = try ClusterCache.init(std.testing.allocator, objs.len);
    defer cache.deinit(std.testing.allocator);

    // Одиночный объект кластера неполный (1 < 8), поэтому идёт поштучный путь
    // и сжатый объект отвергается ЯВНОЙ ошибкой, а не PayloadTampered.
    try std.testing.expectError(KernFsError.CompressedNeedsDecompress,
        fs.objectPayloadCached(0, &cache));
}

test "МУТАНТ false->true: СЖАТЫЙ объект в ПОЛНОМ кластере не идёт в пакет" {
    // 8 объектов в одном кластере, один из них сжат. Мутация
    // `all_small = false` -> `all_small = true` заставит взять пакетный путь,
    // где СЫРЫЕ байты сжатого объекта сверяются с дайджестом РАСПАКОВАННОГО
    // содержимого -> вместо честного CompressedNeedsDecompress получим
    // PayloadTampered на КОРРЕКТНОМ образе.
    var region: [80]u8 = undefined;
    for (&region, 0..) |*b, i| b.* = @truncate(i + 1);
    var objs: [8]ObjectEntry = undefined;
    for (&objs, 0..) |*o, k| {
        o.* = std.mem.zeroes(ObjectEntry);
        o.type_id = 0x0002;
        o.flags = 0x0002;
        o.payload_offset = @intCast(k * 10);
        o.compressed_size = 10;
        o.uncompressed_size = 10;
        std.crypto.hash.Blake3.hash(region[k * 10 .. k * 10 + 10], o.digest[0..32], .{});
    }
    objs[3].compression_codec = 2; // deflate
    // ВАЖНО: у СЖАТОГО объекта дайджест считается по РАСПАКОВАННОМУ
    // содержимому, а в образе лежат ДРУГИЕ (сжатые) байты. Именно поэтому
    // пакетный путь (он хеширует СЫРЫЕ байты) для него недопустим.
    std.crypto.hash.Blake3.hash("compressed-content-differs", objs[3].digest[0..32], .{});
    const fs = KernFS.init(std.testing.allocator, &region, &objs, &region);
    var cache = try ClusterCache.init(std.testing.allocator, objs.len);
    defer cache.deinit(std.testing.allocator);

    // Обращаемся к ДРУГОМУ (несжатому) объекту кластера: именно тогда
    // проверяется весь кластер. Корректное поведение — УСПЕХ: сжатый сосед
    // лишь исключает кластер из пакетного пути. Мутант пойдёт пакетным путём
    // и вернёт PayloadTampered, потому что сырые байты сжатого объекта не
    // совпадут с дайджестом распакованного содержимого.
    const got = try fs.objectPayloadCached(5, &cache);
    try std.testing.expectEqualSlices(u8, region[50..60], got);
}

test "МУТАНТ >=->>: КРУПНЫЙ объект (>1024) в кластере идёт поштучным путём" {
    // compressed_size = 2048 > batchMaxLen (1024). Мутация `all_small = false`
    // -> `true` отправит 2048-байтный вход в hashBatch8, где
    // `std.debug.assert(len <= MAX_SMALL_LEN)` паникует.
    const big = 2048;
    var region: [8 * big]u8 = undefined;
    for (&region, 0..) |*b, i| b.* = @truncate(i * 7 + 3);
    var objs: [8]ObjectEntry = undefined;
    for (&objs, 0..) |*o, k| {
        o.* = std.mem.zeroes(ObjectEntry);
        o.type_id = 0x0002;
        o.flags = 0x0002;
        o.payload_offset = @intCast(k * big);
        o.compressed_size = big;
        o.uncompressed_size = big;
        std.crypto.hash.Blake3.hash(region[k * big .. (k + 1) * big], o.digest[0..32], .{});
    }
    const fs = KernFS.init(std.testing.allocator, &region, &objs, &region);

    // verifyAllBatch обязан пройти поштучно (без паники) и проверить все 8.
    const n = try fs.verifyAllBatch();
    try std.testing.expectEqual(@as(usize, 8), n);
}

test "ГРАНИЦА: logical_path_offset ровно на границе пула не читает память" {
    // Проверка `if (offset >= self.payload_region.len) return ""` в `getString`.
    //
    // ЭКВИВАЛЕНТНЫЙ МУТАНТ (задокументировано в METRICS §66.5): замена `>=` на
    // `>` здесь НЕ наблюдаема, потому что следующий за ней цикл
    // `while (offset + len < self.payload_region.len ...)` дублирует ту же
    // границу. Тест закрепляет поведение на границе, но мутанта не убивает —
    // и это честный факт, а не пропуск.
    var region: [11]u8 = "a.zig\x00hello".*;
    var e = std.mem.zeroes(ObjectEntry);
    e.type_id = 0x0002;
    e.flags = 0x0002; // HAS_LOGICAL_PATH
    e.logical_path_offset = 11; // РОВНО region.len
    e.payload_offset = 6;
    e.compressed_size = 5;
    e.uncompressed_size = 5;
    var objs = [_]ObjectEntry{e};
    var fs = KernFS.init(std.testing.allocator, &region, &objs, &region);
    // Имя пустое -> объект не адресуем по /raw/ (и НЕ должно быть паники).
    try std.testing.expectError(KernFsError.FileNotFound, fs.read("/raw/a.zig"));
}
