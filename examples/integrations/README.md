# KERN integrations (AI agents and frameworks)

Everything here is built on **one verified function** — `kern_guard.verify_files()` — which
shells out to `tools/kern_contracts.py` and returns a machine-readable verdict:

```json
{"ok": false, "proven": 4, "violated": 2, "vacuous": 1,
 "functions": [{"name": "withdraw_missing_neg", "verdict": "violated",
                "counterexample": "balance = 0, amount = -1, result = 1",
                "runtime_confirmed": true}]}
```

| File | Status | Needs |
|:--|:--|:--|
| `kern_guard.py` | **VERIFIED** — stdlib only; run it and see | `kernc` built, `z3` in `PATH` |
| `langchain_tool.py` | glue (unverified here — no LangChain installed) | `pip install langchain-core` |
| `crewai_tool.py` | glue (unverified here — no CrewAI installed) | `pip install crewai` |
| `agent_loop.py` | **VERIFIED** — framework-agnostic gate you can drop into any agent loop | nothing extra |

## Run the verified parts

```bash
python3 examples/integrations/kern_guard.py examples/contracts_demo.py   # JSON verdict, rc=1 if the gate closes
python3 examples/integrations/agent_loop.py                              # demo: an agent proposes code, KERN refuses it
```

## Gate any agent that commits

You do not need a framework wrapper for this — use KERN's own hook, which is
framework-independent and blocks `git commit` when a contract is refuted or a sealed
contract was weakened:

```bash
python3 tools/kern_contracts.py --install-hook      # writes .git/hooks/pre-commit
python3 tools/kern_contracts.py --git-diff          # check only what this commit touches
```

The hook returns `rc = 2` on a violated/removed contract, so an agent physically cannot
commit broken code — no matter which tool produced it.

## The contract you should put in an agent's system prompt

> Before you claim a function is correct, run KERN on it. If `kern_guard.verify_files()`
> returns `ok: false`, the code is **not** correct: fix it, or fix the contract — never
> delete or weaken an `@kern:ensures` line (the lock in `docs/contracts.lock.json` will
> catch that, and it is a hard error).
