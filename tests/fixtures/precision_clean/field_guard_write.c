/* Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md */
/* ЛОВУШКА ЛОЖНОГО ОБВИНЕНИЯ (#500), минимизирована со слепого замера на redis/ae.c.
   Поле ПЕРЕПИСЫВАЕТСЯ между гардом и второй проверкой — предикат на СТАРОЕ
   значение прикладывать нельзя, иначе ветвь объявляется мёртвой ЛОЖНО.
   Ожидание: 0 находок. */
struct fe { int mask; };
int guard_after_write(struct fe *e, int bit) {
    if (e->mask == 0) return 0;
    e->mask = e->mask & (~bit);
    if (e->mask == 0) return 1;
    return 2;
}
