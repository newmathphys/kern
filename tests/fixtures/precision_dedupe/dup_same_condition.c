// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
// КОНТРОЛЬ УЧЁТА (#502), взят из слепого замера (tigerbeetle/samples/main.c:
// две РАЗНЫЕ проверки с ОДНИМ И ТЕМ ЖЕ условием). У `[DEAD BRANCH]` нет номера
// строки, поэтому такие находки текстово идентичны и раньше считались ДВАЖДЫ.
// Ожидание: РОВНО 1 находка — одно обвинение, один счётчик.
struct rec { int kind; };
int dup_same_condition(struct rec *r) {
    if (r->kind == 1) { return 10; }
    if (r->kind == 2) { return 20; }
    if (r->kind == 1) { return 30; }
    if (r->kind == 1) { return 40; }
    return 0;
}
