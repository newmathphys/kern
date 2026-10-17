/* Демонстрация контрактов KERN для языка C (мультиязычный экстрактор).
 *
 * Аннотации — обычные `// @kern:requires` / `// @kern:ensures`.
 * Тип `int` даёт 32-битные границы: KERN проверит переполнение.
 */

// @kern:requires amount >= 0 and balance >= amount
// @kern:ensures  result == balance - amount
int withdraw(int balance, int amount) {
    return balance - amount;
}

// @kern:requires balance >= 0 and amount >= 0
// @kern:ensures  result >= 0 and result <= balance
int withdraw_guard(int balance, int amount) {
    if (amount > balance) return 0;
    return balance - amount;
}

// @kern:requires balance >= 0
// @kern:ensures  result >= 0
int share(int balance, int amount) {
    return balance / amount;   /* amount может быть 0 -> деление на ноль! */
}
