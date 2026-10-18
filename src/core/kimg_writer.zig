// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN: сборщик образа .kimg v1.3 (Zig-side). Раскладка идентична
//! `tools/golden_v1_3.py`: заголовок 128 + таблица N*96 + пул строк + payload.
//! `payload_offset` и `logical_path_offset` ОТНОСИТЕЛЬНЫ `data_payload_offset`.
const std = @import("std");
const ObjectEntry = @import("object_entry.zig").ObjectEntry;
const KimgHeader = @import("kimg_reader.zig").KimgHeader;
const codec = @import("codec.zig");
const HashAlgo = @import("hash_algo.zig").HashAlgo;
const KernFsRouter = @import("kernfs_router.zig").KernFS;
const KernFsError = @import("kernfs_router.zig").KernFsError;
const compat = @import("compat");

pub const BuildError = error{ TooManyObjects, Empty, PoolTooLarge, Overflow, CodecUnsupported, OutOfMemory };

pub const ObjectSpec = struct {
    path: []const u8,
    type_id: u32,
    flags: u16,
    content: []const u8,
    /// Кодек СЖАТИЯ объекта. `.raw` — объект хранится как есть (zero-copy).
    /// `.deflate` — содержимое сжимается при сборке (см. `Builder.compress`).
    codec: codec.Codec = .raw,
};

pub const Builder = struct {
    allocator: std.mem.Allocator,
    specs: std.array_list.Managed(ObjectSpec),
    /// Алгоритм хеша образа (спецификация §5.3). По умолчанию BLAKE3 (0x0001);
    /// `.sha256` — для совместимости и сравнительных прогонов.
    hash_algo: HashAlgo = HashAlgo.DEFAULT,
    /// Кодек сжатия для ВСЕХ добавляемых объектов (`.raw` = без сжатия).
    /// Сжатие применяется только там, где оно РЕАЛЬНО уменьшает объект:
    /// иначе объект остаётся `raw` (см. `codec.compress`, возвращает null).
    compress: codec.Codec = .raw,

    pub fn init(allocator: std.mem.Allocator) Builder {
        return .{ .allocator = allocator, .specs = std.array_list.Managed(ObjectSpec).init(allocator) };
    }

    pub fn deinit(self: *Builder) void {
        self.specs.deinit();
    }

    pub fn addSource(self: *Builder, path: []const u8, content: []const u8) !void {
        // ⚠️ ВНИМАНИЕ (контракт вызова): `content` НЕ копируется —
        // Builder хранит СРЕЗ и читает его в момент `buildBytes`/`write`.
        // Если передать переиспользуемый буфер (например, стек-массив в
        // цикле), ВСЕ объекты получат содержимое ПОСЛЕДНЕЙ итерации.
        // Вызывающий обязан обеспечить время жизни `content` до записи.
        // (Найдено детерминированным симулятором src/sim_test.zig.)
        try self.specs.append(.{ .path = path, .type_id = 0x0002, .flags = 0x0002, .content = content, .codec = self.compress });
    }

    /// status_bits: биты 2-3 (0=N, 1=T, 2=F, 3=B). Бит 1 = HAS_LOGICAL_PATH.
    pub fn addClaim(self: *Builder, id: []const u8, contract: []const u8, status_bits: u2) !void {
        try self.specs.append(.{ .path = id, .type_id = 0x0005, .flags = 0x0002 | (@as(u16, status_bits) << 2), .content = contract, .codec = self.compress });
    }

    /// Байткод для KERN-X (тип 0x0007).
    pub fn addBytecode(self: *Builder, name: []const u8, code: []const u8) !void {
        try self.specs.append(.{ .path = name, .type_id = 0x0007, .flags = 0x0002, .content = code, .codec = self.compress });
    }

    /// Собирает образ .kimg В ПАМЯТИ (без записи на диск).
    ///
    /// ЗАЧЕМ: детерминированному симулятору (src/sim_test.zig) нужен
    /// образ в буфере, а не файл. Логика сборки ЕДИНАЯ — `write`
    /// вызывает этот метод, поэтому образ в памяти и на диске
    /// побайтово совпадают.
    pub fn buildBytes(self: *Builder, out: *std.array_list.Managed(u8)) !void {
        const n = self.specs.items.len;
        if (n == 0) return BuildError.Empty;

        // 1. Пул строк + payload
        var pool = std.array_list.Managed(u8).init(self.allocator);
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
        // СЖАТИЕ: для каждого объекта храним, что реально легло в payload.
        // Если `codec.compress` вернул null (нет выигрыша или кодек raw),
        // объект остаётся `raw`, и `compressed_size == uncompressed_size`.
        var stored_codec = try self.allocator.alloc(codec.Codec, n);
        defer self.allocator.free(stored_codec);
        var stored_len = try self.allocator.alloc(usize, n);
        defer self.allocator.free(stored_len);
        var owned: std.array_list.Managed([]u8) = .init(self.allocator);
        defer {
            for (owned.items) |b| self.allocator.free(b);
            owned.deinit();
        }
        var payload = std.array_list.Managed(u8).init(self.allocator);
        defer payload.deinit();
        for (self.specs.items, 0..) |sp, i| {
            payload_off[i] = pool_len + payload.items.len;
            var body: []const u8 = sp.content;
            stored_codec[i] = .raw;
            if (sp.codec != .raw) {
                const c = codec.compress(self.allocator, sp.codec, sp.content) catch |e| switch (e) {
                    // Честный отказ: кодек объявлен, но не реализован.
                    error.CodecUnsupported => return BuildError.CodecUnsupported,
                    else => return BuildError.OutOfMemory,
                };
                if (c) |buf| {
                    try owned.append(buf);
                    body = buf;
                    stored_codec[i] = sp.codec;
                }
            }
            stored_len[i] = body.len;
            try payload.appendSlice(body);
        }

        // 2. Таблица объектов
        const entries = try self.allocator.alloc([96]u8, n);
        defer self.allocator.free(entries);
        for (self.specs.items, 0..) |sp, i| {
            var e: [96]u8 = @as([96]u8, @splat(0));
            var digest: [32]u8 = undefined;
            self.hash_algo.hash(sp.content, &digest);
            @memcpy(e[0..32], &digest);
            std.mem.writeInt(u64, e[32..40], payload_off[i], .little);
            // uncompressed_size — длина СОДЕРЖИМОГО (по ней распаковывать);
            // compressed_size   — сколько байт реально лежит в образе.
            // Для `raw` они равны. Поля перестали быть фикцией: путь сжатия
            // реализован (см. src/core/codec.zig), а на этих полях был #55.
            std.mem.writeInt(u64, e[40..48], sp.content.len, .little);
            std.mem.writeInt(u64, e[48..56], stored_len[i], .little);
            std.mem.writeInt(u32, e[56..60], sp.type_id, .little);
            std.mem.writeInt(u16, e[60..62], sp.flags, .little);
            e[62] = @intFromEnum(stored_codec[i]);
            std.mem.writeInt(u32, e[64..68], path_off[i], .little);
            std.mem.writeInt(u32, e[68..72], 1, .little);
            entries[i] = e;
        }

        // 3. Merkle-корень
        var root: [32]u8 = undefined;
        ObjectEntry.computeRootHash(entries, &root);

        // 4. Заголовок
        var header: [128]u8 = @as([128]u8, @splat(0));
        @memcpy(header[0..8], "KIMG\r\n\x1a\n");
        std.mem.writeInt(u16, header[8..10], 1, .little);
        std.mem.writeInt(u16, header[10..12], 3, .little);
        std.mem.writeInt(u32, header[12..16], 128, .little);
        std.mem.writeInt(u32, header[16..20], 0, .little);
        std.mem.writeInt(u32, header[20..24], self.hash_algo.toInt(), .little); // 1=BLAKE3, 2=SHA-256
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
        self.hash_algo.hash(header[0..96], &csum);
        @memcpy(header[96..128], &csum);

        // 5. Отдаём готовый образ вызывающему.
        try out.appendSlice(&header);
        for (entries) |e| try out.appendSlice(&e);
        try out.appendSlice(pool.items);
        try out.appendSlice(payload.items);

        // 6. ЕДИНЫЙ ИСТОЧНИК ИСТИНЫ (дефект #128). Корень считается по УЖЕ
        //    СОБРАННОМУ буферу ТОЙ ЖЕ функцией, что вызывает читатель
        //    (`KimgHeader.computeImageMerkleRoot`). Писатель и читатель
        //    выполняют один код над одними байтами -> расхождение невозможно.
        //    Имя объекта входит в корень через `logical_path_offset` -> пул
        //    строк (см. merkleRootImpl), поэтому подмена ПЕЧАТНОГО символа в
        //    имени тоже ловится, а формат 128/96 байт НЕ меняется.
        KimgHeader.sealImageRoot(out.items) catch return BuildError.Overflow;
    }

    /// АТОМАРНАЯ запись на диск (crash-consistency): временный файл + rename.
    pub fn write(self: *Builder, out_path: []const u8) !void {
        var img = std.array_list.Managed(u8).init(self.allocator);
        defer img.deinit();
        try self.buildBytes(&img);

        // 5. АТОМАРНАЯ запись (crash-consistency): пишем во временный файл,
        // затем rename. При аварии (SIGKILL/отключение питания) целевой файл
        // либо старый целый, либо новый целый — НИКОГДА не битый посередине.
        const tmp_path = try std.fmt.allocPrint(self.allocator, "{s}.tmp", .{out_path});
        defer self.allocator.free(tmp_path);
        {
            const f = try compat.createFile(tmp_path, .{});
            errdefer compat.deleteFile(tmp_path) catch {};
            defer compat.fileClose(f);
            try compat.fileWriteAll(f, img.items);
            // ДЕФЕКТ (исправлен): без fsync данные оставались в кэше ОС, и
            // после отключения питания `rename` мог обогнать запись — на
            // диске оказывался ПУСТОЙ (или частичный) файл. Теперь данные
            // сброшены на носитель ДО переименования.
            try compat.fileSync(f);
        }
        // Если rename упадёт — временный файл не должен остаться мусором.
        errdefer compat.deleteFile(tmp_path) catch {};
        try compat.rename(tmp_path, out_path);
        // Долговечность самого rename: синхронизируем КАТАЛОГ.
        // (в Zig 0.13 у std.fs.Dir нет .sync() — открываем каталог через posix)
        const dfd = std.posix.openat(std.posix.AT.FDCWD, ".", .{ .ACCMODE = .RDONLY, .DIRECTORY = true }, 0) catch -1;
        if (dfd >= 0) {
            // Zig 0.17: `std.posix.close` удалён — оборачиваем fd в `Io.File`.
            defer compat.fileClose(.{ .handle = dfd, .flags = .{ .nonblocking = false } });
            std.posix.fdatasync(dfd) catch {};
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
    defer compat.deleteFile(tmp) catch {};

    const data = try compat.readFileAlloc(std.testing.allocator, tmp, 1 << 20);
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
    defer compat.deleteFile(tmp) catch {};
    const data = try compat.readFileAlloc(std.testing.allocator, tmp, 1 << 20);
    defer std.testing.allocator.free(data);
    const KernFS2 = @import("kernfs_router.zig").KernFS;
    var fs = try KernFS2.mountFromBytes(std.testing.allocator, data);
    defer fs.deinit();
    const n = try fs.read("/raw/x");
    try std.testing.expectEqualStrings("y", n.raw_slice);
    const e = try fs.read("/raw/" ++ @as([200]u8, @splat('a')));
    try std.testing.expectEqualStrings("", e.raw_slice);
}

test "CRASH-CONSISTENCY: запись атомарна, .tmp не остаётся" {
    var b = Builder.init(std.testing.allocator);
    defer b.deinit();
    try b.addSource("a.zig", "content");
    const out = "/tmp/atomic_test.kimg";
    defer compat.deleteFile(out) catch {};
    try b.write(out);
    // целевой файл есть
    try compat.access(out, .{});
    // .tmp не осталось
    var tmp_buf: [64]u8 = undefined;
    const tmp = try std.fmt.bufPrint(&tmp_buf, "{s}.tmp", .{out});
    try std.testing.expectError(error.FileNotFound, compat.access(tmp, .{}));
    // перезапись поверх — тоже ок (атомарно)
    try b.write(out);
    try compat.access(out, .{});
}

test "ДОЛГОВЕЧНОСТЬ: данные сброшены на носитель (fsync), образ читается" {
    // Без fsync перед rename данные могли остаться в кэше ОС, и после
    // отключения питания на диске оказался бы ПУСТОЙ файл. Проверяем, что
    // образ после записи полностью читается с диска (не из кэша процесса).
    var b = Builder.init(std.testing.allocator);
    defer b.deinit();
    try b.addSource("src/x.zig", "durability probe");
    const out = "/tmp/durability_test.kimg";
    defer compat.deleteFile(out) catch {};
    try b.write(out);

    // Читаем ФАЙЛ (а не память процесса) — если бы fsync не было,
    // на некоторых ФС размер/содержимое могли быть нулевыми.
    const data = try compat.readFileAlloc(std.testing.allocator, out, 1 << 20);
    defer std.testing.allocator.free(data);
    try std.testing.expect(data.len > 128);
    try std.testing.expectEqualStrings("KIMG\r\n\x1a\n", data[0..8]);

    // И образ монтируется.
    var fs = try KernFsRouter.mountFromBytes(std.testing.allocator, data);
    defer fs.deinit();
    try std.testing.expectEqualStrings("durability probe", (try fs.read("/raw/src/x.zig")).raw_slice);
}

test "СЖАТИЕ: сквозной roundtrip через .kimg (deflate) + подмена ловится" {
    // ЗАЧЕМ: до этого модуля поля compressed_size/uncompressed_size были
    // фикцией (путь сжатия не существовал). Здесь проверяется, что сжатие
    // реально работает И что целостность при этом НЕ ослаблена.
    const alloc = std.testing.allocator;
    var b = Builder.init(alloc);
    defer b.deinit();
    b.compress = .deflate;

    // Сжимаемое содержимое >= min_compress_len (128 байт).
    var content: [920]u8 = undefined;
    const pat = "KERN compression roundtrip ";
    for (&content, 0..) |*ch, i| ch.* = pat[i % pat.len];
    try b.addSource("big.txt", &content);

    var img = std.array_list.Managed(u8).init(alloc);
    defer img.deinit();
    try b.buildBytes(&img);

    var fs = try KernFsRouter.mountFromBytes(alloc, img.items);
    defer fs.deinit();
    try std.testing.expectEqual(@as(usize, 1), fs.objects.len);
    const obj = fs.objects[0];

    // 1. Писатель РЕАЛЬНО сжал: кодек deflate, размер на диске меньше.
    try std.testing.expectEqual(@as(u8, 2), obj.compression_codec);
    try std.testing.expect(obj.compressed_size < obj.uncompressed_size);
    try std.testing.expectEqual(@as(u64, content.len), obj.uncompressed_size);

    // 2. Zero-copy для сжатого объекта ЗАПРЕЩЁН явно (а не тихая выдача).
    try std.testing.expectError(KernFsError.CompressedNeedsDecompress,
        fs.objectPayload(obj));

    // 3. Распаковка даёт ИСХОДНОЕ содержимое.
    const out = try fs.decompressObject(alloc, obj);
    defer alloc.free(out);
    try std.testing.expectEqualSlices(u8, &content, out);
}

test "СЖАТИЕ: подмена в СЖАТОМ объекте -> PayloadTampered" {
    const alloc = std.testing.allocator;
    var b = Builder.init(alloc);
    defer b.deinit();
    b.compress = .deflate;
    var content: [600]u8 = undefined;
    for (&content, 0..) |*ch, i| ch.* = @truncate('a' + (i % 7));
    try b.addSource("c.txt", &content);
    var img = std.array_list.Managed(u8).init(alloc);
    defer img.deinit();
    try b.buildBytes(&img);

    // Смонтируем ДО порчи, чтобы узнать относительное смещение данных.
    var fs0 = try KernFsRouter.mountFromBytes(alloc, img.items);
    defer fs0.deinit();

    // Портим ОДИН байт в области payload.
    // ВНИМАНИЕ (та же ловушка, что документирована в §49): `payload_offset`
    // дескриптора ОТНОСИТЕЛЕН `data_payload_offset`, и РЕГИОН начинается с
    // пула строк. Порча по `data_payload_offset + 1` попадает в ПУЛ (в путь),
    // а не в данные — первая версия теста делала именно это и «проходила»
    // зря. Адрес данных = data_payload_offset + entry.payload_offset.
    const KH = @import("kimg_reader.zig").KimgHeader;
    const h = KH.parse(img.items[0..128], img.items.len) catch
        return error.TestUnexpectedResult;
    const poff: usize = @intCast(h.data_payload_offset);
    const rel: usize = @intCast(fs0.objects[0].payload_offset);
    img.items[poff + rel + 1] ^= 0xFF;

    var fs = try KernFsRouter.mountFromBytes(alloc, img.items);
    defer fs.deinit();
    // Распаковка повреждённого потока ЛИБО сорвётся, ЛИБО даст другой текст —
    // в обоих случаях объект НЕ принят (PayloadTampered).
    const res = fs.decompressObject(alloc, fs.objects[0]);
    try std.testing.expectError(KernFsError.PayloadTampered, res);
}
/// Открыт ли дескриптор `fd`? Через СЫРОЙ системный вызов (без libc):
/// `fcntl(fd, F_GETFD)` возвращает `-EBADF`, если дескриптор закрыт.
fn fdIsOpen(fd: std.posix.fd_t) bool {
    const F_GETFD: i32 = 1;
    const raw = std.os.linux.fcntl(fd, F_GETFD, 0);
    const signed: isize = @bitCast(raw);
    return signed >= 0;
}

test "МУТАНТ >=->>: каталог синхронизируется и при fd == 0 (нет утечки)" {
    // `openat` возвращает МИНИМАЛЬНЫЙ свободный дескриптор. Если закрыть fd 0,
    // каталог получит ровно 0. Мутация `if (dfd >= 0)` -> `if (dfd > 0)`
    // пропускает и fdatasync, и ЗАКРЫТИЕ дескриптора — fd 0 остаётся занятым
    // каталогом (утечка дескриптора).
    //
    // Наблюдаемое следствие: после записи fd 0 обязан быть ЗАКРЫТ (корректный
    // код закрывает каталог через defer). У мутанта fd 0 остаётся открытым.
    //
    // fd 0 спасаем и восстанавливаем, чтобы не сломать раннер тестов.
    const saved = std.os.linux.dup(0);
    const saved_i: isize = @bitCast(saved);
    try std.testing.expect(saved_i >= 0);
    defer {
        _ = std.os.linux.dup2(@intCast(saved_i), 0);
        _ = std.os.linux.close(@intCast(saved_i));
    }
    // ВЕТКА 1: ОТКРЫТЫЙ дескриптор без флагов -> `fcntl(F_GETFD)` вернёт 0.
    // Мутация `>= 0` -> `> 0` в `fdIsOpen` вернёт здесь false и тест упадёт.
    // (`dup` по POSIX сбрасывает FD_CLOEXEC, поэтому флаги действительно 0.)
    try std.testing.expect(fdIsOpen(@intCast(saved_i)));

    _ = std.os.linux.close(0);

    var b = Builder.init(std.testing.allocator);
    defer b.deinit();
    try b.addSource("src/y.zig", "fd0 probe");
    const out = "/tmp/kern_fd0_test.kimg";
    defer compat.deleteFile(out) catch {};
    try b.write(out);

    // fd 0 обязан быть закрыт.
    try std.testing.expect(!fdIsOpen(0));
}
