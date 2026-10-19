// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN: ВСТРОЕННЫЙ РЕШАТЕЛЬ ЛИНЕЙНОЙ ЦЕЛОЧИСЛЕННОЙ АРИФМЕТИКИ (QF_LIA).
//!
//! ЗАЧЕМ (пункт 1 плана v2.5). Без установленного `z3` Врата закрыты для ЛЮБОГО
//! входа (`e = 0`) — даже для тривиального линейного контракта. Этот модуль
//! закрывает простой линейный фрагмент САМ, без внешнего процесса.
//!
//! ВТОРАЯ, БОЛЕЕ ВАЖНАЯ РОЛЬ (пункт 3, дефект #123). Z3 выдаёт арифметические
//! леммы БЕЗ весов Фаркаша: `((_ th-lemma arith) @x224 @x141 @x90 $x159)`.
//! Проверить такую лемму звучимо можно ТОЛЬКО своим решателем: отрицания
//! посылок и заключения образуют систему, несовместность которой и есть
//! доказательство. Именно это делает `checkUnsat`.
//!
//! МЕТОД: исключение переменных Фурье — Моцкина.
//!
//! ЗВУЧНОСТЬ (главное). FM решает систему над РАЦИОНАЛЬНЫМИ числами. Целые —
//! подмножество рациональных, поэтому НЕСОВМЕСТНОСТЬ рационального ослабления
//! гарантирует несовместность целочисленной системы: вердикт `.unsat` ЗВУЧИМ
//! ВСЕГДА. Обратное неверно (рационально совместная система может не иметь
//! целого решения), поэтому `.sat` возвращается ТОЛЬКО когда найдена конкретная
//! ЦЕЛАЯ точка и она ПРОВЕРЕНА прямым вычислением всех ограничений; во всех
//! прочих случаях — `.unknown` (честный `Belnap N, e = 0`).
//!
//! ГРАНИЦЫ. Только ЛИНЕЙНЫЕ ограничения над `Int`, только конъюнкция.
//! `!=` и дизъюнкции вне фрагмента — вызывающий обязан вернуть `.unknown` сам.
const std = @import("std");

/// Один член линейной формы: `coeff * name`.
pub const Term = struct { name: []const u8, coeff: i64 };

/// Ограничение: `sum(coeff_i * x_i) + constant <= 0`.
pub const Lin = struct { terms: []const Term, constant: i64 };

/// Точка (имя = значение), найденная и ПРОВЕРЕННАЯ для вердикта `.sat`.
pub const Binding = struct { name: []const u8, value: i64 };

pub const Verdict = union(enum) {
    /// Несовместно. ЗВУЧИМО: доказано исключением переменных.
    unsat,
    /// Найдена конкретная ЦЕЛАЯ точка, проверенная прямым вычислением.
    sat: []Binding,
    /// Решить не удалось (вне фрагмента / бюджет / нет точки). Честный отказ.
    unknown: []const u8,
};

/// Бюджет на число ограничений: FM порождает комбинации нижних и верхних
/// границ, без ограничения это комбинаторный взрыв. При превышении — честный
/// `.unknown`, а НЕ догадка.
pub const MAX_CONSTRAINTS: usize = 20_000;
/// Бюджет на число исключаемых переменных.
pub const MAX_VARS: usize = 32;

pub const Solver = struct {
    allocator: std.mem.Allocator,
    arena: std.heap.ArenaAllocator,

    pub fn init(allocator: std.mem.Allocator) Solver {
        return .{ .allocator = allocator, .arena = std.heap.ArenaAllocator.init(allocator) };
    }

    pub fn deinit(self: *Solver) void {
        self.arena.deinit();
    }

    /// Сложить два ограничения с ЦЕЛЫМИ положительными множителями.
    /// `null` при переполнении i64 — тогда вызывающий честно сдаётся.
    fn combine(self: *Solver, p: Lin, w_p: i64, n: Lin, w_n: i64) ?Lin {
        var acc = std.ArrayListUnmanaged(Term).empty;
        for (p.terms) |t| {
            const v = std.math.mul(i64, t.coeff, w_p) catch return null;
            if (v == 0) continue;
            acc.append(self.arena.allocator(), .{ .name = t.name, .coeff = v }) catch return null;
        }
        for (n.terms) |t| {
            const v = std.math.mul(i64, t.coeff, w_n) catch return null;
            if (v == 0) continue;
            var merged = false;
            for (acc.items) |*e| {
                if (std.mem.eql(u8, e.name, t.name)) {
                    e.coeff = std.math.add(i64, e.coeff, v) catch return null;
                    merged = true;
                    break;
                }
            }
            if (!merged) acc.append(self.arena.allocator(), .{ .name = t.name, .coeff = v }) catch return null;
        }
        var keep = std.ArrayListUnmanaged(Term).empty;
        for (acc.items) |e| {
            if (e.coeff != 0) keep.append(self.arena.allocator(), e) catch return null;
        }
        const c1 = std.math.mul(i64, p.constant, w_p) catch return null;
        const c2 = std.math.mul(i64, n.constant, w_n) catch return null;
        const k = std.math.add(i64, c1, c2) catch return null;
        return .{ .terms = keep.items, .constant = k };
    }

    /// Коэффициент при `v` (0, если переменной нет).
    fn coeffOf(l: Lin, v: []const u8) i64 {
        for (l.terms) |t| {
            if (std.mem.eql(u8, t.name, v)) return t.coeff;
        }
        return 0;
    }

    /// Выбрать переменную для исключения: первая по порядку появления.
    /// Порядок ДЕТЕРМИНИРОВАН (важно для воспроизводимости вердиктов).
    ///
    /// ДЕФЕКТ #166 (НАЙДЕН измерением, а не рассуждением): раньше здесь
    /// возвращался ПЕРВЫЙ терм строки независимо от коэффициента. Если этот
    /// коэффициент равен нулю ВО ВСЕХ ограничениях набора (типичный случай,
    /// когда вызывающий передаёт терм `0*y` для «неиспользуемой» переменной),
    /// то при исключении не появляется ни одной комбинации `pos × neg`:
    /// набор не уменьшается, счётчик `eliminated` растёт до `MAX_VARS`,
    /// и решатель отдаёт честный, но ЛОЖНО-КОНСЕРВАТИВНЫЙ `.unknown` на
    /// СОВМЕСТНОЙ системе (`x <= 0 ∧ y <= 0`). Теперь выбирается переменная,
    /// у которой есть НЕНУЛЕВОЙ коэффициент: шаг исключения всегда продвигается.
    fn pickVar(set: []const Lin) ?[]const u8 {
        for (set) |l| {
            for (l.terms) |t| {
                if (t.coeff != 0) return t.name;
            }
        }
        return null;
    }
};

/// ГЛАВНАЯ ФУНКЦИЯ: доказать несовместность конъюнкции ограничений.
pub fn checkUnsatFallible(self: *Solver, input: []const Lin) !Verdict {
    var set = std.ArrayListUnmanaged(Lin).empty;
    for (input) |l| try set.append(self.arena.allocator(), l);

    var eliminated: usize = 0;
    while (true) {
        const v = Solver.pickVar(set.items) orelse break;
        if (eliminated >= MAX_VARS) return .{ .unknown = "слишком много переменных" };
        eliminated += 1;

        var pos = std.ArrayListUnmanaged(Lin).empty; // коэффициент при v > 0
        var neg = std.ArrayListUnmanaged(Lin).empty; // коэффициент при v < 0
        var zero = std.ArrayListUnmanaged(Lin).empty; // без v
        for (set.items) |l| {
            const c = Solver.coeffOf(l, v);
            const dst = if (c > 0) &pos else if (c < 0) &neg else &zero;
            try dst.append(self.arena.allocator(), l);
        }

        var next = std.ArrayListUnmanaged(Lin).empty;
        for (zero.items) |l| try next.append(self.arena.allocator(), l);
        for (pos.items) |p| {
            for (neg.items) |n| {
                // p: a*v + A <= 0 (a>0); n: b*v + B <= 0 (b<0).
                // (-b)*p + a*n даёт ограничение БЕЗ v (множители > 0).
                const w_p = -Solver.coeffOf(n, v);
                const w_n = Solver.coeffOf(p, v);
                const c = self.combine(p, w_p, n, w_n) orelse
                    return .{ .unknown = "переполнение коэффициентов" };
                try next.append(self.arena.allocator(), c);
                if (next.items.len > MAX_CONSTRAINTS) return .{ .unknown = "бюджет ограничений исчерпан" };
            }
        }
        set = next;
    }

    // Все переменные исключены: остались только константы.
    // `k <= 0` при `k > 0` — противоречие => НЕСОВМЕСТНО (звучимо).
    for (set.items) |l| {
        if (l.terms.len == 0 and l.constant > 0) return .unsat;
    }

    // Рационально совместно. Ищем ЦЕЛУЮ точку и ПРОВЕРЯЕМ её прямым счётом.
    if (findIntegerPoint(self, input)) |pt| return .{ .sat = pt };
    return .{ .unknown = "рационально совместно, целая точка не найдена" };
}


/// ОБЁРТКА ДЛЯ ПРОДАКШЕНА: отказ аллокатора НЕ фатален — это честный `.unknown`
/// (консервативный отказ: врата закрыты). Утечек нет: `Solver` владеет ареной,
/// которую освобождает `deinit`. Тестируемая (пропагирующая) версия —
/// `checkUnsatFallible`: её гоняет `checkAllAllocationFailures`.
pub fn checkUnsat(self: *Solver, input: []const Lin) Verdict {
    return checkUnsatFallible(self, input) catch .{ .unknown = "нет памяти" };
}

/// Прямая проверка точки: ВСЕ ограничения обязаны выполняться.
fn satisfies(input: []const Lin, pt: []const Binding) bool {
    for (input) |l| {
        var acc: i128 = l.constant;
        for (l.terms) |t| {
            var val: i128 = 0;
            for (pt) |b| {
                if (std.mem.eql(u8, b.name, t.name)) {
                    val = b.value;
                    break;
                }
            }
            acc += @as(i128, t.coeff) * val;
        }
        if (acc > 0) return false;
    }
    return true;
}

/// Имена переменных в порядке появления.
fn collectVars(self: *Solver, input: []const Lin) []const []const u8 {
    var out = std.ArrayListUnmanaged([]const u8).empty;
    for (input) |l| {
        for (l.terms) |t| {
            var seen = false;
            for (out.items) |e| {
                if (std.mem.eql(u8, e, t.name)) {
                    seen = true;
                    break;
                }
            }
            if (!seen) out.append(self.arena.allocator(), t.name) catch return out.items;
        }
    }
    return out.items;
}

/// Кандидаты значений: 0, ±1, ±100 и границы из ОДНОМЕРНЫХ ограничений.
/// Перебор ограничен бюджетом — при неудаче честный `.unknown`, а не догадка.
fn findIntegerPoint(self: *Solver, input: []const Lin) ?[]Binding {
    const vars = collectVars(self, input);
    if (vars.len == 0) return null;
    if (vars.len > 4) return null; // перебор не масштабируется — честный отказ

    var cand = std.ArrayListUnmanaged(i64).empty;
    const fixed = [_]i64{ 0, 1, -1, 100, -100 };
    for (fixed) |f| cand.append(self.arena.allocator(), f) catch return null;
    for (input) |l| {
        if (l.terms.len != 1) continue;
        const c = l.terms[0].coeff;
        if (c == 0) continue;
        // coeff*x + k <= 0: при c>0 -> x <= floor(-k/c); при c<0 -> x >= ceil(-k/c)
        const q = @divFloor(-l.constant, c);
        for ([_]i64{ q, q - 1, q + 1 }) |e| cand.append(self.arena.allocator(), e) catch return null;
    }

    var pt = std.ArrayListUnmanaged(Binding).empty;
    pt.appendNTimes(self.arena.allocator(), .{ .name = "", .value = 0 }, vars.len) catch return null;
    const total = std.math.pow(usize, cand.items.len, vars.len);
    if (total > 200_000) return null; // честный отказ вместо долгого перебора
    var idx: usize = 0;
    while (idx < total) : (idx += 1) {
        var rem = idx;
        for (vars, 0..) |v, k| {
            pt.items[k] = .{ .name = v, .value = cand.items[rem % cand.items.len] };
            rem /= cand.items.len;
        }
        if (satisfies(input, pt.items)) return pt.items;
    }
    return null;
}

/// Целочисленный сдвиг для СТРОГОГО неравенства: `a < b` <=> `a - b + 1 <= 0`.
/// Без этого сдвига FM (решающий над Q) не увидит целочисленной несовместности
/// вида `x > 5 ∧ x < 6`.
pub fn ltShift(terms: []const Term, constant: i64) Lin {
    return .{ .terms = terms, .constant = constant + 1 };
}


// ===========================================================================
//  ТЕСТЫ (пункт 1 плана v2.5)
// ===========================================================================

fn tag(v: Verdict) std.meta.Tag(Verdict) {
    return std.meta.activeTag(v);
}

test "LIA: НЕСОВМЕСТНО x<=5 и x>=10 (звучимый UNSAT)" {
    var s = Solver.init(std.testing.allocator);
    defer s.deinit();
    const t1 = [_]Term{.{ .name = "x", .coeff = 1 }};
    const t2 = [_]Term{.{ .name = "x", .coeff = -1 }};
    const sys = [_]Lin{
        .{ .terms = &t1, .constant = -5 }, // x - 5 <= 0
        .{ .terms = &t2, .constant = 10 }, // -x + 10 <= 0
    };
    try std.testing.expectEqual(std.meta.Tag(Verdict).unsat, tag(checkUnsat(&s, &sys)));
}

test "LIA: СОВМЕСТНО x<=5 и x>=0 -> точка ПРОВЕРЕНА прямым счётом" {
    var s = Solver.init(std.testing.allocator);
    defer s.deinit();
    const t1 = [_]Term{.{ .name = "x", .coeff = 1 }};
    const t2 = [_]Term{.{ .name = "x", .coeff = -1 }};
    const sys = [_]Lin{
        .{ .terms = &t1, .constant = -5 },
        .{ .terms = &t2, .constant = 0 },
    };
    const v = checkUnsat(&s, &sys);
    try std.testing.expectEqual(std.meta.Tag(Verdict).sat, tag(v));
    // Найденная точка обязана УДОВЛЕТВОРЯТЬ системе (иначе это не .sat).
    try std.testing.expect(satisfies(&sys, v.sat));
    try std.testing.expect(v.sat.len == 1 and std.mem.eql(u8, v.sat[0].name, "x"));
}

test "LIA: целочисленный сдвиг — x>5 и x<6 НЕСОВМЕСТНЫ над Z" {
    var s = Solver.init(std.testing.allocator);
    defer s.deinit();
    // x > 5  <=>  x >= 6  <=>  -x + 6 <= 0
    // x < 6  <=>  x <= 5  <=>   x - 5 <= 0  (через ltShift: x - 6 + 1)
    const t1 = [_]Term{.{ .name = "x", .coeff = -1 }};
    const t2 = [_]Term{.{ .name = "x", .coeff = 1 }};
    const sys = [_]Lin{
        .{ .terms = &t1, .constant = 6 },
        ltShift(&t2, -6),
    };
    try std.testing.expectEqual(std.meta.Tag(Verdict).unsat, tag(checkUnsat(&s, &sys)));
}

test "LIA: вне вычислимого фрагмента -> ЧЕСТНЫЙ unknown (не догадка)" {
    var s = Solver.init(std.testing.allocator);
    defer s.deinit();
    // 5 переменных: перебор точек не масштабируется, поэтому решатель обязан
    // вернуть unknown, а НЕ «наверное sat».
    const names = [_][]const u8{ "a", "b", "c", "d", "e" };
    var terms: [5]Term = undefined;
    for (names, 0..) |n, i| terms[i] = .{ .name = n, .coeff = 1 };
    const sys = [_]Lin{.{ .terms = &terms, .constant = 100 }};
    try std.testing.expectEqual(std.meta.Tag(Verdict).unknown, tag(checkUnsat(&s, &sys)));
}

test "LIA: сумма противоречивых границ по ДВУМ переменным -> UNSAT" {
    var s = Solver.init(std.testing.allocator);
    defer s.deinit();
    // x + y <= 1, x - y <= -10, -x <= -100  (x >= 100) -> противоречие
    const t1 = [_]Term{ .{ .name = "x", .coeff = 1 }, .{ .name = "y", .coeff = 1 } };
    const t2 = [_]Term{ .{ .name = "x", .coeff = 1 }, .{ .name = "y", .coeff = -1 } };
    const t3 = [_]Term{.{ .name = "x", .coeff = -1 }};
    const sys = [_]Lin{
        .{ .terms = &t1, .constant = -1 },
        .{ .terms = &t2, .constant = 10 },
        .{ .terms = &t3, .constant = 100 },
    };
    try std.testing.expectEqual(std.meta.Tag(Verdict).unsat, tag(checkUnsat(&s, &sys)));
}

// Убивает `builtin_lia.zig:223 [!=->==]` — ОДНОЧЛЕННЫЕ ограничения обязаны
// учитываться при поиске целой точки. Мутант `==` пропускал бы именно их,
// и система `x <= 5` / `-x <= 0` осталась бы без кандидатов -> честный, но
// НЕПОЛНЫЙ `unknown` вместо найденной точки.
test "МУТАНТ 223: одночленные ограничения дают точку (не unknown)" {
    var s = Solver.init(std.testing.allocator);
    defer s.deinit();
    const t_x = [_]Term{.{ .name = "x", .coeff = 1 }};
    const t_nx = [_]Term{.{ .name = "x", .coeff = -1 }};
    // ВАЖНО: точка НЕ совпадает с нулём (x ∈ [3, 5]), иначе достаточно было бы
    // вырожденного кандидата 0 и мутант выжил бы.
    const input = [_]Lin{
        .{ .terms = &t_x, .constant = -5 }, //  x - 5 <= 0  (x <= 5)
        .{ .terms = &t_nx, .constant = 3 }, // -x + 3 <= 0  (x >= 3)
    };
    const v = checkUnsat(&s, &input);
    try std.testing.expect(std.meta.activeTag(v) == .sat);
}

// =========================================================================
//  ИСПЫТАНИЕ Б: МЕТАМОРФНАЯ ИНВАРИАНТНОСТЬ (Metamorphic Testing).
//  Математическая истинность системы линейных неравенств НЕ зависит от:
//    (а) ПОРЯДКА неравенств (Фурье — Моцкин исключает переменные по порядку,
//        поэтому разный порядок идёт РАЗНЫМИ путями);
//    (б) ИМЁН переменных (переименование меняет порядок исключения);
//    (в) умножения неравенства на ПОЛОЖИТЕЛЬНУЮ константу k > 0
//        (`sum + c <= 0` <=> `k*sum + k*c <= 0`).
//  Вердикт обязан быть СТРОГО тем же (.unsat == .unsat, .sat == .sat).
// =========================================================================

/// Система: 3 строки вида `c0*x + c1*y + c2*z + k <= 0` (коэффициенты при
/// неиспользуемых переменных — 0). Возвращает ограничения с указанными
/// МАСШТАБОМ и ПЕРЕСТАНОВКОЙ имён (0 = как есть, 1 = поменять x и y).
fn buildMeta(a: std.mem.Allocator, rows: []const [4]i64, scale: i64, swap: bool) ![]Lin {
    var out = std.array_list.Managed(Lin).init(a);
    for (rows) |r| {
        var names = [_][]const u8{ "x", "y", "z" };
        var coefs = [_]i64{ r[0], r[1], r[2] };
        if (swap) {
            std.mem.swap([]const u8, &names[0], &names[1]);
            std.mem.swap(i64, &coefs[0], &coefs[1]);
        }
        var terms = std.array_list.Managed(Term).init(a);
        for (coefs, 0..) |c, i| {
            if (c != 0) try terms.append(.{ .name = names[i], .coeff = c * scale });
        }
        try out.append(.{ .terms = terms.items, .constant = r[3] * scale });
    }
    return out.items;
}

fn metaTag(v: Verdict) std.meta.Tag(Verdict) {
    return std.meta.activeTag(v);
}

test "METAMORPHIC: инвариантность к порядку строк, переименованию переменных и масштабу x3" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var i: usize = 0;
    var checked: usize = 0;
    while (i < 20) : (i += 1) {
        // 10 НЕСОВМЕСТНЫХ (x+y >= 0, но x+y <= -(i+1)) и 10 СОВМЕСТНЫХ.
        const c: i64 = if (i < 10) @intCast(i + 1) else -@as(i64, @intCast(i - 9));
        const rows = [_][4]i64{
            .{ 1, 1, 0, c }, // x + y + c <= 0
            .{ -1, 0, 0, 0 }, // -x <= 0  (x >= 0)
            .{ 0, -1, 0, 0 }, // -y <= 0  (y >= 0)
        };
        var s = Solver.init(a);
        const base = checkUnsat(&s, try buildMeta(a, &rows, 1, false));
        const want = metaTag(base);
        if (i < 10) try std.testing.expect(want == .unsat) else try std.testing.expect(want == .sat);

        // (а) РАЗВОРОТ порядка строк.
        var rev: [3][4]i64 = undefined;
        for (rows, 0..) |r, j| rev[rows.len - 1 - j] = r;
        var s2 = Solver.init(a);
        try std.testing.expectEqual(want, metaTag(checkUnsat(&s2, try buildMeta(a, &rev, 1, false))));
        // (б) ПЕРЕИМЕНОВАНИЕ переменных (x <-> y) — меняет порядок исключения.
        var s3 = Solver.init(a);
        try std.testing.expectEqual(want, metaTag(checkUnsat(&s3, try buildMeta(a, &rows, 1, true))));
        // (в) МАСШТАБ k = 3 (положительный).
        var s4 = Solver.init(a);
        try std.testing.expectEqual(want, metaTag(checkUnsat(&s4, try buildMeta(a, &rows, 3, false))));
        checked += 3;
    }
    // 20 систем x 3 трансформации = 60 проверок инвариантности.
    try std.testing.expectEqual(@as(usize, 60), checked);
}

// Убивает `builtin_lia.zig:126 [>=->>]` — БЮДЖЕТ ПЕРЕМЕННЫХ. При 33 переменных
// (> MAX_VARS = 32) решатель обязан честно вернуть `.unknown`, а не продолжать
// исключение: мутант `>` доходит до конца и выдаёт `.sat` на системе, которую
// он по бюджету проверять не имеет права.
test "МУТАНТ 126: бюджет MAX_VARS — противоречие на 32-й элиминации" {
    // Цепочка v0 <= v1 <= ... <= v33 (33 связи) ПЛЮС v33 - v0 + 1 <= 0.
    // Противоречие (1 <= 0) всплывает ровно после исключения 32 переменных,
    // поэтому корректный код обязан вернуть `.unknown` по бюджету MAX_VARS,
    // а мутант `>` идёт дальше и объявляет `.unsat`.
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var s = Solver.init(a);
    var names: [34][]const u8 = undefined;
    for (0..34) |i| names[i] = try std.fmt.allocPrint(a, "v{d}", .{i});
    var terms: [34][2]Term = undefined;
    var cons: [34]Lin = undefined;
    for (0..33) |i| {
        terms[i][0] = .{ .name = names[i], .coeff = 1 };
        terms[i][1] = .{ .name = names[i + 1], .coeff = -1 };
        cons[i] = .{ .terms = &terms[i], .constant = 0 };
    }
    terms[33][0] = .{ .name = names[0], .coeff = -1 };
    terms[33][1] = .{ .name = names[33], .coeff = 1 };
    cons[33] = .{ .terms = &terms[33], .constant = 1 };
    const v = checkUnsat(&s, &cons);
    try std.testing.expect(std.meta.activeTag(v) == .unknown);
}

// Убивает `builtin_lia.zig:80 [false->true]` — флаг `merged` в `combine`.
// Мутант теряет слагаемые из ВТОРОГО ограничения, которых нет в первом:
// при исключении `x` из `x <= 0` и `-x - y <= 0` пропадает `y`, и система
// `x <= 0, x + y >= 0, y <= -1` (НЕСОВМЕСТНАЯ) перестаёт опровергаться.
test "МУТАНТ 80: combine не теряет слагаемые при слиянии" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var s = Solver.init(a);
    const t_x = [_]Term{.{ .name = "x", .coeff = 1 }};
    const t_xy = [_]Term{ .{ .name = "x", .coeff = -1 }, .{ .name = "y", .coeff = -1 } };
    const t_y = [_]Term{.{ .name = "y", .coeff = 1 }};
    const input = [_]Lin{
        .{ .terms = &t_x, .constant = 0 }, // x <= 0
        .{ .terms = &t_xy, .constant = 0 }, // -x - y <= 0  (x + y >= 0)
        .{ .terms = &t_y, .constant = 1 }, // y + 1 <= 0   (y <= -1)
    };
    const v = checkUnsat(&s, &input);
    try std.testing.expect(std.meta.activeTag(v) == .unsat);
}

// Убивает `builtin_lia.zig:189 [false->true]` — `if (acc > 0) return false;`
// в `satisfies`. Мутант объявляет ПЕРВУЮ же нарушающую точку валидной.
// Система `x + y = 3` рационально совместна, но НИ ОДНА из точек-кандидатов
// (0, ±1, ±100, границы) её не удовлетворяет: корректный код даёт честный
// `unknown`, мутант — ложный `.sat`.
test "МУТАНТ 189: satisfies отвергает невалидную точку" {
    var ar = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer ar.deinit();
    const a = ar.allocator();
    var s = Solver.init(a);
    const t_xy = [_]Term{ .{ .name = "x", .coeff = 1 }, .{ .name = "y", .coeff = 1 } };
    const t_nxy = [_]Term{ .{ .name = "x", .coeff = -1 }, .{ .name = "y", .coeff = -1 } };
    const input = [_]Lin{
        .{ .terms = &t_xy, .constant = -3 }, //  x + y - 3 <= 0  (x + y <= 3)
        .{ .terms = &t_nxy, .constant = 3 }, // -x - y + 3 <= 0  (x + y >= 3)
    };
    const v = checkUnsat(&s, &input);
    try std.testing.expect(std.meta.activeTag(v) == .unknown);
}

test "ДЕФЕКТ #166: нулевой коэффициент НЕ должен блокировать исключение" {
    // ИЗМЕРЕНО ДО ФИКСА: этот набор (x <= 0, y <= 0) возвращал `.unknown`,
    // потому что `pickVar` выбирал `x` даже когда его коэффициент РАВЕН НУЛЮ
    // (вызывающий передаёт терм `0*x` для «неиспользуемой» переменной):
    // комбинаций `pos x neg` нет -> набор не уменьшается -> `eliminated`
    // дорастает до `MAX_VARS` -> ложный `.unknown` на СОВМЕСТНОЙ системе.
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const al = arena.allocator();

    var s = Solver.init(al);
    defer s.deinit();

    // (1) СОВМЕСТНАЯ система с нулевыми коэффициентами: обязана быть `.sat`.
    const t1 = try al.alloc(Term, 2);
    t1[0] = .{ .name = "x", .coeff = 1 };
    t1[1] = .{ .name = "y", .coeff = 0 };
    const t2 = try al.alloc(Term, 2);
    t2[0] = .{ .name = "x", .coeff = 0 };
    t2[1] = .{ .name = "y", .coeff = 1 };
    const sys = [_]Lin{
        .{ .terms = t1, .constant = 0 },
        .{ .terms = t2, .constant = 0 },
    };
    const v1 = checkUnsat(&s, &sys);
    try std.testing.expectEqual(Verdict.sat, std.meta.activeTag(v1));
    // Предъявленная точка обязана УДОВЛЕТВОРЯТЬ системе (звучимость SAT).
    for (v1.sat) |b| {
        if (std.mem.eql(u8, b.name, "x")) try std.testing.expectEqual(@as(i64, 0), b.value);
        if (std.mem.eql(u8, b.name, "y")) try std.testing.expectEqual(@as(i64, 0), b.value);
    }

    // (2) НЕСОВМЕСТНАЯ система с теми же нулевыми коэффициентами -> `.unsat`.
    const t3 = try al.alloc(Term, 2);
    t3[0] = .{ .name = "x", .coeff = 1 };
    t3[1] = .{ .name = "y", .coeff = 0 };
    const t4 = try al.alloc(Term, 2);
    t4[0] = .{ .name = "x", .coeff = -1 };
    t4[1] = .{ .name = "y", .coeff = 0 };
    // -x + 1 <= 0  =>  x >= 1, а вместе с x <= 0 это НЕСОВМЕСТНО.
    const sys2 = [_]Lin{
        .{ .terms = t3, .constant = 0 },
        .{ .terms = t4, .constant = 1 },
    };
    try std.testing.expectEqual(Verdict.unsat, std.meta.activeTag(checkUnsat(&s, &sys2)));
}
