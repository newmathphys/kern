// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN: 8-полосный SIMD BLAKE3 для МЕЛКИХ объектов (<= 1024 Б).
//!
//! ЗАЧЕМ. На мелких объектах (96–200 Б) BLAKE3 работает в одну полосу: чанк
//! не кратен 1024 Б, дерево Меркла не раскрывается, и все накладные расходы
//! (инициализация состояния, финализация) приходятся на один объект. Замер
//! (`make bench-hash`): 259 МБ/с на 96 Б против 2601 МБ/с на 64 КиБ.
//!
//! ЧТО ДЕЛАЕМ. Хешируем 8 НЕЗАВИСИМЫХ объектов одной векторной операцией
//! `@Vector(8, u32)` — 8 полос AVX2 (или NEON) заняты одновременно. Каждый
//! объект остаётся однократным чанком, поэтому схема сжатия та же, что у
//! `std.crypto.hash.Blake3`, и дайджесты совпадают БИТ-В-БИТ.
//!
//! ПРО БЕЗОПАСНОСТЬ: пакетная обработка НЕ ослабляет проверку. Каждый из 8
//! результатов сверяется со СВОИМ 32-байтным `entry.digest` из таблицы
//! дескрипторов. Порча одного байта в любой полосе даёт несовпадение и
//! `error.PayloadTampered`. Формат `.kimg` не меняется ни на байт.
//!
//! ОГРАНИЧЕНИЕ: длины входов могут быть РАЗНЫМИ (0..1024), но каждый вход
//! обязан быть <= 1024 Б, то есть однократным чанком.
const std = @import("std");

/// Максимальная длина объекта, для которой применим этот путь: один чанк.
pub const MAX_SMALL_LEN: usize = 1024;

const V8 = @Vector(8, u32);
const Mask8 = @Vector(8, bool);

const IV = [8]u32{
    0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
    0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19,
};

/// Порядок перемешивания слов по раундам (спецификация BLAKE3).
const MSG_SCHEDULE = [7][16]usize{
    .{ 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15 },
    .{ 2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8 },
    .{ 3, 4, 10, 12, 13, 2, 7, 14, 6, 5, 9, 0, 11, 15, 8, 1 },
    .{ 10, 7, 12, 9, 14, 3, 13, 15, 4, 0, 11, 2, 5, 8, 1, 6 },
    .{ 12, 13, 9, 11, 15, 10, 14, 8, 7, 2, 5, 3, 0, 1, 6, 4 },
    .{ 9, 14, 11, 5, 8, 12, 15, 1, 13, 3, 0, 10, 2, 6, 4, 7 },
    .{ 11, 15, 5, 0, 1, 9, 8, 6, 14, 10, 2, 12, 3, 4, 7, 13 },
};

const CHUNK_START: u32 = 1 << 0;
const CHUNK_END: u32 = 1 << 1;
const ROOT: u32 = 1 << 3;

inline fn rotr8(x: V8, comptime n: u5) V8 {
    const sh: @Vector(8, u5) = @splat(n);
    const inv: @Vector(8, u5) = @splat(@as(u5, @intCast(32 - @as(u6, n))));
    return (x >> sh) | (x << inv);
}

inline fn g8(
    state: *[16]V8,
    comptime a: usize,
    comptime b: usize,
    comptime c: usize,
    comptime d: usize,
    mx: V8,
    my: V8,
) void {
    state[a] = state[a] +% state[b] +% mx;
    state[d] = rotr8(state[d] ^ state[a], 16);
    state[c] = state[c] +% state[d];
    state[b] = rotr8(state[b] ^ state[c], 12);
    state[a] = state[a] +% state[b] +% my;
    state[d] = rotr8(state[d] ^ state[a], 8);
    state[c] = state[c] +% state[d];
    state[b] = rotr8(state[b] ^ state[c], 7);
}

inline fn round8(state: *[16]V8, m: *const [16]V8, comptime s: [16]usize) void {
    g8(state, 0, 4, 8, 12, m[s[0]], m[s[1]]);
    g8(state, 1, 5, 9, 13, m[s[2]], m[s[3]]);
    g8(state, 2, 6, 10, 14, m[s[4]], m[s[5]]);
    g8(state, 3, 7, 11, 15, m[s[6]], m[s[7]]);
    g8(state, 0, 5, 10, 15, m[s[8]], m[s[9]]);
    g8(state, 1, 6, 11, 12, m[s[10]], m[s[11]]);
    g8(state, 2, 7, 8, 13, m[s[12]], m[s[13]]);
    g8(state, 3, 4, 9, 14, m[s[14]], m[s[15]]);
}

/// Сжатие блока с ПОЛОСНОЙ маской: полосы, для которых блок уже кончился
/// (`active == false`), сохраняют прежнее состояние.
inline fn compress8Masked(
    cv: *[8]V8,
    m: *const [16]V8,
    block_len: V8,
    flags: V8,
    active: Mask8,
) void {
    var state: [16]V8 = .{
        cv[0],          cv[1],          cv[2],         cv[3],
        cv[4],          cv[5],          cv[6],         cv[7],
        @splat(IV[0]),  @splat(IV[1]),  @splat(IV[2]), @splat(IV[3]),
        @splat(0),      @splat(0),      block_len,     flags,
    };
    inline for (0..7) |r| round8(&state, m, MSG_SCHEDULE[r]);
    inline for (0..8) |i| {
        const next_cv = state[i] ^ state[i + 8];
        cv[i] = @select(u32, active, next_cv, cv[i]);
    }
}

/// Вычислить 8 дайджестов BLAKE3 одновременно. Длины входов могут
/// различаться; каждый вход обязан быть <= `MAX_SMALL_LEN`.
pub fn hash8SmallObjects(inputs: [8][]const u8, outputs: *[8][32]u8) void {
    var cv: [8]V8 = .{
        @splat(IV[0]), @splat(IV[1]), @splat(IV[2]), @splat(IV[3]),
        @splat(IV[4]), @splat(IV[5]), @splat(IV[6]), @splat(IV[7]),
    };

    var num_blocks_arr: [8]u32 = undefined;
    var max_blocks: u32 = 1;
    inline for (0..8) |lane| {
        const len = inputs[lane].len;
        std.debug.assert(len <= MAX_SMALL_LEN);
        // Пустой вход — это один блок нулевой длины (как у std.Blake3).
        const nb: u32 = if (len == 0) 1 else @intCast((len + 63) / 64);
        num_blocks_arr[lane] = nb;
        if (nb > max_blocks) max_blocks = nb;
    }
    const num_blocks_vec: V8 = num_blocks_arr;

    var block_idx: u32 = 0;
    while (block_idx < max_blocks) : (block_idx += 1) {
        const offset: usize = @as(usize, block_idx) * 64;
        const active: Mask8 = @as(V8, @splat(block_idx)) < num_blocks_vec;

        var blk_len_arr: [8]u32 = undefined;
        var flags_arr: [8]u32 = undefined;
        inline for (0..8) |lane| {
            const len = inputs[lane].len;
            const rem = if (len > offset) len - offset else 0;
            blk_len_arr[lane] = @intCast(@min(rem, 64));
            var flg: u32 = 0;
            if (block_idx == 0) flg |= CHUNK_START;
            if (block_idx + 1 == num_blocks_arr[lane]) flg |= (CHUNK_END | ROOT);
            flags_arr[lane] = flg;
        }

        var m: [16]V8 = undefined;
        var w: usize = 0;
        while (w < 16) : (w += 1) {
            var lane_words: V8 = @splat(0);
            const word_off = offset + w * 4;
            inline for (0..8) |lane| {
                const slice = inputs[lane];
                if (word_off + 4 <= slice.len) {
                    lane_words[lane] = std.mem.readInt(u32, slice[word_off..][0..4], .little);
                } else if (word_off < slice.len) {
                    var tail: [4]u8 = @splat(0);
                    const avail = slice.len - word_off;
                    @memcpy(tail[0..avail], slice[word_off..slice.len]);
                    lane_words[lane] = std.mem.readInt(u32, &tail, .little);
                }
            }
            m[w] = lane_words;
        }

        compress8Masked(&cv, &m, blk_len_arr, flags_arr, active);
    }

    inline for (0..8) |word_i| {
        const vec_arr: [8]u32 = cv[word_i];
        inline for (0..8) |lane| {
            std.mem.writeInt(u32, outputs[lane][word_i * 4 ..][0..4], vec_arr[lane], .little);
        }
    }
}

// =========================================================================
// ТЕСТЫ
// =========================================================================

test "SIMD8: бит-в-бит совпадение со std.Blake3 на краевых длинах" {
    const lengths = [8]usize{ 0, 1, 63, 64, 65, 200, 512, 1024 };
    var buffers: [8][MAX_SMALL_LEN]u8 = undefined;
    var slices: [8][]const u8 = undefined;
    for (0..8) |lane| {
        for (&buffers[lane], 0..) |*b, i| {
            b.* = @truncate((lane * 53 + i * 17 + 11) & 0xFF);
        }
        slices[lane] = buffers[lane][0..lengths[lane]];
    }

    var got: [8][32]u8 = undefined;
    hash8SmallObjects(slices, &got);
    for (0..8) |lane| {
        var want: [32]u8 = undefined;
        std.crypto.hash.Blake3.hash(slices[lane], &want, .{});
        try std.testing.expectEqualSlices(u8, &want, &got[lane]);
    }
}

test "SIMD8: разные длины в одной пачке — все полосы независимы" {
    // Монотонно разные входы: если полосы перепутают данные, дайджесты совпадут.
    var buf: [8][200]u8 = undefined;
    var slices: [8][]const u8 = undefined;
    for (0..8) |lane| {
        for (&buf[lane], 0..) |*b, i| b.* = @truncate((lane + 1) * 7 + i);
        slices[lane] = buf[lane][0 .. 100 + lane * 12];
    }
    var got: [8][32]u8 = undefined;
    hash8SmallObjects(slices, &got);
    for (0..8) |lane| {
        var want: [32]u8 = undefined;
        std.crypto.hash.Blake3.hash(slices[lane], &want, .{});
        try std.testing.expectEqualSlices(u8, &want, &got[lane]);
    }
    // Полосы не должны совпадать между собой (иначе перепутаны входы).
    for (0..8) |i| for (i + 1..8) |j| {
        try std.testing.expect(!std.mem.eql(u8, &got[i], &got[j]));
    };
}

test "SIMD8-АТАКА: подмена 1 байта в ОДНОЙ полосе ломает только её дайджест" {
    // Ровно тот сценарий, который проверяет конвейер чтения: если злоумышленник
    // испортит 1 байт в любом объекте пачки, дайджест ИМЕННО ЭТОЙ полосы обязан
    // измениться, а остальные 7 остаться прежними (иначе полосы перепутаны и
    // сверка со «своим» entry.digest была бы фикцией).
    var buf: [8][256]u8 = undefined;
    var slices: [8][]const u8 = undefined;
    for (0..8) |lane| {
        for (&buf[lane], 0..) |*b, i| b.* = @truncate((lane * 91 + i * 13 + 5) & 0xFF);
        slices[lane] = buf[lane][0..200];
    }
    var before: [8][32]u8 = undefined;
    hash8SmallObjects(slices, &before);

    // Портим ровно 1 байт в 7-й полосе (как canfail: payload-tamper).
    buf[6][137] ^= 0x01;
    var after: [8][32]u8 = undefined;
    hash8SmallObjects(slices, &after);

    try std.testing.expect(!std.mem.eql(u8, &before[6], &after[6])); // полоса 7 поймана
    for (0..8) |lane| {
        if (lane == 6) continue;
        try std.testing.expectEqualSlices(u8, &before[lane], &after[lane]);
    }
}
