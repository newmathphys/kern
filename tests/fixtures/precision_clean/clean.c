/* ГЕРМЕТИЧНЫЙ НЕГАТИВНЫЙ КОНТРОЛЬ (#475): здесь всё ЗАЩИЩЕНО — находок быть не должно.
 * Гейт `make xray-precision` требует `находок 0`; любая находка = регресс. */

int div_if_return_c(int a, int b) {
    if (b == 0) {
        return 0;
    }
    return a / b;
}

int div_else_c(int a, int b) {
    if (b == 0) {
        return 0;
    } else {
        return a / b;
    }
}

int div_while_c(int a, int b) {
    while (b != 0) {
        return a / b;
    }
    return 0;
}
