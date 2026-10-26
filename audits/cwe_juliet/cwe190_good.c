/* CWE-190 `good` twin: тот же код, но с правильным гардом.
 * 46340 * 46340 = 2147395600 < 2147483647 = INT_MAX, переполнение НЕВОЗМОЖНО. */
// @kern:requires a > 0 and b > 0 and a <= 46340 and b <= 46340
// @kern:ensures result > 0
int mul_good(int a, int b) {
    return a * b;
}
