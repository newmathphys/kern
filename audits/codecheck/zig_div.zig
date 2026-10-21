// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// CORPUS: UNGUARDED division (real defect). KERN must REFUTE it (F) with a
// division-by-zero counterexample.
//
// ДЕФЕКТ #308: раньше здесь стояли i64, и `a / b` для ЗНАКОВЫХ целых Zig 0.17
// отвергает НА КОМПИЛЯЦИИ («signed integers must use @divTrunc, ...»). Тогда
// наземная проверка контрпримера живым компилятором была невозможна. Для u64
// `/` допустим, и `B=0` даёт РЕАЛЬНУЮ панику `division by zero` (SIGABRT).
// @kern:requires a >= 0 and a <= 1000
// @kern:ensures result == a / b
pub fn ratio(a: u64, b: u64) u64 {
    return a / b;
}
