// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
// ЛОВУШКА ЛОЖНОГО ОБВИНЕНИЯ (#503), минимизирована со слепого замера
// (curl/lib/curl_fnmatch.c::setcharset): `switch` НЕ моделируется, поэтому
// ОДНО И ТО ЖЕ условие в РАЗНЫХ `case` считалось последовательным кодом и
// третья ветвь объявлялась мёртвой. Ожидание: 0 находок.
int switch_repeated(int state, int c) {
    switch (state) {
    case 0:
        if (c == 93) { return 1; }
        break;
    case 1:
        if (c == 93) { return 2; }
        break;
    }
    return 0;
}
