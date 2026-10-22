// ТЕНЕВОЙ КОНТРАКТ: выражение `n - i` ВЕРБАТИМ из upstream binom().
// Условие цикла: i in 0..k, то есть i < k. Никакого `k <= n` в коде НЕТ.
// @kern:requires i < k
// @kern:ensures result >= 0
fn binom_step(n: u64, k: u64, i: u64) -> u64 {
    return n - i;
}
