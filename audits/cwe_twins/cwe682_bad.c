/* CWE-682 Incorrect Calculation / hardware `idiv` trap (дефект #334).
 *
 * Настоящий дефект: гард `b != 0` ЕСТЬ, но этого НЕДОСТАТОЧНО. По стандарту C
 * `INT_MIN / -1` и `INT_MIN % -1` — аппаратная ловушка (SIGFPE): частное
 * 2147483648 не представимо в int. Обязанность ловит именно этот случай. */
// @kern:requires b != 0
// @kern:ensures result == a % b
int rem_bad(int a, int b) {
    return a % b;
}
