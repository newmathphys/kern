const std = @import("std");

// ЭТАЛОН: встроенные операции Zig — семантика уровня компилятора.
// Именно это обязаны моделировать наши SMT-адаптеры (дефект #317).
pub fn main() void {
    std.debug.print("a b trunc floor ceil\n", .{});
    var a: i32 = -20;
    while (a <= 20) : (a += 1) {
        var b: i32 = -20;
        while (b <= 20) : (b += 1) {
            if (b == 0) continue;
            std.debug.print("{d} {d} {d} {d} {d}\n", .{
                a, b, @divTrunc(a, b), @divFloor(a, b), @divCeil(a, b),
            });
        }
    }
}
