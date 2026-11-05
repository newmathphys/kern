// DeepJIT — include/deep_jit/utils/json.hpp, `dump_string` (строки 84-85):
//     output.push_back(hex[c >> 4]);
//     output.push_back(hex[c & 0x0f]);
// где `hex` — таблица из 16 символов, а `c` — `unsigned char` (0..255, цикл
// `for (const unsigned char c : value)`).
//
// ПОЧЕМУ ЭТО НАДО ДОКАЗЫВАТЬ. `hex[...]` — индексация по индексу БЕЗ явной
// проверки границ; безопасность держится на ТИПЕ `c` (0..255) и на том, что
// `c >> 4` и `c & 0x0f` дают 0..15. Если тип `c` когда-нибудь сменят на
// `char`/`int` без сужения, `c >> 4` (арифметический сдвиг знакового) уйдёт
// в отрицательные индексы — и это молчаливое чтение ДО таблицы `hex`.
// Контракт делает неявную гарантию ЯВНОЙ и проверяемой.

// @kern:bitvec32
// @kern:requires c >= 0 and c <= 255
// @kern:ensures result >= 0 and result <= 15
int deepjit_hex_hi(int c) { return c >> 4; }

// @kern:bitvec32
// @kern:requires c >= 0 and c <= 255
// @kern:ensures result >= 0 and result <= 15
int deepjit_hex_lo(int c) { return c & 0x0f; }
