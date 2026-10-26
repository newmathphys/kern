/* CWE-682 `good` twin: гард закрывает ОБА случая — ноль И пару (MIN, -1). */
// @kern:requires b != 0 and not (a == -2147483648 and b == -1)
// @kern:ensures result == a % b
int rem_good(int a, int b) {
    return a % b;
}
