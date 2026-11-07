// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
/* КОНТРОЛЬ В ОБРАТНУЮ СТОРОНУ (#500): поле НЕ переписывается, поэтому третья
   проверка `kind == 1` после двух ранних выходов — НАСТОЯЩАЯ мёртвая ветвь.
   Ожидание: ровно 1 находка [DEAD BRANCH]. Если правка #500 «убила» и такие
   ветви — recall упал, и гейт обязан покраснеть. */
struct rec { int kind; };
int dead_after_kind(struct rec *r) {
    if (r->kind == 1) { return 10; }
    if (r->kind == 2) { return 20; }
    if (r->kind == 1) { return 30; }
    return 0;
}
