//! KERN-Next: модель данных (§5, §7 спецификации KERN-Next).
const std = @import("std");

/// Статусная система (§7). Типизирована, а не свободный текст.
pub const Status = enum {
    proven,
    refuted,
    verified,
    tested,
    compiled,
    empirical,
    hypothesis,
    blocked,
    unknown,
    not_found,
    not_yet_reproducible,
    /// КОНФЛИКТ (Белнап B): есть и подтверждающее, и опровергающее исполнение.
    /// Расширение словаря §7 — необходимо для аккумулятора joinK.
    conflicted,

    pub fn fromString(s: []const u8) ?Status {
        inline for (@typeInfo(Status).Enum.fields) |f| {
            if (std.mem.eql(u8, s, f.name)) return @field(Status, f.name);
        }
        return null;
    }
};

/// Виды объектов (§5).
pub const Kind = enum {
    project,
    artifact,
    module,
    symbol,
    claim,
    evidence,
    execution,
    proof,
    metric,
    relation,
    decision,
    blocker,
    snapshot,
    question,
    agent_packet,
    cache_entry,

    pub fn fromString(s: []const u8) ?Kind {
        inline for (@typeInfo(Kind).Enum.fields) |f| {
            if (std.mem.eql(u8, s, f.name)) return @field(Kind, f.name);
        }
        return null;
    }
};

/// Разрешённые типы связей (§4.4).
pub const RelationKind = enum {
    supported_by, depends_on, imports, calls, implements, documents, tests,
    proves, contradicts, updates, duplicates, references, generates,
    derived_from, blocked_by,

    pub fn fromString(s: []const u8) ?RelationKind {
        inline for (@typeInfo(RelationKind).Enum.fields) |f| {
            if (std.mem.eql(u8, s, f.name)) return @field(RelationKind, f.name);
        }
        return null;
    }
};

pub const Artifact = struct {
    id: []const u8,
    path: []const u8,
    kind: []const u8,
    hash: ?[]const u8,
};

pub const Metric = struct { name: []const u8, value: f64 };

pub const Claim = struct {
    id: []const u8,
    statement: []const u8,
    status: Status,
    scope: ?[]const u8,
    evidence_ids: []const []const u8,
    metrics: []const Metric,
};

pub const Evidence = struct {
    id: []const u8,
    kind: []const u8,
    source: []const u8,
};

pub const Proof = struct {
    id: []const u8,
    path: []const u8,
    system: []const u8,
    theorem: []const u8,
    status: Status,
};

pub const Module = struct {
    id: []const u8,
    name: []const u8,
    requires: []const []const u8,
    ensures: []const []const u8,
};

pub const Link = struct {
    from: []const u8,
    to: []const u8,
    relation: RelationKind,
};

pub const Project = struct {
    name: []const u8,
    version: ?[]const u8,
    root: ?[]const u8,
    artifacts: []const Artifact,
    claims: []const Claim,
    evidence: []const Evidence,
    proofs: []const Proof,
    modules: []const Module,
    links: []const Link,

    pub fn nodeCount(self: Project) usize {
        return 1 + self.artifacts.len + self.claims.len + self.evidence.len +
            self.proofs.len + self.modules.len + self.links.len;
    }
};

/// Стабильный ID: `kind:slug`. Детерминирован от имени → не меняется
/// между пересборками (критерий 9 из §20).
pub fn stableId(allocator: std.mem.Allocator, kind: Kind, name: []const u8) ![]const u8 {
    return std.fmt.allocPrint(allocator, "{s}:{s}", .{ @tagName(kind), name });
}

/// Нормализация: нижний регистр, пробелы → `_` (для slug).
pub fn slugify(allocator: std.mem.Allocator, s: []const u8) ![]const u8 {
    const out = try allocator.alloc(u8, s.len);
    for (s, 0..) |c, i| out[i] = if (c == ' ') '_' else std.ascii.toLower(c);
    return out;
}

pub fn isKnownStatus(s: []const u8) bool {
    return Status.fromString(s) != null;
}
