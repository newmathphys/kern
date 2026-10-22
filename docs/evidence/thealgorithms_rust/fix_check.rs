fn binom_u64(n: u64, k: u64) -> u64 {
    if k > n { return 0; }          // <- ПРАВКА
    let mut res = 1u64;
    for i in 0..k { res = (res * (n - i)) / (i + 1); }
    res
}

fn main() {
    // случаи из тестов upstream (регрессия)
    for (n, k, want) in [(5u64,2u64,10u64),(10,5,252),(0,0,1),(1000,2,499500),(7,4,35),(12,3,220),(20,10,184756)] {
        let got = binom_u64(n, k);
        println!("binom({},{}) = {}  ожидалось {}  {}", n, k, got, want, if got==want {"OK"} else {"РЕГРЕССИЯ"});
    }
    // случаи k > n (падали до правки)
    for (n, k) in [(0u64,2u64),(5,7),(1,3)] {
        println!("binom({},{}) = {}  (было: panic/мусор)", n, k, binom_u64(n, k));
    }
}
