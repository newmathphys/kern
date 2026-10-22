# Versioning policy

KERN follows [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).
This document exists because the rule was previously **implicit** — and an
implicit rule drifts. Measured before this document was written: **8 tags in two
days**, two of them 29 minutes apart (`v2.6.2` → `v2.6.3`), and `v2.6.1` shipped a
new user-facing command (`kernc pack-dir`) as a *patch* although SemVer calls that
a *minor*.

## What each part means here

| Part | Bump when | Examples |
|:--|:--|:--|
| **MAJOR** | the C ABI in `include/kern.h` changes, or the `.kimg` wire format changes in a way old readers reject | removing a `kern_*` export; changing a header field |
| **MINOR** | a **new user-visible capability**: a `kernc`/`kernx` command or flag, a new contract class, a new SMT theory, a new output format field that consumers may rely on | `kernc pack-dir`; `[advisory]` contract classes; `--query-kind` |
| **PATCH** | bug fixes, soundness fixes, documentation, gates, evidence, version-consistency fixes — **no new capability** | #317, #318, #312, #320, #321 |

Adding a gate or a CHECK target is **not** a capability: it changes how the
project checks itself, not what a user can do. That is a patch.

## Release cadence

1. **Fixes accumulate.** Do not tag every fix. A tag is a **milestone**, not a
   save point: if `v2.6.3` lands 29 minutes after `v2.6.2`, the tag stops meaning
   anything and users who pinned the previous one learn to ignore tags.
2. **One tag per closed plan step or cycle** — see
   [`PLAN_v2.6.4.md`](PLAN_v2.6.4.md) §2 for what "closed" means (acceptance met,
   gates green, attestation re-signed).
3. **The CHANGELOG section is written before the tag**, never after.
4. **Never move a published tag.** A new commit is a new tag; `main` is not
   force-pushed.
5. **Every tag is signed** (Ed25519) and carries an attestation whose
   `attests_commit` points at the content commit — see
   [`KEY_MANAGEMENT.md`](KEY_MANAGEMENT.md).

## Enforced by

| Gate | What it checks |
|:--|:--|
| `make version-check` | one version across `src/main.zig`, `src/next/main.zig`, `src/capi.zig`, `server.json`, `action.yml`, `README.md` and both binaries |
| `make changelog-check` | the version in `src/main.zig` has a `## [x.y.z]` section |
| `make metrics-guard` | no stale version or count in any guarded surface |

## Known deviations (recorded, not hidden)

- **`v2.6.1` is a mis-classified patch**: it added `kernc pack-dir`. Per this
  policy it should have been `v2.7.0`. It is left as published — tags are
  immutable here — and recorded so the classification error is visible.
- The two-day burst (`v2.5.0` → `v2.6.4`, 8 tags) happened while the project was
  closing the honesty and soundness defects (#239–#321) one at a time. From
  `v2.6.4` on, releases follow the cadence above.
