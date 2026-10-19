// ОГРАНИЧЕНИЕ экстрактора: «хвостовое выражение» Rust (`a.saturating_add(b)`
// без return) вне подмножества — требуется явный `return`.
/// @kern:ensures result >= 0
pub fn add_sat(a: u32, b: u32) -> u32 {
    return a.saturating_add(b);
}
