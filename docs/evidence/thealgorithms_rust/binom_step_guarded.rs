// НЕГАТИВНЫЙ КОНТРОЛЬ к `binom_step.rs` (анти-вакуум).
// То же тело `n - i`, но с ЧЕСТНЫМ гардом `i <= n`: вычитание в u64 безопасно.
// Обязан быть ДОКАЗАН.
// @kern:requires i <= n
// @kern:ensures result >= 0
fn binom_step_guarded(n: u64, i: u64) -> u64 {
    return n - i;
}
