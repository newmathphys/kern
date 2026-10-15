# Security Policy

## What KERN is (and is not)

KERN is a verification gateway: it decides whether a claim about code is
*admissible* (`e = 1`) or not (`e = 0`). A defect in KERN is security-relevant
when it can make the gate accept something it should reject — a **false accept**.

The following are the highest-severity classes for this project:

| Class | Example |
|:--|:--|
| **Gate bypass** | a payload/witness that forces `e = 1` without a trusted-checker verdict |
| **Integrity bypass** | a modified `.kimg` payload that is served without `PayloadTampered` |
| **Verdict forgery** | a certificate or attestation that validates for a different contract/commit |
| **Memory unsafety** | out-of-bounds read, overflow, or UB reachable from untrusted input |
| **Denial of service** | crafted input that hangs the parser, solver bridge, or filesystem router |
| **Sandbox escape** | path traversal or NUL injection escaping `/raw/` in KERNFS |

## Supported versions

Security fixes are applied to the active line only.

| Line | Toolchain | Status |
|:--|:--|:--|
| `main` | Zig 0.17.0 | **supported** |
| `zig-0.17-migration` | Zig 0.17.0 | supported (migration line) |
| older commits | Zig 0.13.0 | archived baseline, not maintained |

## Reporting a vulnerability

**Please do not open a public issue for security-relevant findings.**

Report privately through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository (**Security → Report a vulnerability**).

If that channel is unavailable, contact the maintainer listed in
[`README.md`](README.md) / [`LICENSE`](LICENSE).

### What to include

1. The exact command and input that triggers the issue.
2. The observed behaviour and the expected behaviour.
3. Which invariant is violated (`e = 1` without proof, tampered payload served,
   crash, hang, leak).
4. Whether the issue is reachable from untrusted input (a `.kern` project, a
   `.kimg` image, an `.smt2` contract).
5. If possible, a minimal reproducing artifact.

### What to expect

| Stage | Target |
|:--|:--|
| Acknowledgement | within 7 days |
| Initial assessment | within 14 days |
| Fix or mitigation | depends on severity; critical gate bypass is prioritised |
| Public disclosure | coordinated, after a fix is available |

Credit will be given in the defect registry
(`docs/CAPABILITY_STATUS.md`) unless you prefer to stay anonymous.

## Known limitations that are NOT vulnerabilities

These are documented, deliberate boundaries (see
`formal/certification/KNOWN_LIMITATIONS.md`):

- **A missing solver closes the gate.** With no `z3` in `PATH`, every claim stays
  at `e = 0`. This is safe degradation by design, not a bypass.
- **Debug builds are not bit-reproducible** (non-deterministic DWARF in Zig 0.17).
  Attested artefacts are ReleaseFast.
- **The static gate has ~70 % recall** on the HumanEval set. It is a filter, not a
  prover for arbitrary code.
- **`proof_check.zig` performs structural validation only** — it is not a full
  Alethe/LFSC proof checker.
- **The SLSA attestation is unsigned** in this environment (no `cosign`).

## Hardening already in place

For context when assessing a report:

- Merkle root over the descriptor table **and** SHA-256 over every payload
  (a one-byte modification yields `PayloadTampered`).
- Checked arithmetic (`std.math.add/mul`) on all offset and size computations.
- No `@ptrCast`/`@alignCast` in the read path — records are decoded byte-wise
  (`[96]u8`, alignment 1), which is why ARM64 reports no `Bus Error`.
- `comptime` layout assertions on every on-disk structure.
- Atomic image writes (tmp + `fsync` + `rename` + directory `fsync`).
- A hard timeout and FD/zombie discipline around every solver subprocess.
- Can-fail harness proving that all 60 checks are able to fail.

Thank you for helping keep KERN honest.
