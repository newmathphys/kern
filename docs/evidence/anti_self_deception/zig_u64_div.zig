const std = @import("std");
const compat = @import("compat");
pub fn ratio(a: u64, b: u64) u64 {
    return a / b;
}
pub fn main() void {
    const s = compat.envVar("B") orelse "0";
    const b = std.fmt.parseInt(u64, s, 10) catch 0;
    std.debug.print("NO VIOLATION {d}\n", .{ratio(1, b)});
}
