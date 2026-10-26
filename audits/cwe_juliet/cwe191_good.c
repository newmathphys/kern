/* CWE-191 `good` twin: правильный гард `a >= b` делает вычитание безопасным. */
// @kern:requires a > 0 and b > 0 and a >= b
// @kern:ensures result >= 0
unsigned int sub_good(unsigned int a, unsigned int b) {
    return a - b;
}
