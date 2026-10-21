const std = @import("std");
pub fn ratio(a: i64, b: i64) i64 {
    return a / b;
}
pub fn main() !void {
    var args = std.process.args();
    _ = args.next();
    const b = try std.fmt.parseInt(i64, args.next() orelse "0", 10);
    std.debug.print("NO VIOLATION {d}\n", .{ratio(1, b)});
}
