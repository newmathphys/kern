// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
// ГЕРМЕТИЧНЫЙ КОНТРОЛЬ ПОЛНОТЫ (#475) для C-like: здесь НАСТОЯЩИЕ ошибки.
// Пропуск = потеря сигнала (FN). Гейт требует, чтобы КАЖДОЕ имя ниже нашлось.

fn div_unguarded_rs(a: i64, b: i64) -> i64 {
    a / b
}

fn mod_unguarded_rs(a: i64, b: i64) -> i64 {
    a % b
}
