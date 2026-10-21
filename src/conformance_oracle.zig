// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! Conformance oracle (Phase 5): prints FACTS produced by the kernel itself.
//!
//! WHY. `conformance_check.py` must not trust test *names*; it must read the
//! same functions the verifier uses. This program links the real modules and
//! emits one `section|key|value` line per fact; the Python harness asserts the
//! expected values and turns each section into PASS/FAIL.
//!
//! Run: zig run --dep compat -Mroot=src/conformance_oracle.zig -Mcompat=src/compat.zig

const std = @import("std");
const compat = @import("compat");
const Eq2 = @import("core/eq2.zig").Eq2;
const eq2 = @import("core/eq2.zig");
const axes = @import("next/state_axes.zig");
const ledger = @import("next/evidence_ledger.zig");
const prov = @import("next/provenance.zig");
const kern_x = @import("runtime/kern_x.zig");
const KernX = kern_x.KernX;
const gate = @import("verifier/admission_gate.zig");
const cache = @import("proof_cache.zig");
const kfs = @import("core/kernfs_router.zig");

const ast32: [32]u8 = @splat(0x44);
const con32: [32]u8 = @splat(0x55);

fn provedRun(_: ?*anyopaque, _: std.mem.Allocator, _: [32]u8, _: [32]u8, _: []const u8) gate.CheckerVerdict {
    return .Proved;
}

fn same(a1: [32]u8, b1: [32]u8) bool {
    return std.mem.eql(u8, &a1, &b1);
}

fn pathRejected(p: []const u8) bool {
    if (kfs.KernFS.validatePath(p)) |_| return false else |_| return true;
}

fn line(comptime fmt: []const u8, args: anytype) void {
    var buf: [512]u8 = undefined;
    const s = std.fmt.bufPrint(&buf, fmt ++ "\n", args) catch return;
    compat.fileWriteAll(std.Io.File.stdout(), s) catch {};
}

pub fn main() !void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const a = arena.allocator();

    // 1. The four Belnap values as twist pairs (p, n).
    for ([_]Eq2{ .N, .T, .F, .B }) |v| {
        line("b4|{s}|{d}|{d}", .{ v.symbol(), v.positive(), v.negative() });
    }

    // 2. All 16 joinK pairs.
    for ([_]Eq2{ .N, .T, .F, .B }) |x| {
        for ([_]Eq2{ .N, .T, .F, .B }) |y| {
            line("join|{s}|{s}|{s}", .{ x.symbol(), y.symbol(), Eq2.joinK(x, y).symbol() });
        }
    }

    // 3. Both lattices: a <= b iff join(a,b) == b (information) /
    //    a <=t b iff orT(a,b) == b (truth).
    for ([_]Eq2{ .N, .T, .F, .B }) |x| {
        for ([_]Eq2{ .N, .T, .F, .B }) |y| {
            line("le_k|{s}|{s}|{d}", .{ x.symbol(), y.symbol(),
                @intFromBool(Eq2.joinK(x, y) == y) });
            line("le_t|{s}|{s}|{d}", .{ x.symbol(), y.symbol(),
                @intFromBool(eq2.orT(x, y) == y) });
        }
    }

    // 4. Conflation (~): information inversion, involution.
    for ([_]Eq2{ .N, .T, .F, .B }) |v| {
        line("conflate|{s}|{s}", .{ v.symbol(), eq2.conflate(v).symbol() });
    }
    var inv = true;
    for ([_]Eq2{ .N, .T, .F, .B }) |v| {
        if (eq2.conflate(eq2.conflate(v)) != v) inv = false;
    }
    line("conflate_involution|all|{d}", .{@intFromBool(inv)});

    // 5. Seven axes: the verdict -> Belnap mapping.
    for ([_]axes.VerificationVerdict{ .proved, .refuted, .unknown, .timeout,
        .out_of_fuel, .invalid_certificate, .tool_error }) |v|
    {
        line("verdict|{s}|{s}", .{ @tagName(v), @tagName(axes.toBelnap(v).?) });
    }
    var b_reachable = false;
    for ([_]axes.VerificationVerdict{ .proved, .refuted, .unknown, .timeout,
        .out_of_fuel, .invalid_certificate, .tool_error }) |v|
    {
        if (axes.toBelnap(v).? == .B) b_reachable = true;
    }
    line("verdict_b_never|all|{d}", .{@intFromBool(!b_reachable)});

    // 6. Evidence ledger: add / retract / idempotency / order independence.
    var l = ledger.Ledger.init(a);
    _ = try l.add("e1", .positive);
    line("ledger|after_pos|{s}", .{l.state().symbol()});
    _ = try l.add("e2", .negative);
    line("ledger|conflict|{s}", .{l.state().symbol()});
    _ = l.retract("e2");
    line("ledger|after_retract|{s}", .{l.state().symbol()});
    const dup = try l.add("e1", .positive);
    line("ledger|duplicate_rejected|{d}", .{@intFromBool(!dup)});
    var l2 = ledger.Ledger.init(a);
    _ = try l2.add("x", .negative);
    _ = try l2.add("y", .positive);
    var l3 = ledger.Ledger.init(a);
    _ = try l3.add("y", .positive);
    _ = try l3.add("x", .negative);
    line("ledger|order_independent|{d}", .{@intFromBool(l2.state().eq(l3.state()))});

    // 7. Provenance: negative recursive SCC rejected, positive allowed.
    const names = [_][]const u8{ "f", "g" };
    const neg = [_]prov.Edge{
        .{ .from = 0, .to = 1 },
        .{ .from = 1, .to = 0, .kind = .negated },
    };
    const pos = [_]prov.Edge{
        .{ .from = 0, .to = 1 },
        .{ .from = 1, .to = 0 },
    };
    line("scc|negative|{d}", .{@intFromBool(try prov.hasNegativeRecursiveCycle(
        .{ .kind = .g_src, .nodes = &names, .edges = &neg }, a))});
    line("scc|positive|{d}", .{@intFromBool(try prov.hasNegativeRecursiveCycle(
        .{ .kind = .g_src, .nodes = &names, .edges = &pos }, a))});

    // 7. Admission gate: certificate binding and QueryKind (Ф1).
    {
        const ast: [32]u8 = @splat(0x11);
        const con: [32]u8 = @splat(0x22);
        var cert = gate.ProofCertificate{
            .target_ast_digest = ast,
            .contract_digest = con,
            .checker_id = 1,
            .witness_payload = "proof-bytes",
            .query_kind = .refutation,
        };
        const policy = gate.VerificationPolicy{ .require_anti_vacuity = false,
            .allowed_checkers = 2, .expected_kind = .refutation };
        const checker = gate.TrustedChecker{ .runFn = provedRun };

        const ok = gate.AdmissionGate.verifyClaimWithChecker(a, ast, con, cert, policy, checker);
        line("gate|matching_kind|{s}", .{if (ok) |r| r.eq2_status.symbol() else |_| "ERR"});

        // Certificate from ANOTHER query kind: valid proof, wrong claim.
        cert.query_kind = .equivalence;
        const qk = gate.AdmissionGate.verifyClaimWithChecker(a, ast, con, cert, policy, checker);
        line("gate|query_kind_mismatch|{d}", .{@intFromBool(if (qk) |_| false else |e| e == gate.GateError.QueryKindMismatch)});
        cert.query_kind = .refutation;

        // Certificate bound to a DIFFERENT function.
        const other: [32]u8 = @splat(0x33);
        const reused = gate.AdmissionGate.verifyClaimWithChecker(a, other, con, cert, policy, checker);
        line("gate|cert_reuse_other_fn|{d}", .{@intFromBool(if (reused) |_| false else |e| e == gate.GateError.AstHashMismatch)});
    }

    // 9. Cache key: every one of the 13 fields must change the key.
    {
        const base = cache.ProofCache.CacheKey{ .body_hashes = @splat(1), .contract = @splat(2) };
        const b0 = base.digest();
        var c = base;
        c.task_kind = 1;
        line("cache|task_kind|{d}", .{@intFromBool(!same(c.digest(), b0))});
        c = base;
        c.semantic_slice = @splat(9);
        line("cache|semantic_slice|{d}", .{@intFromBool(!same(c.digest(), b0))});
        c = base;
        c.body_hashes = @splat(3);
        line("cache|body_hashes|{d}", .{@intFromBool(!same(c.digest(), b0))});
        c = base;
        c.contract = @splat(4);
        line("cache|contract|{d}", .{@intFromBool(!same(c.digest(), b0))});
        c = base;
        c.dependency_hashes = @splat(5);
        line("cache|dependency_hashes|{d}", .{@intFromBool(!same(c.digest(), b0))});
        c = base;
        c.model_fingerprint = @splat(6);
        line("cache|model_fingerprint|{d}", .{@intFromBool(!same(c.digest(), b0))});
        c = base;
        c.prompt_hash = @splat(7);
        line("cache|prompt_hash|{d}", .{@intFromBool(!same(c.digest(), b0))});
        c = base;
        c.params_hash = @splat(8);
        line("cache|params_hash|{d}", .{@intFromBool(!same(c.digest(), b0))});
        c = base;
        c.tools_hash = @splat(9);
        line("cache|tools_hash|{d}", .{@intFromBool(!same(c.digest(), b0))});
        c = base;
        c.retrieval_hash = @splat(10);
        line("cache|retrieval_hash|{d}", .{@intFromBool(!same(c.digest(), b0))});
        c = base;
        c.schema_hash = @splat(11);
        line("cache|schema_hash|{d}", .{@intFromBool(!same(c.digest(), b0))});
        c = base;
        c.policy_hash = @splat(12);
        line("cache|policy_hash|{d}", .{@intFromBool(!same(c.digest(), b0))});
        c = base;
        c.checker_version = @splat(13);
        line("cache|checker_version|{d}", .{@intFromBool(!same(c.digest(), b0))});
        c = base;
        c.version = 3;
        line("cache|schema_prefix|{d}", .{@intFromBool(!same(c.digest(), b0))});
        // Solver version must reach the key (Ф3.5).
        const k1 = cache.ProofCache.keyOfWithSolver(ast32, con32, "proof", "Z3 4.8");
        const k2 = cache.ProofCache.keyOfWithSolver(ast32, con32, "proof", "Z3 5.1");
        line("cache|solver_version|{d}", .{@intFromBool(!same(k1, k2))});
    }

    // 11. KERNFS: path traversal, NUL, write denial.
    {
        line("kernfs|dotdot|{d}", .{@intFromBool(pathRejected("../etc/passwd"))});
        line("kernfs|inner_dotdot|{d}", .{@intFromBool(pathRejected("/a/../../b"))});
        line("kernfs|null_byte|{d}", .{@intFromBool(pathRejected(&[_]u8{ 97, 0, 98 }))});
        line("kernfs|normal|{d}", .{@intFromBool(pathRejected("/a/b"))});
        var fs: kfs.KernFS = undefined;
        const w = fs.write("/a", "b");
        line("kernfs|write_denied|{d}", .{@intFromBool(if (w) |_| false else |e| e == kfs.KernFsError.AccessDenied)});
    }

    // 8. KERN-X: ONE shared fuel across two machines + depth quota.
    var fuel: u32 = 10;
    var arena_used: usize = 0;
    var out_used: usize = 0;
    var depth: u32 = 0;
    var calls: u32 = 0;
    const budget = kern_x.Budget{ .fuel = &fuel, .arena = &arena_used, .arena_max = 1024,
        .output = &out_used, .output_max = 1024, .depth = &depth, .depth_max = 8,
        .host_calls = &calls, .host_calls_max = 4 };
    var vm1 = KernX.initWithBudget(budget);
    var vm2 = KernX.initWithBudget(budget);
    // 10 NO-OPs = exactly 10 units of fuel.
    vm1.execute(&[_]u8{ 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 }) catch {};
    line("kernx|fuel_after_first|{d}", .{fuel});
    var exhausted = false;
    vm2.execute(&[_]u8{0x00}) catch |err| switch (err) {
        error.OutOfFuel => exhausted = true,
        else => {},
    };
    line("kernx|second_branch_exhausted|{d}", .{@intFromBool(exhausted)});
}
