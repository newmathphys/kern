/* CWE-570/CWE-561 Expression is Always False / Dead Code (Juliet-style `good` twin).
 *
 * Исправление: проверяются НЕЗАВИСИМЫЕ биты, поэтому ветка достижима.
 */
int dead_bits_good(int x) {
    if ((x & 1) == 0) {
        if ((x & 2) != 0) return 1;
    }
    return 0;
}
