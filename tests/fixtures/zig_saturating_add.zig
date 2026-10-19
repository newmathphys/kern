/// @kern:ensures result >= 0
pub fn addSat(a: u32, b: u32) u32 {
    return a +| b;
}
