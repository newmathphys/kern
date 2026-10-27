/// @kern:requires a >= 0 and a <= 100 and b >= 0 and b <= 100
/// @kern:ensures result >= 0
pub fn addGuarded(a: i32, b: i32) i32 {
    return a + b;
}

/// @kern:requires b > 0
/// @kern:ensures result == a / b
pub fn divOk(a: i32, b: i32) i32 {
    return @divTrunc(a, b);
}

/// @kern:requires 1 == 1
pub fn satOk(a: u32, b: u32) u32 {
    return a +| b;
}
