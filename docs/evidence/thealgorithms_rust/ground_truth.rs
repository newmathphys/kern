fn binom_step(n: u64, i: u64) -> u64 {
    n - i   // вербатим из upstream binom()
}

fn main() {
    // КОНТРПРИМЕР KERN: n = 0, i = 1  (достижим вызовом binom(0, 2))
    let n = 0u64; let i = 1u64;
    println!("binom(0, 2): на шаге i={} получаем n-i = {}", i, binom_step(n, i));
}
