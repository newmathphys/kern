# Bounded intuitionistic mode: what the sources actually say (design note)

> Status: **DESIGN ONLY, NOT IMPLEMENTED.** Phase 6.2 stays in the backlog
> (`docs/PLAN_v2.5.3.md` §15). This note records what was read, what a bounded
> encoding would mean, and why implementing it today would produce a result that
> looks stronger than it is.

## 1. What was read (and where)

| Source | Read | What it contains |
|---|---|---|
| Niki & Omori, *Kamide is in America, Moisil and Leitgeb are in Australia* (arXiv:2501.00495) | **partial** — abstract, §2.2 Def. 5, axiom list, completeness remark | Two semantics for BD+: a **star-model** `<W, *, D, V>` with `w** = w` and `I(w, ~A) = 1 iff I(w*, A) != 1`, where `→` is still classical at a state (`I(w, A→B) = 1 iff I(w,A) != 1 or I(w,B) = 1`); and a **monotone** semantics (`x >= w` preserves predicate extensions) used for the intuitionistic `BDi` / `QDN4` side. |
| Niki, *Intuitionistic views on connexive constructible falsity* (IfCoLog, DOI 10.13154/294-12564) | **partial** — abstract | Compares “negation as implication to absurdity” with a primitive **constructible falsity** (Nelson), and studies interactions inside Wansing’s connexive framework, proof-theoretically and semantically. |
| Niki, *Investigations into intuitionistic and other negations* (dissertation, RUB) | **metadata only** (DOI 10.1017/bsl.2022.29) | Labelled sequent calculi, cut elimination, semantics for intuitionistic negation. |
| Kamide & Niki, *First-order intuitionistic BD* (IGPL, DOI 10.1093/jigpal/jzag024) | **not available** (`read = {false}`) | The article KERN would cite for `--worlds N`. Its subject is the Gentzen calculus `sQBDi`. |

## 2. Why “`--intuitionistic --worlds N`” is not a small feature

1. **The contract language has no logical connectives to interpret.** `@kern:requires`/`ensures` accept arithmetic comparisons joined by `and`. There is no `->`, no `not` over formulas, no `or` at the formula level. Intuitionistic and classical semantics coincide on such atoms, so a worlds-based encoding would change **no verdict on any real contract** — while adding a large amount of machinery.
2. **Bounded unfolding cannot produce `T`.** A preorder is reflexive and transitive; its transitive closure is not first-order definable, so it must be unrolled to depth `N`. UNSAT at depth `N` proves validity **up to `N`**, not validity. Reporting that as `T` is exactly the class of claim this project removed (see `31/31`, `33/40` without qualifiers).
3. **The star-model is not monotone.** In the `BD+` star semantics there is no `>=` relation to unroll at all: `~` is evaluated at `w*`. Unrolling it would be a different (and unmotivated) construction.

## 3. What would make it meaningful (prerequisites, in order)

1. Extend the contract grammar with `->`, `not`, `or` **at the formula level** and define their SMT encoding (today only `and` exists).
2. Define the verdict carrier: `CoverageState.bounded(bound = N)` — never `T`; `--worlds 0` is rejected; the reported result carries `bound`.
3. Prove monotonicity of the encoding on a hand-checked micro-corpus (three formulas whose classical and intuitionistic readings differ), and record the counterexample that separates them.
4. Only then implement, with a can-fail case that turns a **classical** validator red on an intuitionistically invalid formula.

## 4. Decision

Phase 6.2 remains in the backlog. The blocker is no longer “no text”: the sources are readable and are cited here. The blocker is that the feature has **no observable effect** in the current contract language, and that its output would have to be `bounded` — a fact worth recording rather than a reason to build a mode that cannot be trusted as a proof.
