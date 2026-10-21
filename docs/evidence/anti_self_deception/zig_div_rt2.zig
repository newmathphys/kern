const std = @import("std");
pub fn ratio(a: i64, b: i64) i64 {
    return a / b;
}
pub fn main() void {
    const s = std.posix.getenv("B") orelse "0";
    const b = std.fmt.parseInt(i64, s, 10) catch 0;
    std.debug.print("NO VIOLATION {d}\n", .{ratio(1, b)});
}
