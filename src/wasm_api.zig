//! ЭШЕЛОН 8, ПУНКТ 40А: ядро KERN в WebAssembly (`wasm32-freestanding`).
//!
//! ЗАЧЕМ: дать возможность проверить решение/допуск БЕЗ установки Zig/Z3 —
//! прямо в браузере. Здесь экспортируются только те части ядра, которые не
//! делают системных вызовов:
//!   * решётка Белнапа B₄ (`JOIN_K`) и функция допуска `e`;
//!   * 64-битный код Хэмминга `AdmissionCode`;
//!   * встроенный решатель Фурье — Моцкина (`builtin_lia.zig`).
//!
//! ЧЕГО ЗДЕСЬ НЕТ (и почему): `proof_check.zig` тянет `z3_bridge.zig`
//! (спавн внешнего процесса `z3`), а в `wasm32-freestanding` системных
//! вызовов нет вообще. Поэтому в браузере доступна ПРОВЕРКА ЦЕЛОСТНОСТИ
//! решений и решатель LIA, но не перепроверка вывода Z3.
//!
//! ПАМЯТЬ: статический буфер 4 МБ + `FixedBufferAllocator` — никаких
//! обращений к ОС (0 syscalls). ИЗМЕРЕНО: 256 КБ НЕ ХВАТАЛО —
//! `kern_wasm_verify_proof` на 51-шаговом доказательстве `abs.c`
//! возвращал 0 (отказ аллокатора), хотя доказательство валидно.
//! 4 МБ хватает с запасом; размер модуля от размера буфера не зависит
//! (секция данных `undefined` в файл не пишется).
const std = @import("std");
const truth = @import("next/truth.zig");
const builtin_lia = @import("verifier/builtin_lia.zig");
const proof_check = @import("verifier/proof_check.zig");

/// Статическая арена: всё, что решателю нужно, живёт здесь.
var wasm_buf: [4 * 1024 * 1024]u8 = undefined;

/// Состояние аллокатора держим ГЛОБАЛЬНО: `allocator()` возвращает указатель
/// внутрь этого значения, поэтому локальная переменная дала бы висячий
/// указатель (поймано компилятором: `expected '*T', found '*const T'`).
var wasm_fba: std.heap.FixedBufferAllocator = undefined;

fn allocator() std.mem.Allocator {
    // Переинициализация перед каждым вызовом = «сброс арены»: буфер статический,
    // утечек между вызовами нет.
    wasm_fba = std.heap.FixedBufferAllocator.init(&wasm_buf);
    return wasm_fba.allocator();
}

/// Упаковка кванта Белнапа в байт: bit0 = `p` (подтверждение), bit1 = `n` (опровержение).
/// Так T=(1,0)->1, F=(0,1)->2, B=(1,1)->3, N=(0,0)->0.
fn packBit(b: truth.Bit) u8 {
    return @as(u8, @intFromBool(b.p)) | (@as(u8, @intFromBool(b.n)) << 1);
}

fn unpackBit(v: u8) truth.Bit {
    return .{ .p = (v & 1) != 0, .n = (v & 2) != 0 };
}

/// `JOIN_K` — монотонное объединение свидетельств двух агентов.
/// ИЗМЕРЕНО (нативный тест `test-next`): `JOIN_K(T, F) = B`, и `B` поглощает
/// любые последующие `T` (`JOIN_K(B, T) = B`) — противоречие НЕ перезаписывается.
export fn kern_wasm_belnap_join(a: u8, b: u8) u8 {
    return packBit(truth.Bit.join(unpackBit(a), unpackBit(b)));
}

/// Допуск Врат: `1` только для `T (1,0)`. `N`/`F`/`B` -> `0`.
export fn kern_wasm_belnap_allow(v: u8) u8 {
    return @intCast(truth.allowance(unpackBit(v)));
}

/// Проверка 64-битного кода Хэмминга: `1` — код распознан и искажений меньше
/// порога; `0` — отвергнуть (fail-closed).
export fn kern_wasm_admission_valid(code: u64) u8 {
    return if (truth.AdmissionCode.decode(code) != null) 1 else 0;
}

/// Встроенный решатель (Фурье — Моцкин) на ДВУХ ограничениях вида
/// `a*x + b*y + c <= 0`. Возврат: 1 = UNSAT (доказано), 2 = SAT, 0 = unknown.
/// ЗВУЧИМО: UNSAT у FM гарантирует несовместность над Z; SAT выдаётся только
/// при предъявлении конкретной целой точки, проверенной прямым вычислением.
export fn kern_wasm_lia_unsat2(a1: i64, b1: i64, c1: i64, a2: i64, b2: i64, c2: i64) u8 {
    var arena = std.heap.ArenaAllocator.init(allocator());
    defer arena.deinit();
    const al = arena.allocator();

    const t1 = al.alloc(builtin_lia.Term, 2) catch return 0;
    t1[0] = .{ .name = "x", .coeff = a1 };
    t1[1] = .{ .name = "y", .coeff = b1 };
    const t2 = al.alloc(builtin_lia.Term, 2) catch return 0;
    t2[0] = .{ .name = "x", .coeff = a2 };
    t2[1] = .{ .name = "y", .coeff = b2 };
    const sys = al.alloc(builtin_lia.Lin, 2) catch return 0;
    sys[0] = .{ .terms = t1, .constant = c1 };
    sys[1] = .{ .terms = t2, .constant = c2 };

    var solver = builtin_lia.Solver.init(al);
    defer solver.deinit();
    return switch (builtin_lia.checkUnsat(&solver, sys)) {
        .unsat => 1,
        .sat => 2,
        .unknown => 0,
    };
}

// ============================================================================
// ТЕСТЫ: тот же код, что уезжает в WASM, проверяется НАТИВНО (`zig test`).
// Смысл: приёмка `make wasm-check` проверяет и байты модуля (магия/размер/
// экспорты), и СЕМАНТИКУ экспортов — иначе гейт был бы вакуумным.
// ============================================================================

const t = std.testing;

test "wasm: JOIN_K(T, N) = T, JOIN_K(T, F) = B, B поглощает T" {
    const T: u8 = packBit(.{ .p = true, .n = false });
    const F: u8 = packBit(.{ .p = false, .n = true });
    const N: u8 = packBit(.{ .p = false, .n = false });
    try t.expectEqual(T, kern_wasm_belnap_join(T, N));
    const B = kern_wasm_belnap_join(T, F);
    try t.expectEqual(@as(u8, 3), B);
    try t.expectEqual(B, kern_wasm_belnap_join(B, T));
}

test "wasm: допуск e=1 только для T" {
    try t.expectEqual(@as(u8, 1), kern_wasm_belnap_allow(1));
    try t.expectEqual(@as(u8, 0), kern_wasm_belnap_allow(0));
    try t.expectEqual(@as(u8, 0), kern_wasm_belnap_allow(2));
    try t.expectEqual(@as(u8, 0), kern_wasm_belnap_allow(3));
}

test "wasm: Хэмминг-допуск распознаёт код и отвергает искажённый" {
    try t.expectEqual(@as(u8, 1), kern_wasm_admission_valid(truth.AdmissionCode.encode(1)));
    try t.expectEqual(@as(u8, 0), kern_wasm_admission_valid(0));
}

test "wasm: встроенный LIA решает ДВЕ задачи (unsat и sat)" {
    // x <= 5  и  x >= 10  -> несовместно над Z
    try t.expectEqual(@as(u8, 1), kern_wasm_lia_unsat2(1, 0, -5, -1, 0, 10));
    // x <= 5  и  x >= 0   -> совместно (точка x = 0)
    try t.expectEqual(@as(u8, 2), kern_wasm_lia_unsat2(1, 0, -5, -1, 0, 0));
}

/// ПРОВЕРКА ГОТОВОГО ДОКАЗАТЕЛЬСТВА Z3 БЕЗ РЕШАТЕЛЯ (5-й экспорт).
///
/// `verifyProof` работает только со строками в памяти, поэтому целиком
/// помещается в `wasm32-freestanding`. Граница с решателем (`z3_bridge.zig`)
/// локализована в `proof_check.check()`, которая из WASM НЕ достижима.
/// Возврат: 1 — доказательство подтверждено (`checksPass` + вывод `false` +
/// `trusted == 0`); 0 — отвергнуто.
export fn kern_wasm_verify_proof(
    smt_ptr: [*]const u8,
    smt_len: usize,
    proof_ptr: [*]const u8,
    proof_len: usize,
) u8 {
    var arena = std.heap.ArenaAllocator.init(allocator());
    defer arena.deinit();
    const al = arena.allocator();

    const smt = smt_ptr[0..smt_len];
    const proof = proof_ptr[0..proof_len];
    const contract = proof_check.extractAsserts(al, smt) catch return 0;
    const pv = proof_check.verifyProof(al, proof, contract) catch return 0;
    return if (pv.checksPass() and pv.proof_concludes_false and pv.trusted_steps == 0) 1 else 0;
}

test "wasm: verifyProof принимает валидное доказательство и отвергает подделку" {
    const fx = @import("verifier/abs_proof_fixture.zig");
    const smt = fx.ABS_CONTRACT;
    const proof = fx.ABS_PROOF;

    // 1) ВАЛИДНОЕ: 1 (проверено без решателя, trusted: 0).
    try t.expectEqual(@as(u8, 1), kern_wasm_verify_proof(smt.ptr, smt.len, proof.ptr, proof.len));

    // 2) ПОДДЕЛКА: меняем первое вхождение `(>= a 0)` на `(>= a 1)` —
    //    вывод перестаёт сходиться, значит 0 (отвергнуто).
    const bad = try std.testing.allocator.dupe(u8, proof);
    defer std.testing.allocator.free(bad);
    if (std.mem.indexOf(u8, bad, "(>= a 0)")) |i| bad[i + 7] = '1';
    try t.expectEqual(@as(u8, 0), kern_wasm_verify_proof(smt.ptr, smt.len, bad.ptr, bad.len));
}

test "wasm: вывод, НЕ заканчивающийся false, отвергается (убивает [and->or])" {
    // УБИВАЕТ мутант `wasm_api.zig:155 [and->or]`: структурно корректный вывод,
    // у которого корень НЕ `false`, даёт checksPass()==true, но
    // proof_concludes_false==false. Строгий критерий (and) -> 0; мутант (or)
    // вернул бы 1, то есть ПРИНЯЛ бы вывод, ничего не доказывающий.
    const fx = @import("verifier/abs_proof_fixture.zig");
    const smt = fx.ABS_CONTRACT;
    const proof = fx.ABS_PROOF;
    const last = std.mem.lastIndexOf(u8, proof, "false") orelse return error.NoMarker;
    const bad = try std.testing.allocator.alloc(u8, proof.len - 5 + 4);
    defer std.testing.allocator.free(bad);
    @memcpy(bad[0..last], proof[0..last]);
    @memcpy(bad[last..][0..4], "true");
    @memcpy(bad[last + 4 ..], proof[last + 5 ..]);
    try t.expectEqual(@as(u8, 0), kern_wasm_verify_proof(smt.ptr, smt.len, bad.ptr, bad.len));
}
