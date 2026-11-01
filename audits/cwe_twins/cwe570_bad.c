/* CWE-570/CWE-561 Expression is Always False / Dead Code (Juliet-style `bad` twin).
 *
 * Настоящий дефект: если младшие два бита нулевые, то `(x & 3) != 0`
 * НЕДОСТИЖИМО. Требует БИТОВОГО рассуждения (BV32), целочисленной моделью
 * не берётся — это и есть мускул, построенный в Шаге 4b.
 */
int dead_bits_bad(int x) {
    if ((x & 1) == 0) {
        if ((x & 2) == 0) {
            if ((x & 3) != 0) return 1;
        }
    }
    return 0;
}
