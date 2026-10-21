const std = @import("std");
pub fn add32(a: i32, b: i32) i32 {
    return a + b;
}
pub fn main() void {
    std.debug.print("NO VIOLATION {d}\n", .{add32(2147483647, 1)});
}
