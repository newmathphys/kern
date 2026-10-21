const std = @import("std");
pub fn ratio(a: i64, b: i64) i64 {
    return a / b;
}
pub fn main() void {
    const r = ratio(1, 0);
    std.debug.print("NO VIOLATION {d}\n", .{r});
}
