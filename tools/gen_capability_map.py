#!/usr/bin/env python3
"""ГЕНЕРАТОР `docs/CAPABILITY_MAP` (#485): КАРТА 193 CHECK-ЦЕЛЕЙ, БЕЗ «СПИСКА ПО ПАМЯТИ».

ЗАЧЕМ ГЕНЕРАТОР, А НЕ РУЧНАЯ ТАБЛИЦА. Карта, написанная руками, устаревает на
194-й цели и начинает ЛГАТЬ — а документ, который врёт, хуже отсутствующего.
Поэтому карта ПРОИЗВОДИТСЯ из `tools/registry.py` + `tools/canfail.py`:

  * цели и их класс — `registry.CLASS` (193 CHECK);
  * доказательство «может упасть» — `registry.CASE_TARGET` (кейс -> цель);
  * какие дефекты защищаются — номера `#NNN` ИЗ ОПИСАНИЯ КЕЙСА (`canfail.CASES`),
    то есть из того же места, где живёт сам кейс, а не из прозы;
  * команда воспроизведения — `make <цель>`.

`--check` сверяет файлы с ТОЛЬКО ЧТО сгенерированным содержимым: добавили 194-ю
цель и забыли пересобрать — гейт краснеет. Это и есть «машинный паритет».
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import canfail  # noqa: E402
import registry  # noqa: E402

OUT_RU = ROOT / "docs" / "CAPABILITY_MAP.ru.md"
OUT_EN = ROOT / "docs" / "CAPABILITY_MAP.md"

# ЭШЕЛОНЫ: порядок проверки важен (первое совпадение выигрывает).
EPHELONS: list[tuple[str, str, tuple[str, ...]]] = [
    ("E1", "Формальное ядро L4 и сертификаты доказательств",
     ("smtlib", "proof", "evidence-trust", "pcc", "audits", "translator-diff",
      "arith-", "lang-", "lia-", "real-cases", "localize", "cegis", "semantic-gap",
      "polyglot", "translation-val", "adversarial", "svcomp", "theory", "check-proof")),
    ("E2", "Решётка Белнапа B4 (L3) и KERN-Next",
     ("belnap", "kernx", "mcp-selftest", "swarm")),
    ("E3", "Защита от саботажа ИИ (L5)",
     ("l5-duel", "anti-cheat", "ai-traps", "contracts-lock", "mcp-audit",
      "pytest-blind", "anti-self-deception", "hypotheses", "hook", "action-firewall",
      "guardrail", "arbitrage", "double-spend", "pricing-matrix", "ledger", "storage",
      "state-inv", "sql-policy", "rag-conflict", "rlvr", "redos", "noninterference",
      "dst-", "deal-", "evm-", "chc", "absint", "loop-check", "litmus", "ai-demo",
      "attack", "flood", "axes")),
    ("E4", "Рентген кода, CWE, точность и PR-дельта",
     ("xray", "cwe", "abi-", "audit-delta", "bounds", "div-guards", "c-types",
      "edge-cases", "codecheck", "binlevel", "clike-ir", "float-nan", "overflow",
      "string-contracts", "parser-security", "concolic", "fuzz", "bug-hunt",
      "hypotheses-corpus", "render", "svg", "html-canvas", "graph", "regex",
      "guard", "dual", "kb-", "spec", "counter")),
    ("E5", "Контейнер .kimg, крипто-аттестация и WASM (L0–L2)",
     ("verify-attestation", "wasm", "kimg", "slsa", "secrets", "tree-lock",
      "artifact", "bitrot", "disasm", "binary-audit", "foreign-verdicts", "citations",
      "attest", "audit-manifest", "audit-repo", "evidence", "capi", "ffi", "abi-test")),
    ("E6", "Ресурсная безопасность и самоконтроль контура",
     ("mem", "spawn", "mutation-lock", "temp-isolation", "docs-map", "claims",
      "metrics", "registry", "charter", "version", "changelog", "journal-parity",
      "docs-parity", "llms", "status-check", "readme", "trace-check", "scorecard",
      "theorem", "lean", "coverage", "flaky", "determinism", "os-stress", "fd-check",
      "pool", "stress", "junit", "telemetry", "self-verify", "trust-docs", "golden",
      "chaos", "injection", "cite", "pin", "lock", "guard")),
]

OVERRIDES: dict[str, str] = {
    # E1 — формальное ядро: теории, доказательства, контракты.
    **{t: "E1" for t in (
        "align", "arrays", "cert", "dtmc", "nra", "strings", "theories", "ubsafe",
        "ubsaFe", "verify", "prove", "smt", "sim", "presets-check", "gen-tests-check",
        "opt-diff-check", "oracle-dtmc-check", "oracle-string-check",
        "quixbugs-diff-check", "quixbugs-replay", "diff-equiv", "conformance-check",
        "native-theories-file-check", "native-zig-ast-check", "contracts",
        "contracts-json", "advisory-check", "deal", "hadamard-check", "dtmc-check",
    )},
    # E2 — KERN-Next и решётка Белнапа.
    **{t: "E2" for t in ("kern", "test-next")},
    # E4 — инструменты точности (мутации, фаззинг-корпуса).
    **{t: "E4" for t in ("mutate", "fuzz-1m", "bug-hunt-check")},
    # E5 — артефакты, аттестация, форматы отчётов.
    **{t: "E5" for t in ("audit", "audit-manifest", "sarif-check", "portable-bench")},
    # E6 — ресурсы и самоконтроль контура.
    **{t: "E6" for t in (
        "bench", "bench-json", "perf", "perf-check", "probe", "test", "test-fault",
        "canfail", "build", "cli-help-parity-check", "ecosystem-check", "flake-check",
        "inline-check", "homeostatic-heal-check", "simplify-check", "avalanche",
        "capability-map-check", "mutate-log-check",
    )},
}

# Цели класса CHECK, для которых кейс canfail НЕ применим ПО ДЕЛУ (и это названо,
# а не замолчано): `make test`/`build` — это сборка и прогон тестов, а не гейт с
# вердиктом «может упасть»; `kern` — корневая агрегирующая цель. Остальные 193
# обязаны иметь кейс (класс #356).
NO_CASE_OK = {"kern"}  # `test`/`build` кейсы ИМЕЮТ (проверено генератором)

RE_DEFECT = re.compile(r"#(\d+)")


def checks() -> list[str]:
    return sorted(t for t, c in registry.CLASS.items() if c == "CHECK")


def cases_of() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for case, target in registry.CASE_TARGET.items():
        out.setdefault(target, []).append(case)
    return out


def desc_of() -> dict[str, str]:
    return {row[0]: row[1] for row in canfail.CASES}


def echelon_of(target: str) -> str:
    if target in OVERRIDES:
        return OVERRIDES[target]
    for eid, _name, keys in EPHELONS:
        if any(k in target for k in keys):
            return eid
    return "E9"


def rows() -> list[dict]:
    cof, dof = cases_of(), desc_of()
    out = []
    for t in checks():
        c = sorted(cof.get(t, []))
        desc = " ".join(dof.get(x, "") for x in c)
        defects = sorted({f"#{d}" for d in RE_DEFECT.findall(desc)},
                         key=lambda s: int(s[1:]))
        out.append({"target": t, "echelon": echelon_of(t), "cases": c,
                    "defects": defects, "desc": desc.strip()})
    return out


def _fact_block() -> list[str]:
    f = json.loads((ROOT / "docs" / "facts.json").read_text(encoding="utf-8"))
    return [
        "",
        "ядро <!-- fact:core_tests -->%d · next <!-- fact:next_tests -->%d · каталог "
        "<!-- fact:catalog -->%d ·" % (f["core_tests"], f["next_tests"], f["catalog"]),
        "CHECK-цели <!-- fact:check_targets -->%d · can-fail кейсы <!-- fact:canfail_cases -->%d ·"
        % (f["check_targets"], f["canfail_cases"]),
        "якоря <!-- fact:anchors -->%d · цели реестра <!-- fact:registry_targets -->%d · "
        "META <!-- fact:meta_targets -->%d ·" % (f["anchors"], f["registry_targets"],
                                                 f["meta_targets"]),
        "теоремы Lean <!-- fact:lean_theorems -->%d · QuixBugs SMT <!-- fact:quixbugs.smt -->%d · "
        "QuixBugs differential <!-- fact:quixbugs.differential -->%d"
        % (f["lean_theorems"], f["quixbugs"]["smt"], f["quixbugs"]["differential"]),
    ]


def _table(rs: list[dict], lang: str) -> list[str]:
    by_e: dict[str, list[dict]] = {}
    for r in rs:
        by_e.setdefault(r["echelon"], []).append(r)
    hdr = ("| Цель (CHECK) | Кейс canfail | Защищает | Команда |" if lang == "ru"
           else "| Target (CHECK) | canfail case | Protects | Command |")
    L: list[str] = []
    for eid, name, _k in EPHELONS:
        g = by_e.get(eid, [])
        if not g:
            continue
        L += [f"## {eid}. {name} ({len(g)})", "", hdr, "|:--|:--|:--|:--|"]
        for r in g:
            cases = ", ".join("`" + c + "`" for c in r["cases"]) or "—"
            L.append(f"| `{r['target']}` | {cases} | "
                     f"{', '.join(r['defects']) or '—'} | `make {r['target']}` |")
        L.append("")
    if by_e.get("E9"):
        L += (["## E9. НЕ КЛАССИФИЦИРОВАНО (ошибка карты, а не цель)", "",
               "| Цель | Кейс | Команда |", "|:--|:--|:--|"] if lang == "ru"
              else ["## E9. UNCLASSIFIED (a map error, not a target)", "",
                    "| Target | Case | Command |", "|:--|:--|:--|"])
        for r in by_e["E9"]:
            L.append(f"| `{r['target']}` | {', '.join(r['cases']) or '—'} | "
                     f"`make {r['target']}` |")
        L.append("")
    return L


def _parity(rs: list[dict], lang: str) -> list[str]:
    """Блок паритета: карта обязана сходиться с реестром ЧИСЛОМ и СОСТАВОМ."""
    n_case = sum(1 for r in rs if not r["cases"] and r["target"] not in NO_CASE_OK)
    n_make = len(registry.CASE_TARGET) - len(getattr(registry, "CASE_TARGET_NON_MAKE", {}))
    if lang == "ru":
        return [
            "## Паритет с реестром", "",
            f"Целей в карте: **{len(rs)}**; класс CHECK в `registry.py`: **{len(checks())}**;",
            f"записей `CASE_TARGET`: **{len(registry.CASE_TARGET)}** "
            f"(make-исполнимых **{n_make}**); без кейса вне `NO_CASE_OK`: **{n_case}**.", "",
        ]
    return [
        "## Registry parity", "",
        f"Targets in the map: **{len(rs)}**; class CHECK in `registry.py`: **{len(checks())}**;",
        f"`CASE_TARGET` records: **{len(registry.CASE_TARGET)}** "
        f"(make-executable **{n_make}**); without a case outside `NO_CASE_OK`: **{n_case}**.", "",
    ]


def _head(lang: str) -> list[str]:
    if lang == "ru":
        return [
            "# КАРТА ВОЗМОЖНОСТЕЙ: CHECK-ЦЕЛИ И ЧТО ОНИ ЗАЩИЩАЮТ", "",
            "**Документ СГЕНЕРИРОВАН** `tools/gen_capability_map.py` из `tools/registry.py` +",
            "`tools/canfail.py`. Руками НЕ правится: `make capability-map-check` краснеет, если",
            "карта разошлась с реестром (добавили цель и забыли пересобрать — это ОШИБКА, а не",
            "мелочь: документ, который врёт, хуже отсутствующего).", "",
            "Колонки: **цель** — что запускается; **кейс canfail** — доказательство, что цель",
            "СПОСОБНА упасть (класс `#356`: цель без кейса = покрытие занижено молча);",
            "**защищает** — номера дефектов, взятые ИЗ ОПИСАНИЯ САМОГО КЕЙСА; **команда** —",
            "как воспроизвести.", "",
        ]
    return [
        "# CAPABILITY MAP: CHECK TARGETS AND WHAT THEY PROTECT", "",
        "**This document is GENERATED** by `tools/gen_capability_map.py` from",
        "`tools/registry.py` + `tools/canfail.py`. NEVER edited by hand:",
        "`make capability-map-check` reddens when the map diverges from the registry",
        "(a target added and the map not regenerated is an ERROR, not a nit: a document",
        "that lies is worse than none).", "",
        "Columns: **target** — what runs; **canfail case** — proof the target CAN go red",
        "(class `#356`: a target without a case has its coverage understated silently);",
        "**protects** — defect numbers taken FROM THE CASE DESCRIPTION ITSELF;",
        "**command** — how to reproduce.", "",
    ]


def render(rs: list[dict], lang: str) -> str:
    parts = _head(lang) + _table(rs, lang) + _parity(rs, lang) + _fact_block()
    return "\n".join(parts) + "\n"


def main() -> int:
    rs = rows()
    ru, en = render(rs, "ru"), render(rs, "en")
    if "--check" in sys.argv:
        bad = 0
        for path, want, label in ((OUT_RU, ru, "RU"), (OUT_EN, en, "EN")):
            if not path.exists():
                print(f"[FAIL] нет {path.relative_to(ROOT)} — соберите: make capability-map")
                bad += 1
            elif path.read_text(encoding="utf-8") != want:
                print(f"[FAIL] {label}: карта РАСХОДИТСЯ с реестром — "
                      f"пересоберите: make capability-map")
                bad += 1
        uncl = [r["target"] for r in rs if r["echelon"] == "E9"]
        if uncl:
            print(f"[FAIL] не классифицировано: {len(uncl)} — {uncl[:8]}")
            bad += 1
        nocase = [r["target"] for r in rs if not r["cases"] and r["target"] not in NO_CASE_OK]
        if nocase:
            print(f"[FAIL] целей БЕЗ кейса canfail (класс #356): {len(nocase)} — {nocase[:8]}")
            bad += 1
        if bad:
            print(f"[FAIL] #485: нарушений {bad}")
            return 1
        print(f"[OK] #485: карта == реестр ({len(rs)} CHECK, "
              f"{len(registry.CASE_TARGET)} кейсов, 0 неклассифицированных, 0 без кейса)")
        return 0
    OUT_RU.write_text(ru, encoding="utf-8")
    OUT_EN.write_text(en, encoding="utf-8")
    uncl = [r["target"] for r in rs if r["echelon"] == "E9"]
    print(f"[OK] #485: записано {OUT_RU.name} и {OUT_EN.name}; целей {len(rs)}, "
          f"неклассифицированных {len(uncl)}")
    if uncl:
        print(f"[!] добавьте в EPHELONS/OVERRIDES: {uncl}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
