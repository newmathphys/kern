// ГЕРМЕТИЧНЫЙ НЕГАТИВНЫЙ КОНТРОЛЬ (#475) для C-like маршрута: ВСЁ ЗАЩИЩЕНО.
// Гейт `make xray-precision` требует `находок 0`. Любая находка — регресс
// ложного обвинения (#471b/#471c/#472).

fn div_if_return_rs(a: i64, b: i64) -> i64 {
    if b == 0 {
        return 0;
    }
    a / b
}

fn div_else_rs(a: i64, b: i64) -> i64 {
    // #471c: `else` обязан получать `(not cond)`, а НЕ прямой `cond`.
    if b == 0 {
        0
    } else {
        a / b
    }
}

fn gcd_while_rs(mut a: u64, mut b: u64) -> u64 {
    // #471b: условие `while` — гард для тела (Евклид).
    while b != 0 {
        let temp = b;
        b = a % b;
        a = temp;
    }
    a
}

fn ratio_f64_rs(debt: f64, equity: f64) -> f64 {
    // #472: f64/f64 в IEEE-754 даёт inf/NaN, паники НЕТ -> названный пропуск.
    debt / equity
}
