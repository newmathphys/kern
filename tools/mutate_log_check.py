#!/usr/bin/env python3
"""ГЕЙТ `mutate-log-check` (#487): ЛОГ МУТАЦИЙ — НЕ «МЁРТВЫЙ ТЕКСТ», А ИЗМЕРЕНИЕ.

ЗАЧЕМ. История с тремя числами (`1345` в логе, `1376` в README, `1597` в факте)
возникла ровно потому, что лог свипа никто не сверял: файл лежал, «100 %» в
README жило своей жизнью, а число САЙТОВ росло от такта к такту.

ЧТО СВЕРЯЕТСЯ (лог ↔ факт ↔ проза):
  1. лог разобран: сайты, мутанты, убитые, разбивка test/compile/timeout, RC;
  2. `facts.json["mutation_sites"]` == числу сайтов В ЛОГЕ (иначе лог неполный —
     именно так жил `1345` при факте `1597`);
  3. выживших `0` (иначе «100 %» — ложь), `RC=0`;
  4. README (RU и EN) содержит `<killed> / <killed>` и `<sites> sites`;
  5. НИ В ОДНОМ README нет ДРУГОГО числа вида `NNNN / NNNN` — иначе это ровно
     тот «второй набор чисел», который и создал расхождение.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "docs" / "evidence" / "mutate_full.log"
FACTS = ROOT / "docs" / "facts.json"
READMES = (ROOT / "README.md", ROOT / "README.ru.md")

RE_SITES = re.compile(r"найдено сайтов мутации:\s*(\d+)")
RE_TOTAL = re.compile(r"Всего мутантов:\s*(\d+)")
RE_SCORE = re.compile(r"убито\s+(\d+)\s*/\s*(\d+)")
RE_RC = re.compile(r"^RC=(\d+)$", re.M)
RE_ANY_PAIR = re.compile(r"(\d{3,5})\s*/\s*\1(?!\d)")


def parse_log(text: str) -> dict:
    """Разобрать лог свипа. Возвращает измеренные числа (-1 = не найдено)."""
    ms, mt, ms2, mr = RE_SITES.search(text), RE_TOTAL.search(text), RE_SCORE.search(text), RE_RC.search(text)
    return {
        "sites": int(ms.group(1)) if ms else -1,
        "mutants": int(mt.group(1)) if mt else -1,
        "killed": int(ms2.group(1)) if ms2 else -1,
        "compile": text.count("killed (compile)"),
        "timeout": text.count("killed (timeout)"),
        "survived": text.count("-> survived"),
        "rc": int(mr.group(1)) if mr else -1,
        "lines": len(text.splitlines()),
    }


def check(m: dict, sites_fact: int, readme_texts: dict) -> list:
    bad = []
    if m["sites"] < 0 or m["killed"] < 0:
        return ["лог не разобран: нет строк «найдено сайтов мутации» / «убито N/M»"]
    if m["sites"] != sites_fact:
        bad.append(f"ЛОГ НЕПОЛНЫЙ: сайтов в логе {m['sites']}, в facts.json {sites_fact} "
                   f"(ровно так жил 1345 при факте 1597)")
    if m["survived"] != 0:
        bad.append(f"выживших {m['survived']} — «100 %» в README было бы ложью")
    if m["rc"] != 0:
        bad.append(f"RC={m['rc']} (ожидали 0)")
    if m["killed"] != m["mutants"]:
        bad.append(f"убито {m['killed']} из {m['mutants']} мутантов — счёт неполный")
    for name, txt in readme_texts.items():
        if f"{m['killed']} / {m['killed']}" not in txt:
            bad.append(f"{name}: нет строки `{m['killed']} / {m['killed']}`")
        if f"{m['sites']} sites" not in txt and f"{m['sites']} сайт" not in txt:
            bad.append(f"{name}: нет числа сайтов {m['sites']}")
        # УЗКОЕ ПРАВИЛО (#487): «чужое число» ищем только в строке про мутации и
        # только СРЕДИ ЧИСЕЛ ТОГО ЖЕ ПОРЯДКА, что число сайтов: per-module
        # счётчики (184/184, 244/244) — законны и расхождением не являются.
        for line in txt.splitlines():
            low = line.lower()
            if not any(k in low for k in ("mutation", "мутац", "sweep", "свип")):
                continue
            pairs = {int(x) for x in RE_ANY_PAIR.findall(line)}
            big = {p for p in pairs if p != m["killed"] and p >= m["killed"] // 2}
            if big:
                bad.append(f"{name}: ДРУГОЕ число мутаций в строке про мутации: "
                           f"{sorted(big)} (в логе {m['killed']}) — обновите README")
    return bad



def _selftest() -> int:
    """Синтетика: верный набор принимается, КАЖДАЯ из 5 поломок ловится."""
    good_log = ("[i] найдено сайтов мутации: 1597; берём не более 5000\n"
                "[1/1597] a.zig [x->y] -> killed (compile) ✅\n"
                "[2/1597] b.zig [x->y] -> killed ✅\n"
                "Всего мутантов:      1597\n"
                "MUTATION SCORE (сырой):  100.0%  (убито 1597/1597)\nRC=0\n")
    good_readme = "Full sweep: **1597 / 1597 (100.0%)** over 21 files / 1597 sites"
    fails = 0

    def ck(name: str, ok: bool) -> None:
        nonlocal fails
        fails += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {name}")

    ck("верный набор принимается",
       not check(parse_log(good_log), 1597, {"R": good_readme}))
    cases = [
        ("лог неполный", good_log.replace("1597", "1345"), 1597, good_readme),
        ("есть выживший", good_log.replace("RC=0", "[9/10] c.zig -> survived\nRC=0"),
         1597, good_readme),
        ("RC != 0", good_log.replace("RC=0", "RC=2"), 1597, good_readme),
        ("README с чужим числом", good_log, 1597, good_readme + " · 1376 / 1376"),
        ("README без числа сайтов", good_log, 1597, "**1597 / 1597**"),
    ]
    for name, log, facts, readme in cases:
        ck(f"поломка «{name}» ловится", bool(check(parse_log(log), facts, {"R": readme})))
    print(f"[{'FAIL' if fails else 'OK'}] mutate-log selftest: провалов {fails}")
    return 1 if fails else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    if not LOG.exists():
        print(f"[SKIP] нет {LOG.relative_to(ROOT)} — свип ещё не прогонялся "
              f"(НАЗВАННЫЙ пропуск, не зелёный результат)")
        return 0
    m = parse_log(LOG.read_text(encoding="utf-8", errors="replace"))
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    bad = check(m, int(facts["mutation_sites"]),
                {p.name: p.read_text(encoding="utf-8", errors="replace")
                 for p in READMES if p.exists()})
    print(f"[i] #487: сайтов {m['sites']} | мутантов {m['mutants']} | убито {m['killed']} "
          f"| test {m['killed'] - m['compile'] - m['timeout']} | compile {m['compile']} "
          f"| timeout {m['timeout']} | выживших {m['survived']} | RC={m['rc']} "
          f"| строк {m['lines']}")
    for b in bad:
        print(f"[!] {b}")
    if bad:
        print(f"[FAIL] #487: нарушений {len(bad)}")
        return 1
    print("[OK] #487: лог, facts.json и README говорят ОДНО И ТО ЖЕ число")
    return 0


if __name__ == "__main__":
    sys.exit(main())
