// @kern:requires a >= 0 and b >= 0
// @kern:ensures result >= a
pub fn add32(a: i32, b: i32) -> i32 {
    a.saturating_add(b)
}
