// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
// Тесты для дефектов #471b/#471c и #472 на C-like (Rust) маршруте.
// «Молчащие» функции — ложные обвинения, которые обязаны ИСЧЕЗНУТЬ.
// Функции с пометкой TP — настоящие ошибки, которые обязаны ОСТАТЬСЯ.

fn gcd_while_rust(mut a: u64, mut b: u64) -> u64 {
    // #471b: условие цикла — гард для тела (`while b != 0`).
    while b != 0 {
        let temp = b;
        b = a % b;
        a = temp;
    }
    a
}

fn gcd_else_rust(a: i64, b: i64) -> i64 {
    // #471c: ветвь `else` выполняется только при `a != 0`.
    if a == 0 {
        b.abs()
    } else {
        gcd_else_rust(b % a, a)
    }
}

fn ratio_f64(debt: f64, equity: f64) -> f64 {
    // #472: деление 0.0 в IEEE-754 даёт inf/NaN, паники НЕТ -> QF_FP не моделируем.
    debt / equity
}

fn ratio_i64(debt: i64, equity: i64) -> i64 {
    // TP-КОНТРОЛЬ к #472: целочисленное деление на ноль — паника, обвинение остаётся.
    debt / equity
}
