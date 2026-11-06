// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
// КОРПУС (шаг 5 плана): ТЕРНАРНИК и то, что тернарником НЕ является.
// `?.` (опциональная цепочка) и `??` (nullish) раньше считались тернарниками и
// роняли перевод функции; вложенный тернарник `a ? b ? c : d : e` разбирался
// неверно и тоже ронял перевод. Ожидание: функция РАЗОБРАНА (не пропущена
// по причине «тернарный оператор»), а настоящий тернарник переведён в `ite`.
export function pick(x: any, a: number, b: number): number {
    const v = x?.value ?? 0;
    const m = a > 0 ? (b > 0 ? b : a) : b;
    if (v > 0) {
        return m + v;
    }
    return 0;
}
