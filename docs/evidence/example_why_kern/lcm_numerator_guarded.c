/* НЕГАТИВНЫЙ КОНТРОЛЬ к `lcm_numerator.c` (анти-вакуум).
 * То же тело `a * b`, но с ЧЕСТНЫМ гардом: 46340^2 = 2147395600 < INT_MAX,
 * а `b >= 1` обеспечивает `a * b >= a`. Обязан быть ДОКАЗАН — иначе
 * «REFUTED» на незащищённой версии ничего не доказывал бы.
 */
// @kern:requires a >= 0 and b >= 1 and a <= 46340 and b <= 46340
// @kern:ensures result >= a
int lcm_numerator_guarded(int a, int b) {
    return a * b;
}
