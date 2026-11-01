/* CWE-193 Off-by-One Error (Juliet-style `bad` twin).
 *
 * Настоящий дефект: `i <= len` разрешает `i == len`, а `buf[len]` уже за концом
 * (валидные индексы 0..len-1). Так была устроена историческая уязвимость
 * `198669d` в cmark-gfm (`numdelims <= max_delims`).
 */
int fill_bad(int *buf, int len, int i) {
    if (i <= len) { buf[i] = 1; }
    return 0;
}
