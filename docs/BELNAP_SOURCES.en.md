# KERN's formal basis: sources and code cross-check

> **Why this file exists.** Every KERN line that governs admission rests on a
> specific published result. This page records which one, where it lives in the
> code, and **what KERN does not implement**. Claims are machine-checked:
> `make citations-check`.

## §0 Reading the statuses

| Status | Meaning | Where it may be used |
|:--|:--|:--|
| `verified` | publisher/Crossref page opened, fields compared | §1–§5 as a basis |
| `secondary` | confirmed via another paper's reference list; DOI not opened | §1–§5, with a note |
| `unverified` | not confirmed | **§7 only**, as “needs checking” |

Data: `docs/references.bib` (25 entries, keys `§REF:<key>`) and
`docs/references.lock.json` (field snapshot). `citations-check` fails when a key
is unknown, an `unverified` key is cited in §1–§6, an entry has no DOI/ISBN/arXiv,
a `file:line` or Lean theorem reference does not exist, or the EN page is missing
a key used on the RU page.

## §1 Primary sources

- **§REF:belnap1977useful** — four values `4 = P({T,F})`, two orders (`≤t`, `≤k`),
  and the motivation “a local conflict must not poison the database”.
- **§REF:dunn1976intuitive** — relational FDE semantics: `A ρ 1` and `A ρ 0` as
  independent evidence; hence the `(p, n)` pair.
- **§REF:ginsberg1988** — the term “bilattice” and the interlacing condition.
- **§REF:fitting1991** — monotonicity of the consequence operator over `≤k` and the
  fixed point: why accumulating evidence cannot be overwritten by the last run.
- **§REF:fitting1994** — K3/LP as fragments of B4 (drop `B` / drop `N`).

## §2 Bilattices and De Morgan lattices

- **§REF:arieli1996** — logical bilattices and bifilters: the formal frame for `{T,B}`.
- **§REF:font1997** — B4 and De Morgan lattices: why `∧, ∨, ¬` form a correct algebra.
- **§REF:rivieccio2011residuated** — residuated bilattices: `⊔/⊓` as a residual pair.
- **§REF:shramko2005sixteen** — 16-valued logics; unused in KERN, but it is where the
  phrase “how a computer network should think” comes from (see §7).

## §3 Generalized values

- **§REF:shramko2011truth** — the `16₃` trilattice (truth, falsity, information orders).
  **Not implemented**: KERN has two orders, not three.
- **§REF:omori2017forty** — 40 years of FDE: what counts as the standard semantics.
- **§REF:omori2019newessays** — modern anthology: BD expansions, connexive logics.

## §4 The Russian school

- **§REF:karpenko2017four** — expansions of BD and DM4, lattices of functional expansions.
- **§REF:pavlov2005** — truth/falsity assertion operators: reducing 4-valued semantics to
  a metalanguage (the idea behind `e = 1` only for `T`).
- **§REF:shramko2017relatives** — relatives of FDE (exactly true, non-falsity).
  Relevant to §6: KERN does **not** distinguish “exactly true” from “non-false” — it is stricter.

## §5 Theory → code

Link format: `src/path:line` or `formal/<file>.lean:<theorem>` — both are verified
by `citations-check` (the line exists; the theorem is declared).

| In KERN | Where | Source |
|:--|:--|:--|
| `Eq2 {N,T,F,B}`, code `p \| (n<<1)` | `src/core/eq2.zig:18` | §REF:belnap1977useful · §REF:dunn1976intuitive |
| twist representation `(t,f)` | `src/core/eq2.zig:24` | §REF:jakl2025four |
| `joinKnowledge` = ⊔ over `≤k` (bitwise OR) | `src/core/eq2.zig:39` | §REF:fitting1991 · §REF:arieli1996 |
| `meetK` = ⊓ over `≤k` (AND) | `src/core/eq2.zig:49` | §REF:rivieccio2011residuated |
| ¬ (swap `p↔n`) | `src/core/eq2.zig:74` | §REF:belnap1977useful · §REF:font1997 |
| `andT` / `orT` (⊓/⊔ over `≤t`) | `src/core/eq2.zig:85` | §REF:font1997 |
| conflation `~` (information inversion) | `src/core/eq2.zig:89` | §REF:fitting1991 |
| evidence ledger `add`/`retract` (recompute `(p,n)`, epoch) | `src/next/evidence_ledger.zig:66` | §REF:fitting1991 |
| negative recursive SCC rejection | `src/next/provenance.zig:43` | §REF:belnap1977useful |
| contradiction isolation `T ⊔ F = B` | `formal/KernAllMath.lean:contradiction_isolation` | §REF:belnap1977useful |
| conflation involution `~~a = a` | `formal/KernAllMath.lean:conflate_involutive` | §REF:fitting1991 |
| commutativity of `⊔` | `formal/KernAllMath.lean:joinK_comm` | §REF:fitting1991 |
| associativity of `⊔` | `formal/KernAllMath.lean:joinK_assoc` | §REF:fitting1991 |
| HTTP `409 Conflict` for `B` | `README.md:123` | §REF:belnap1977useful |

## §6 What KERN does NOT have (stated honestly)

| Not implemented | Why | Recorded in |
|:--|:--|:--|
| **Trilattice `16₃`** | KERN works with B4; the third order adds nothing for contracts | §REF:shramko2011truth |
| **K3 / LP as modes** | B4 is their superset; separate modes yield no new verdicts | §REF:fitting1994 |
| **Abduction** | hypotheses are neither unique nor sound; KERN offers a read-only report only (Ф6.3) | `docs/PLAN_v2.5.3.md`, §REF:bienvenu2026abductive |
| **Modalities** (essence/accident) | no added expressiveness: `∀/∃` already exist | `docs/PLAN_v2.5.3.md`, §REF:petrukhin2026essence |
| **First-order intuitionistic BD** | KERN is a propositional SMT pipeline | §REF:niki2026firstorder |
| **Evidence retraction** as a LATTICE operation | a monotone `⊔` has no inverse; `retract` is implemented as a **recompute of the contribution set**, not as `⊔⁻¹` | §5, `evidence_ledger.zig` |
| **`trusted: 0` for Z3** | the proof checker trusts nothing, but Z3 is in the TCB | `docs/THREAT_MODEL.md` §3 |

## §7 Draft discrepancies (what verification did NOT confirm)

| Claim | Reality |
|:--|:--|
| “Arieli & Fermüller (2020), JANCL: … Thirty-Five Years Later” | **does not exist**; the closest real item is §REF:omori2017forty |
| “Jung, A. et al. (2026), Studia Logica” | §REF:jakl2025four — an arXiv preprint, **single** author, 2025 |
| “Aoyama, H. (2026)” | §REF:niki2026firstorder — the author is **Satoru Niki** |
| “Badura, J. et al. (2026)” | §REF:bienvenu2026abductive — Bienvenu, Inoue, Kozhemiachenko |
| “Rivieccio & Jansana (2024), Soft Computing 14(5)” | §REF:rivieccio2011residuated — **2011**, volume **16**(3), 493–504 |
| “Casari, Meyer, Slaney (2025), LLP 34(2): 225–252” | §REF:casari2025abelian — **Studia Logica**, DOI 10.1007/s11225-025-10208-7 |
| “Belnap 1977: Contemporary Research in Philosophical Logic, pp. 305–324” | DOI `10.1007/978-94-010-1161-7_2` is right but points to Modern Uses of Multiple-Valued Logic, pp. **5–37** |
| “Belnap 1977, pp. 30–56” (How a Computer Should Think) | catalogues say **30–55**; and it is a different work |
| “Omori & Wansing 2017, DOI …9747-2” | the real DOI is **…9748-6** |
| “Fitting, arXiv:2509.10322” | authors are **Barroso-Nascimento, Mejia**, not Fitting |
| **§REF:karpenko2010** | **unverified**: issue 16 of the journal lists a different Karpenko article; cite §REF:karpenko2017four |
| **§REF:belikov2017** | **unverified**: journal site and CyberLeninka did not confirm it |
| **§REF:fitting2026strict** | **unverified**: not found |
| **§REF:jago2026talk** | **unverified**: a talk, not indexed |

Page variants (Belnap 7–37/8–37; Ginsberg 265–315/316; Font 1–29/413–440;
Arieli 25–63) are recorded in the `note` field of the corresponding `references.bib` entries.

## §8 How to reproduce the check

```bash
make citations-check                     # keys, file:line references, theorems, statuses
python3 tools/citations_check.py --json  # machine-readable
```

Finding sources:

```
"<exact title>" + publisher   → link.springer.com / sciencedirect / OJS
api.crossref.org/works?query.bibliographic=<title+author>&rows=1
arxiv.org/abs/<id>            → preprints (check for a journal version)
```

Rule: **`verified` is set only after opening the publisher page.** A list marked
“checked” without that procedure already contained errors twice (see §7).
