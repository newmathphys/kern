/* CWE-193 Off-by-One Error (Juliet-style `good` twin).
 *
 * Исправление: строгое `<`, поэтому индекс не дотягивает до длины.
 */
int fill_good(int *buf, int len, int i) {
    if (i < len) { buf[i] = 1; }
    return 0;
}
