// EXTRACTED from saber-hq/stable-swap, stable-swap-math/src/curve.rs
//   StableSwap::compute_amp_factor (ramp-up branch), math core only.
// Original uses checked_sub/checked_mul/checked_div (safe arithmetic).
// Here the SAME math is written as plain i64 so KERN can reason about the
// invariant the checked version relies on.

/// @kern:requires initial_amp >= 0 and target_amp >= initial_amp
/// @kern:requires time_range > 0 and time_delta >= 0 and time_delta <= time_range
/// @kern:ensures result >= initial_amp and result <= target_amp
pub fn amp_ramp_up_safe(initial_amp: i64, target_amp: i64, time_delta: i64, time_range: i64) -> i64 {
    return initial_amp + (target_amp - initial_amp) * time_delta / time_range;
}

/// @kern:requires initial_amp >= 0 and target_amp >= initial_amp
/// @kern:requires time_range > 0 and time_delta >= 0
/// @kern:ensures result <= target_amp
pub fn amp_ramp_up_unchecked(initial_amp: i64, target_amp: i64, time_delta: i64, time_range: i64) -> i64 {
    return initial_amp + (target_amp - initial_amp) * time_delta / time_range;
}
