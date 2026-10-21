/* SOURCE: TheAlgorithms/C @ e5dad3fa8def3726ec850ca66a7f51521f8ad393, math/catalan.c
 *
 * VERBATIM from the repository:
 *     long int factorial(int x) {
 *         int i; long int fac; fac = x;
 *         for (i = 1; i < x; i++) fac = fac * (x - i);
 *         return fac;
 *     }
 *     f1 = factorial(2 * n); f2 = factorial(n + 1); f3 = factorial(n);
 *     C = f1 / (f2 * f3);      <-- INTEGER division (all operands are long int)
 *
 * For x == 0 the loop body never runs and `fac = x` leaves 0, so
 * factorial(0) == 0 (mathematically it must be 1).
 *
 * The loop is UNROLLED below to the two cases that decide the obligation
 * (n = 0 and n = 1): the extractor does not model loops. The unrolled form is
 * EXACT for those inputs, because every factorial factor there is 0 or 1.
 */

// @kern:requires n >= 0 and n <= 1
// @kern:ensures result > 0
int catalan_divisor(int n)
{
    if (n == 0) return 0;   /* factorial(1) * factorial(0) = 1 * 0 */
    return 2;               /* factorial(2) * factorial(1) = 2 * 1 */
}
