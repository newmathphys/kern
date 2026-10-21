// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN: C-ABI — встраивание ядра в чужие системы (Python / Rust / Go / C++).
//!
//! Зачем: CLI через пайпы — это процесс, сериализация и задержка. C-ABI
//! позволяет вызвать ядро KERN НАПРЯМУЮ (скорость памяти) из любого языка.
//!
//! Сборка: `zig build lib` -> `zig-out/lib/libkern.so` + `include/kern.h`.
//! Все функции `export` имеют C-совместимые типы (только целые и указатели).
const std = @import("std");
const KimgHeader = @import("core/kimg_reader.zig").KimgHeader;
const hash_algo = @import("core/hash_algo.zig");
const z3b = @import("verifier/z3_bridge.zig");
const owner = @import("owner.zig");

/// Коды вердикта (совпадают с include/kern.h).
pub const KERN_PROVED: c_int = 0;
pub const KERN_REFUTED: c_int = 1;
pub const KERN_UNKNOWN: c_int = 2;
pub const KERN_TOOL_ERROR: c_int = -1;

/// Версия ядра.
/// Хеш данных тем же алгоритмом, что и ядро (спецификация §5.3).
///
/// ЗАЧЕМ В C-ABI. Клиенты (Python SDK, Rust, Go) обязаны считать хеши ТЕМ ЖЕ
/// кодом, что и ядро: иначе возможен рассинхрон реализаций. До этой функции
/// `tools/golden_v1_3.py` использовал сторонний pip-пакет `blake3` — то есть
/// Python и Zig считали хеш РАЗНЫМИ библиотеками. Теперь источник один.
///
///   algo   — 1 = BLAKE3-256, 2 = SHA2-256 (значения из спецификации);
///   data/len — входные байты (НЕ zero-terminated: длина передаётся явно);
///   out32  — буфер вызывающего ровно на 32 байта.
///
/// Возвращает: 0 = успех, -1 = неизвестный алгоритм (out32 не тронут).

/// ЗАЩИТА ОТ NULL (хардкор-аудит). В C вызывающий МОЖЕТ передать NULL, хотя
/// тип Zig `[*]const u8` этого не допускает. Без проверки `img[0]` по NULL
/// даёт SIGSEGV. Проверяем через @intFromPtr.
inline fn isNull(ptr: anytype) bool {
    return @intFromPtr(ptr) == 0;
}

export fn kern_hash(algo: c_uint, data: [*]const u8, len: usize, out32: [*]u8) c_int {
    if (isNull(out32)) return KERN_TOOL_ERROR;
    if (isNull(data) and len != 0) return KERN_TOOL_ERROR;
    const a = hash_algo.HashAlgo.fromInt(algo) orelse return KERN_TOOL_ERROR;
    var out: [32]u8 = undefined;
    a.hash(data[0..len], &out);
    @memcpy(out32[0..32], &out);
    return 0;
}

export fn kern_version() [*:0]const u8 {
    return "KERN v2.6.2 (C-ABI)";
}

/// Автор (для метки авторства в чужих сборках).
export fn kern_author() [*:0]const u8 {
    return owner.AUTHOR;
}

/// Проверка «ключа-замка» авторства: 1 = валиден, 0 = нет.
export fn kern_ownership_ok() c_int {
    return if (owner.verifyOwnership()) 1 else 0;
}

/// Проверка SMT-LIB2 контракта через реальный Z3.
///   KERN_PROVED (0) — доказано (unsat: контрпримеров нет);
///   KERN_REFUTED (1) — найден контрпример (sat);
///   KERN_UNKNOWN (2) — таймаут/неизвестно; KERN_TOOL_ERROR (-1) — нет решателя.
export fn kern_smt_verify(smt: [*]const u8, len: usize) c_int {
    if (isNull(smt) or len == 0) return KERN_TOOL_ERROR;
    const alloc = std.heap.c_allocator;
    var bridge = z3b.Z3Bridge.init(alloc);
    const r = bridge.executeQuery(smt[0..len]);
    if (r.witness_model) |m| alloc.free(m);
    return switch (r.status) {
        .Unsat => KERN_PROVED,
        .Sat => KERN_REFUTED,
        .Unknown, .Timeout => KERN_UNKNOWN,
        .ToolError => KERN_TOOL_ERROR,
    };
}

/// Проверка целостности образа .kimg (заголовок + Merkle-корень).
/// 1 = валиден, 0 = нет. НЕ аллоцирует память (zero-copy).
export fn kern_kimg_valid(img: [*]const u8, len: usize) c_int {
    if (isNull(img) or len < 128) return 0;
    const hdr: *const [128]u8 = @ptrCast(img);
    const h = KimgHeader.parse(hdr, len) catch return 0;
    KimgHeader.verifyMerkleRoot(img[0..len], h) catch return 0;
    return 1;
}

/// Число объектов в образе (-1 при ошибке).
// 0K.10: `c_long` на Windows (LLP64) — 32 бита, на Linux — 64.
// Возвращаем фиксированный i64, чтобы ABI не зависел от платформы.
export fn kern_kimg_object_count(img: [*]const u8, len: usize) i64 {
    if (isNull(img) or len < 128) return -1;
    const hdr: *const [128]u8 = @ptrCast(img);
    const h = KimgHeader.parse(hdr, len) catch return -1;
    return @intCast(h.object_count);
}

/// Доказательство через Z3 с РАЗБОРОМ неразрешимого ядра (fault localization).
/// Возвращает: вердикт, а через `out_buf` — список имён конфликтующих строк
/// (через пробел), если они есть. `out_buf_len` — размер буфера.
export fn kern_localize(
    decls: [*]const u8,
    decls_len: usize,
    pre: [*]const u8,
    pre_len: usize,
    goal: [*]const u8,
    goal_len: usize,
    out_buf: [*]u8,
    out_buf_len: usize,
) c_int {
    if (isNull(decls) or isNull(pre) or isNull(goal) or isNull(out_buf)) return KERN_TOOL_ERROR;
    if (decls_len == 0 or pre_len == 0 or goal_len == 0 or out_buf_len == 0) {
        return KERN_TOOL_ERROR;
    }
    const alloc = std.heap.c_allocator;
    const unsat_core = @import("verifier/unsat_core.zig");
    var bridge = z3b.Z3Bridge.init(alloc);
    var eng = unsat_core.UnsatCoreEngine.init(alloc);

    // 🔴 ИСПРАВЛЕНО: раньше ОДНА строка служила и объявлениями, и
    // предусловием. Из-за этого корректный вызов был невозможен: строка
    // `(declare-const x Int)` попадала в `(assert ...)`, а `x` оставался
    // необъявленным — Z3 отвечал ошибкой, и функция возвращала КОНТРПРИМЕР
    // с пустым списком виновников (ложная диагностика).
    // Теперь: decls — только объявления; pre — предусловие; goal — цель.
    const pres = [_]unsat_core.NamedAssertion{
        .{ .name = "pre", .formula = pre[0..pre_len] },
    };
    var core = eng.localize(&bridge, decls[0..decls_len], &pres, goal[0..goal_len]) catch
        return KERN_TOOL_ERROR;
    defer core.deinit();

    var written: usize = 0;
    for (core.conflicting, 0..) |name, i| {
        if (i > 0) {
            if (written + 1 >= out_buf_len) break;
            out_buf[written] = ' ';
            written += 1;
        }
        for (name) |ch| {
            if (written + 1 >= out_buf_len) break;
            out_buf[written] = ch;
            written += 1;
        }
    }
    out_buf[written] = 0;
    return if (core.is_conflict) KERN_PROVED else KERN_REFUTED;
}
