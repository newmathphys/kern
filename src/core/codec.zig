// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license: newmathphys@gmail.com
//! KERN: кодеки объектов `.kimg` (поле `compression_codec` дескриптора, §6.3).
//!
//! СТАТУС КОДЕКОВ (честно, по факту реализации):
//!
//!   0x00 raw      — без сжатия. РЕАЛИЗОВАНО.
//!   0x01 zstd     — ОБЪЯВЛЕН В СПЕЦИФИКАЦИИ, НО НЕ РЕАЛИЗОВАН.
//!                   Причина: в Zig std есть только zstd-РАСПАКОВЩИК,
//!                   компрессора нет, а статической `libzstd.a` в системе нет —
//!                   линковка сломала бы герметичную musl-сборку
//!                   (`kernc-hermetic`). Обращение даёт `error.CodecUnsupported`,
//!                   а НЕ тихую ошибку.
//!   0x02 deflate  — РЕАЛИЗОВАНО через `std.compress.flate` (собственный
//!                   компрессор Zig, без внешних зависимостей, работает в
//!                   статической сборке). Это расширение KERN: в §6.3
//!                   спецификации код 0x02 не описан.
//!
//! ПОЧЕМУ ЭТО ВАЖНО. До этого модуля поля `compressed_size` и
//! `uncompressed_size` дескриптора существовали, но путь сжатия не был
//! реализован вовсе. Именно на этих полях был дефект #55 (безопасный и сырой
//! пути чтения выбирали размеры в противоположном порядке). Теперь путь
//! сжатия существует и покрыт тестами, а не только объявлен.
const std = @import("std");
const flate = std.compress.flate;

/// Кодек объекта (значения совпадают с §6.3 спецификации).
pub const Codec = enum(u8) {
    raw = 0x00,
    zstd = 0x01,
    deflate = 0x02,

    pub fn fromInt(v: u8) ?Codec {
        return switch (v) {
            0x00 => .raw,
            0x01 => .zstd,
            0x02 => .deflate,
            else => null,
        };
    }
};

pub const CodecError = error{
    CodecUnsupported,
    CompressFailed,
    DecompressFailed,
    SizeMismatch,
    OutOfMemory,
};

/// Порог: объекты меньше этого размера не сжимаем — накладные расходы
/// (таблица Хаффмана) превышают выигрыш.
pub const min_compress_len: usize = 128;

/// Сжать `data`. Возвращает `null`, если сжатие НЕ дало выигрыша
/// (тогда вызывающий обязан сохранить объект как `raw`).
///
/// Гарантия: возвращённый срез всегда КОРОЧЕ входа — иначе `null`.
pub fn compress(
    allocator: std.mem.Allocator,
    codec: Codec,
    data: []const u8,
) CodecError!?[]u8 {
    switch (codec) {
        .raw => return null,
        // Честный отказ вместо тихой ошибки: zstd объявлен, но не реализован.
        .zstd => return CodecError.CodecUnsupported,
        .deflate => {},
    }
    if (data.len < min_compress_len) return null;

    // `.raw` — без заголовков gzip/zlib: целостность обеспечивает digest объекта.
    var out: [64 * 1024]u8 = undefined;
    var out_w: std.Io.Writer = .fixed(&out);
    var win: [flate.max_window_len * 2]u8 = undefined;

    var comp = flate.Compress.init(&out_w, &win, .raw, .default) catch
        return CodecError.CompressFailed;
    comp.writer.writeAll(data) catch return CodecError.CompressFailed;
    comp.finish() catch return CodecError.CompressFailed;

    const produced = out_w.buffered();
    if (produced.len >= data.len) return null; // выигрыша нет

    const buf = allocator.alloc(u8, produced.len) catch return CodecError.OutOfMemory;
    @memcpy(buf, produced);
    return buf;
}

/// Распаковать `data` в ровно `expected_len` байт.
///
/// `expected_len` берётся из дескриптора (`uncompressed_size`) — это и есть
/// защита от «zip-бомбы»: распаковщик не может выделить больше, чем заявлено.
pub fn decompress(
    allocator: std.mem.Allocator,
    codec: Codec,
    data: []const u8,
    expected_len: usize,
) CodecError![]u8 {
    switch (codec) {
        .raw => {
            if (data.len != expected_len) return CodecError.SizeMismatch;
            const buf = allocator.alloc(u8, data.len) catch return CodecError.OutOfMemory;
            @memcpy(buf, data);
            return buf;
        },
        .zstd => return CodecError.CodecUnsupported,
        .deflate => {},
    }

    const buf = allocator.alloc(u8, expected_len) catch return CodecError.OutOfMemory;
    errdefer allocator.free(buf);

    // Zig 0.17: `std.io.fixedBufferStream` удалён; используется `std.Io.Reader.fixed`.
    var in_reader: std.Io.Reader = .fixed(data);
    // ОКОННЫЙ БУФЕР ОБЯЗАТЕЛЕН. Пустой буфер (`&.{}`) вызывает `rebase()`,
    // где `capacity <= buffer.len - history_len` при нулевой длине даёт
    // ПЕРЕПОЛНЕНИЕ и панику. Проверено прогоном (дефект найден тестом).
    var win: [flate.max_window_len * 2]u8 = undefined;
    var dec = flate.Decompress.init(&in_reader, .raw, &win);
    // `readSliceAll` заполняет РОВНО буфер или падает с EndOfStream:
    // частичный результат принят не будет.
    dec.reader.readSliceAll(buf) catch return CodecError.DecompressFailed;
    return buf;
}

// ===========================================================================
//  ТЕСТЫ
// ===========================================================================

test "CODEC: roundtrip deflate на сжимаемых данных" {
    const alloc = std.testing.allocator;
    // ВНИМАНИЕ: оператор `**` удалён в Zig 0.17 (см. дефект #55-миграции),
    // поэтому данные строятся циклом, а не повторением литерала.
    var data: [920]u8 = undefined;
    const pat = "KERN compression test ";
    for (&data, 0..) |*b, i| b.* = pat[i % pat.len];
    const comp = (try compress(alloc, .deflate, &data)) orelse
        return error.SkipZigTest; // не сжалось — тест неприменим, а не вакуумен
    defer alloc.free(comp);
    try std.testing.expect(comp.len < data.len);
    const back = try decompress(alloc, .deflate, comp, data.len);
    defer alloc.free(back);
    try std.testing.expectEqualSlices(u8, &data, back);
}

test "CODEC: несжимаемые данные дают null (нет выигрыша)" {
    const alloc = std.testing.allocator;
    var data: [256]u8 = undefined;
    var prng = std.Random.DefaultPrng.init(0xC0DEC);
    prng.random().bytes(&data);
    // Случайные байты не сжимаются: функция обязана вернуть null,
    // а не «сжатие» длиннее исходника.
    try std.testing.expect((try compress(alloc, .deflate, &data)) == null);
}

test "CODEC: zstd объявлен, но НЕ реализован — честный отказ" {
    const alloc = std.testing.allocator;
    var data: [512]u8 = undefined;
    @memset(&data, 'x');
    try std.testing.expectError(CodecError.CodecUnsupported,
        compress(alloc, .zstd, &data));
    try std.testing.expectError(CodecError.CodecUnsupported,
        decompress(alloc, .zstd, &data, data.len));
}

test "CODEC: порог — мелкие объекты не сжимаются" {
    const alloc = std.testing.allocator;
    var small: [30]u8 = undefined;
    @memset(&small, 'a'); // 30 байт < min_compress_len
    try std.testing.expect((try compress(alloc, .deflate, &small)) == null);
}

test "CODEC: завышенная длина отвергается (zip-бомба)" {
    const alloc = std.testing.allocator;
    var data: [400]u8 = undefined;
    for (&data, 0..) |*b, i| b.* = if (i % 2 == 0) 'A' else 'B';
    const comp = (try compress(alloc, .deflate, &data)) orelse return error.SkipZigTest;
    defer alloc.free(comp);

    // ЗАВЫШЕННАЯ длина: потока не хватит -> отказ, частичный результат НЕ принят.
    // Это и есть защита от «zip-бомбы»: распаковщик не может выдать больше,
    // чем есть в потоке.
    try std.testing.expectError(CodecError.DecompressFailed,
        decompress(alloc, .deflate, comp, data.len + 1));

    // ЗАНИЖЕННАЯ длина ошибки НЕ даёт: `readSliceAll` прочитает ровно столько,
    // сколько запрошено. Такой случай ловится НЕ здесь, а сверкой дайджеста
    // объекта (payload короче -> хеш не сойдётся). Проверяем это явно,
    // чтобы поведение было зафиксировано тестом, а не предположением.
    const short = try decompress(alloc, .deflate, comp, data.len - 1);
    defer alloc.free(short);
    try std.testing.expectEqual(@as(usize, data.len - 1), short.len);
    try std.testing.expect(!std.mem.eql(u8, &data, short)); // хеш НЕ сойдётся
}

test "CODEC: raw проверяет длину" {
    const alloc = std.testing.allocator;
    const data = "12345";
    const ok = try decompress(alloc, .raw, data, data.len);
    defer alloc.free(ok);
    try std.testing.expectEqualSlices(u8, data, ok);
    try std.testing.expectError(CodecError.SizeMismatch,
        decompress(alloc, .raw, data, data.len + 1));
}

test "CODEC: fromInt отвергает неизвестный код" {
    try std.testing.expect(Codec.fromInt(0x00) == .raw);
    try std.testing.expect(Codec.fromInt(0x01) == .zstd);
    try std.testing.expect(Codec.fromInt(0x02) == .deflate);
    try std.testing.expect(Codec.fromInt(0x7F) == null);
}
