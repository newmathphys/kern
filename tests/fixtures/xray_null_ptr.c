// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// КОРПУС (шаг 6 плана): УКАЗАТЕЛЬ = Int, ГДЕ 0 = NULL. ДВУСТОРОННИЙ контроль.
//
// ПОЗИТИВНЫЙ: противоречие БЕЗ мутации — вторая проверка МЁРТВАЯ, её обязаны найти.
int null_twice(int *p) {
    if (p == NULL) { return 0; }
    if (p == NULL) { return 1; }
    return 2;
}

// НЕГАТИВНЫЙ: МУТАЦИЯ указателя между проверками — вторая проверка НЕ мёртвая.
// Находки быть НЕ должно: накопленный `p != 0` относится к СТАРОМУ значению.
// Именно на таком обходе узлов (`node = node->next`) ломается наивная модель.
int null_after_mutation(int *p, int *next_p) {
    if (p == NULL) { return 0; }
    p = next_p;
    if (p == NULL) { return 1; }
    return 2;
}

// ФОРМА `!p` (ловушка сортов Z3): обязана переводиться в `p == 0`, а не в `not p`.
int bang_twice(int *p) {
    if (!p) { return 0; }
    if (!p) { return 1; }
    return 2;
}
