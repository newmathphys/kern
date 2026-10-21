// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN-X: изолированная fuel-bounded виртуальная машина (§ «Среда Исполнения»).
//!
//! Топливо списывается на каждой инструкции, поэтому бесконечный цикл
//! невозможен физически. Квоты (Ф3) расширяют то же правило на остальные
//! ресурсы: память (arena), вывод (output), глубину вызовов (depth) и
//! обращения к хосту (host_calls).
//!
//! ПОЧЕМУ ТОПЛИВО — УКАЗАТЕЛЬ. «Копия на ветку» обнуляла бы гарантию:
//! рекурсивный байткод с двумя ветвями получал бы N топлива НА КАЖДУЮ ветку,
//! то есть экспоненциальный бюджет. Здесь бюджет передаётся по ссылке, и все
//! ветки (и даже разные машины) тратят ОДИН счётчик.

const std = @import("std");

pub const ExecError = error{
    OutOfFuel,
    /// Исчерпана квота ресурса (arena / output / depth / host_calls).
    OutOfQuota,
    InvalidOpcode,
    MemoryOutOfBounds,
    StackUnderflow,
    /// `RET` без соответствующего `CALL`.
    CallStackOverflow,
};

/// Общий бюджет на все ветки исполнения. Все поля — указатели на ОДИН счётчик.
pub const Budget = struct {
    fuel: *u32,
    arena: *usize,
    arena_max: usize,
    output: *usize,
    output_max: usize,
    depth: *u32,
    depth_max: u32,
    host_calls: *u32,
    host_calls_max: u32,
};

/// Опкоды:
///   0x00 NOP · 0x01 TRACE · 0x02 PUSH imm8 · 0x03 STORE · 0x04 LOAD
///   0x05 ADD · 0x06 CALL addr8 · 0x07 RET · 0xFF HALT
pub const KernX = struct {
    budget: Budget,
    memory: [4096]u8 = @as([4096]u8, @splat(0)),
    stack: [256]u8 = @as([256]u8, @splat(0)),
    sp: usize = 0,
    pc: usize = 0,
    trace: bool = false,
    /// Стек возврата: `CALL` кладёт адрес, `RET` снимает.
    ret: [64]usize = @as([64]usize, @splat(0)),
    rsp: usize = 0,

    pub fn initWithBudget(b: Budget) KernX {
        return .{ .budget = b };
    }

    fn chargeFuel(self: *KernX) !void {
        if (self.budget.fuel.* == 0) return ExecError.OutOfFuel;
        self.budget.fuel.* -= 1;
    }

    pub fn chargeArena(self: *KernX, n: usize) !void {
        if (self.budget.arena.* + n > self.budget.arena_max) return ExecError.OutOfQuota;
        self.budget.arena.* += n;
    }

    pub fn emit(self: *KernX, n: usize) !void {
        if (self.budget.output.* + n > self.budget.output_max) return ExecError.OutOfQuota;
        self.budget.output.* += n;
    }

    pub fn hostCall(self: *KernX) !void {
        if (self.budget.host_calls.* >= self.budget.host_calls_max) return ExecError.OutOfQuota;
        self.budget.host_calls.* += 1;
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

    pub fn execute(self: *KernX, bytecode: []const u8) !void {
        self.pc = 0;
        self.rsp = 0;
        self.budget.depth.* = 0;
        while (self.pc < bytecode.len) {
            // АППАРАТНЫЙ ШЛЮЗ ТОПЛИВА — ОДИН счётчик на всё.
            try self.chargeFuel();

            const opcode = bytecode[self.pc];
            self.pc += 1;
            switch (opcode) {
                0x00 => {},
                0x01 => {
                    if (self.trace) std.debug.print("⚡ [KERN-X] защищённая инструкция\n", .{});
                },
                0x02 => {
                    if (self.pc >= bytecode.len) return ExecError.InvalidOpcode;
                    try self.push(bytecode[self.pc]);
                    self.pc += 1;
                },
                0x03 => {
                    const addr = try self.pop();
                    const val = try self.pop();
                    self.memory[addr] = val;
                },
                0x04 => {
                    const addr = try self.pop();
                    try self.push(self.memory[addr]);
                },
                0x05 => {
                    const b = try self.pop();
                    const a = try self.pop();
                    try self.push(a +% b);
                },
                0x06 => {
                    if (self.pc >= bytecode.len) return ExecError.InvalidOpcode;
                    const target = bytecode[self.pc];
                    self.pc += 1;
                    if (self.budget.depth.* >= self.budget.depth_max) return ExecError.OutOfQuota;
                    if (self.rsp >= self.ret.len) return ExecError.CallStackOverflow;
                    self.ret[self.rsp] = self.pc;
                    self.rsp += 1;
                    self.budget.depth.* += 1;
                    self.pc = target;
                },
                0x07 => {
                    if (self.rsp == 0) return ExecError.CallStackOverflow;
                    self.rsp -= 1;
                    self.pc = self.ret[self.rsp];
                    if (self.budget.depth.* > 0) self.budget.depth.* -= 1;
                },
                0xFF => return,
                else => return ExecError.InvalidOpcode,
            }
        }
    }
};

// =========================================================================
// ТЕСТЫ
// =========================================================================

/// Тестовый бюджет: все счётчики — локальные переменные теста.
const TB = struct {
    fuel: u32 = 100,
    arena: usize = 0,
    output: usize = 0,
    depth: u32 = 0,
    calls: u32 = 0,
    depth_max: u32 = 8,

    fn budget(self: *TB) Budget {
        return .{ .fuel = &self.fuel, .arena = &self.arena, .arena_max = 1024,
                  .output = &self.output, .output_max = 1024,
                  .depth = &self.depth, .depth_max = self.depth_max,
                  .host_calls = &self.calls, .host_calls_max = 4 };
    }
};

test "KERN-X: HALT завершает, топливо остаётся" {
    var tb = TB{};
    var vm = KernX.initWithBudget(tb.budget());
    try vm.execute(&[_]u8{ 0x00, 0x01, 0xFF });
    try std.testing.expect(tb.fuel > 0);
}

test "KERN-X: исчерпание топлива невозможно обойти (бесконечный цикл)" {
    var code: [10_000]u8 = @as([10_000]u8, @splat(0x00));
    var tb = TB{ .fuel = 5 };
    var vm = KernX.initWithBudget(tb.budget());
    try std.testing.expectError(ExecError.OutOfFuel, vm.execute(&code));
}

test "KERN-X: неизвестный опкод отвергается" {
    var tb = TB{ .fuel = 10 };
    var vm = KernX.initWithBudget(tb.budget());
    try std.testing.expectError(ExecError.InvalidOpcode, vm.execute(&[_]u8{0x99}));
}

test "KERN-X: PUSH/STORE/LOAD/ADD работают" {
    var tb = TB{};
    var vm = KernX.initWithBudget(tb.budget());
    const code = [_]u8{ 0x02, 5, 0x02, 3, 0x05, 0x02, 10, 0x03, 0x02, 10, 0x04, 0xFF };
    try vm.execute(&code);
    try std.testing.expectEqual(@as(u8, 8), vm.memory[10]);
}

test "KERN-X: LOAD без адреса -> StackUnderflow" {
    var tb = TB{};
    var vm = KernX.initWithBudget(tb.budget());
    try std.testing.expectError(ExecError.StackUnderflow, vm.execute(&[_]u8{ 0x04, 0xFF }));
}

test "Ф3: fuel ОДИН на все ветки (две машины, один счётчик)" {
    var tb = TB{ .fuel = 10 };
    var vm1 = KernX.initWithBudget(tb.budget());
    var vm2 = KernX.initWithBudget(tb.budget());
    // 9 NOP + HALT = ровно 10 списаний -> топливо 0.
    try vm1.execute(&[_]u8{ 0, 0, 0, 0, 0, 0, 0, 0, 0, 0xFF });
    try std.testing.expectEqual(@as(u32, 0), tb.fuel);
    // Вторая «ветка» не получает свежую копию: топлива уже нет.
    try std.testing.expectError(ExecError.OutOfFuel, vm2.execute(&[_]u8{0x00}));
}

test "Ф3: рекурсия упирается в квоту глубины, а не в стек хоста" {
    var tb = TB{ .fuel = 10_000, .depth_max = 8 };
    var vm = KernX.initWithBudget(tb.budget());
    // CALL 0 -> бесконечная рекурсия; глубина 8 исчерпывается раньше топлива.
    try std.testing.expectError(ExecError.OutOfQuota, vm.execute(&[_]u8{ 0x06, 0x00 }));
}

test "Ф3: рекурсия тратит ОДИН fuel (без копии на ветку)" {
    var tb = TB{ .fuel = 50, .depth_max = 1000 };
    var vm = KernX.initWithBudget(tb.budget());
    try std.testing.expectError(ExecError.OutOfFuel, vm.execute(&[_]u8{ 0x06, 0x00 }));
    try std.testing.expectEqual(@as(u32, 0), tb.fuel);
}

test "Ф3: квоты arena / output / host_calls" {
    var tb = TB{};
    var vm = KernX.initWithBudget(tb.budget());
    try vm.chargeArena(1000);
    try std.testing.expectError(ExecError.OutOfQuota, vm.chargeArena(100));
    try vm.emit(1024);
    try std.testing.expectError(ExecError.OutOfQuota, vm.emit(1));
    var i: u32 = 0;
    while (i < 4) : (i += 1) try vm.hostCall();
    try std.testing.expectError(ExecError.OutOfQuota, vm.hostCall());
}
