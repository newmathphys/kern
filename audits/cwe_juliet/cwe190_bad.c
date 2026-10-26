/* CWE-190 Integer Overflow (NIST Juliet-style `bad` twin).
 * Настоящий дефект: `a * b` при `a, b > 0` переполняет знаковый int и даёт
 * ОТРИЦАТЕЛЬНЫЙ результат, поэтому постусловие `result > 0` нарушается.
 * Гард в `good`-близнеце: `a, b <= 46340` (46340^2 < INT_MAX). */
// @kern:requires a > 0 and b > 0
// @kern:ensures result > 0
int mul_bad(int a, int b) {
    return a * b;
}
