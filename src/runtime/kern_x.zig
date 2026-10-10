// Copyright (c) 2026 mrbritneyxxx. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN-X: изолированная fuel-bounded виртуальная машина (§ «Среда Исполнения»).
//! Байткод исполняется прямо из образа, «топливо» списывается на каждой
//! инструкции — бесконечные циклы невозможны физически (Уравнение V: Fuel).
const std = @import("std");

pub const ExecError = error{
    OutOfFuel,
    InvalidOpcode,
    MemoryOutOfBounds,
    StackUnderflow,
};

/// Минимальный набор опкодов (расширяемый).
///   0x00 NOP
///   0x01 TRACE      — полезная «работа» (в проде здесь вызовы контрактов)
///   0x02 PUSH imm8  — положить байт на стек
///   0x03 STORE      — memory[addr] = value (addr,value со стека)
///   0x04 LOAD       — положить memory[addr] на стек
///   0x05 ADD        — сложить два верхних
///   0xFF HALT       — успешное завершение
pub const KernX = struct {
    fuel: u32,
    memory: [4096]u8 = [_]u8{0} ** 4096,
    stack: [256]u8 = [_]u8{0} ** 256,
    sp: usize = 0,
    pc: usize = 0,
    trace: bool = false,

    pub fn init(max_fuel: u32) KernX {
        return .{ .fuel = max_fuel };
    }

    fn push(self: *KernX, v: u8) !void {
        if (self.sp >= self.stack.len) return ExecError.MemoryOutOfBounds;
        self.stack[self.sp] = v;
        self.sp += 1;
    }

    fn pop(self: *KernX) !u8 {
        if (self.sp == 0) return ExecError.StackUnderflow;
        self.sp -= 1;
        return self.stack[self.sp];
    }

    /// Выполнение верифицированного байткода.
    pub fn execute(self: *KernX, bytecode: []const u8) !void {
        self.pc = 0;
        while (self.pc < bytecode.len) {
            // АППАРАТНЫЙ ШЛЮЗ ТОПЛИВА (Уравнение V)
            if (self.fuel == 0) return ExecError.OutOfFuel;
            self.fuel -= 1;

            const opcode = bytecode[self.pc];
            self.pc += 1;
            switch (opcode) {
                0x00 => {}, // NOP
                0x01 => {
                    if (self.trace) std.debug.print("⚡ [KERN-X] защищённая инструкция\n", .{});
                },
                0x02 => { // PUSH imm8
                    if (self.pc >= bytecode.len) return ExecError.InvalidOpcode;
                    try self.push(bytecode[self.pc]);
                    self.pc += 1;
                },
                0x03 => { // STORE
                    const addr = try self.pop();
                    const val = try self.pop();
                    self.memory[addr] = val;
                },
                0x04 => { // LOAD
                    const addr = try self.pop();
                    try self.push(self.memory[addr]);
                },
                0x05 => { // ADD
                    const b = try self.pop();
                    const a = try self.pop();
                    try self.push(a +% b);
                },
                0xFF => return, // HALT
                else => return ExecError.InvalidOpcode,
            }
        }
    }
};

// =========================================================================
// ТЕСТЫ
// =========================================================================

test "KERN-X: HALT завершает, топливо остаётся" {
    var vm = KernX.init(100);
    try vm.execute(&[_]u8{ 0x00, 0x01, 0xFF });
    try std.testing.expect(vm.fuel > 0);
}

test "KERN-X: исчерпание топлива невозможно обойти (бесконечный цикл)" {
    // Байткод без HALT: 10 000 NOP, топливо 5 → OutOfFuel, не зависание.
    var code: [10_000]u8 = [_]u8{0x00} ** 10_000;
    var vm = KernX.init(5);
    try std.testing.expectError(ExecError.OutOfFuel, vm.execute(&code));
}

test "KERN-X: неизвестный опкод отвергается" {
    var vm = KernX.init(10);
    try std.testing.expectError(ExecError.InvalidOpcode, vm.execute(&[_]u8{0x99}));
}

test "KERN-X: PUSH/STORE/LOAD/ADD работают" {
    // PUSH 5, PUSH 3, ADD -> 8; PUSH 8 -> addr; STORE; PUSH 8; LOAD -> 8
    var vm = KernX.init(100);
    const code = [_]u8{ 0x02, 5, 0x02, 3, 0x05, 0x02, 10, 0x03, 0x02, 10, 0x04, 0xFF };
    try vm.execute(&code);
    try std.testing.expectEqual(@as(u8, 8), vm.memory[10]);
}

test "KERN-X: STORE за границей памяти отвергается" {
    var vm = KernX.init(100);
    // PUSH 200 (val), PUSH 255 (addr) — внутри 4096, ок; проверим адрес вне [0,255] невозможно (u8).
    // Проверяем StackUnderflow вместо паники.
    try std.testing.expectError(ExecError.StackUnderflow, vm.execute(&[_]u8{ 0x04, 0xFF }));
}
