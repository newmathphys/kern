#!/usr/bin/env python3
"""ФИЛЬТР НОЧНОЙ ОХОТЫ — три обязательных ворот перед публикацией находки.

ЗАЧЕМ (измерено на разборе `nightly-trophy` #46, 2026-11-24). Ночь принесла
4 «CONFIRMED», и все четыре — `ZeroDivisionError` при `period=0` в Python-пакете.
Разбор чтением показал: в файле НЕТ ни одной проверки `period`, то есть это не
противоречие внутри библиотеки, а контракт вызывающего. Мейнтейнер такой отчёт
не примет, а мы потратили окно на разбор. Ручная охота своё уже доказала
(24 репорта, 0 ложных, 3 влитых фикса в 3 независимых классах), поэтому ночной
контур должен приносить ГОТОВОЕ К ОТПРАВКЕ, а не сырьё.

ТРИ ВОРОТ (каждое отказывает С ПРИЧИНОЙ, а не молча):
  1. `is_blocked`        — репозиторий уже отрепорчен нами;
  2. `policy_verdict`    — CONTRIBUTING/SECURITY запрещают ИИ/автоматизацию;
  3. `duplicate_of`      — такой тикет/PR уже открыт (иначе дубль = минус репутация).

ПЛЮС ПРАВИЛО КЛАССА: Python div-by-zero засчитывается только при ВНУТРЕННЕМ
ПРОТИВОРЕЧИИ (`div0_has_contradiction`) — одна функция проверяет аргумент, а
соседняя в том же файле нет. Без этого — `PY_DIV0_NO_CONTRADICTION`.

ЗАПУСК:  python3 tools/hunt_filter.py --selftest
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLOCKLIST = ROOT / "tools" / "hunt_blocklist.txt"

# ЗАПРЕТЫ, которые мы уважаем. Шаблоны намеренно широкие: лучше пропустить
# репозиторий, чем получить закрытый PR с репутационным следом.
_POLICY_BAN = re.compile(
    r"(no\s+(?:ai|llm)[\s-]*(?:generated|assisted|wrote|authored)"
    r"|ai[\s-]*generated\s+\w*\s*(?:pr|pull request|issue|report|contributions?)"
    r"|(?:do not|don't|never)\s+(?:use|submit|open)\s+(?:ai|llm|automated|bot)"
    r"|automated\s+(?:pr|pull request|issue|report)s?\s+(?:are|is|will be)\s+"
    r"(?:not|closed|rejected|ignored)"
    r"|no\s+(?:automated|bot)[\s-]*(?:pr|pull request|issue|report)"
    r"|(?:reject|close|ignore)\s+(?:all\s+)?(?:ai|llm|automated)[\s-]*generated)",
    re.I)

# Внутреннее противоречие: проверка аргумента ГДЕ-ТО в файле.
_GUARD = re.compile(r"(raise\s+ValueError|period\s*<\s*1|period\s*<=\s*0"
                    r"|if\s+period\s*<\s*1|assert\s+period|period\s*>\s*0)")


def load_blocklist(path: Path = BLOCKLIST) -> dict:
    """`repo` -> причина. Формат строки: `owner/name  # причина`."""
    table = {}
    if not path.is_file():
        return table
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        repo, _, why = line.partition("#")
        repo = repo.strip().lower()
        if repo:
            table[repo] = (why.strip() or "уже отрепортчен")
    return table


def is_blocked(repo: str, table: dict) -> str:
    """Причина отказа или пустая строка. Регистр и `.git` не влияют."""
    key = repo.strip().lower().removesuffix(".git")
    if key in table:
        return table[key]
    for known, why in table.items():          # `owner/*` — вся организация
        if known.endswith("/*") and key.split("/")[0] == known[:-2]:
            return why
    return ""


def policy_verdict(text: str) -> str:
    """Причина отказа, если политика репозитория запрещает наш отчёт."""
    m = _POLICY_BAN.search(text or "")
    if not m:
        return ""
    frag = " ".join(m.group(0).split())[:90]
    return f"политика репозитория запрещает: «{frag}»"


def div0_has_contradiction(source: str) -> bool:
    """Есть ли в файле проверка аргумента, которой лишена найденная функция.

    ИЗМЕРЕНО на `atilaahmettaner/tradingview-mcp/src/.../indicators_calc.py`:
    ни `raise`, ни `period < 1` в файле нет — все четыре находки #46 не
    противоречие, а контракт вызывающего. На `ghdl`/`iio` проверка есть в
    соседних функциях, и именно это делало отчёт сильным.
    """
    return bool(_GUARD.search(source or ""))


def div0_verdict(source: str) -> str:
    """Пустая строка — находку можно нести людям; иначе код причины."""
    return "" if div0_has_contradiction(source) else "PY_DIV0_NO_CONTRADICTION"



def gh_issues(repo: str, query: str, limit: int = 20) -> list:
    """Существующие issue/PR по запросу. Бросает OSError, если `gh` недоступен."""
    import json
    import subprocess
    out = subprocess.run(
        ["gh", "issue", "list", "-R", repo, "--state", "all", "-L", str(limit),
         "--search", query, "--json", "number,title,state"],
        capture_output=True, text=True, timeout=120, check=True).stdout
    return json.loads(out or "[]")


def duplicate_of(rows: list, signature: str) -> str:
    """Причина отказа, если такой тикет уже есть. `rows` — из `gh_issues`."""
    sig = re.sub(r"\W+", " ", (signature or "").lower()).strip()
    if not sig:
        return ""
    words = [w for w in sig.split() if len(w) > 3][:4]
    for row in rows or []:
        title = re.sub(r"\W+", " ", str(row.get("title", "")).lower())
        if words and sum(1 for w in words if w in title) >= max(2, len(words) - 1):
            return f"уже открыто: #{row.get('number')} «{row.get('title')}»"
    return ""


def _selftest() -> int:
    """КАЖДЫЕ ворота проверяются ПОЛОЖИТЕЛЬНЫМ и ОТРИЦАТЕЛЬНЫМ случаем:
    ворота, которые не умеют отказать, — декорация (урок #475)."""
    bad = 0

    def ok(cond, name):
        nonlocal bad
        if not cond:
            bad += 1
            print(f"  [FAIL] {name}")

    table = {"zed-industries/zed": "PR #67346 влит",
             "ad-si/woxi": "влито dd05bc2",
             "ghdl/*": "организация: #3521 открыт"}
    ok(is_blocked("zed-industries/zed", table) != "", "blocklist: точное имя")
    ok(is_blocked("ZED-industries/Zed.git", table) != "", "blocklist: регистр и .git")
    ok(is_blocked("ghdl/ghdl", table) != "", "blocklist: шаблон owner/*")
    ok(is_blocked("randomicity/new-lib", table) == "", "blocklist: чужой репозиторий проходит")

    ok(policy_verdict("We do not accept AI-generated pull requests.") != "",
       "policy: запрет ИИ распознан")
    ok(policy_verdict("Automated PRs will be closed without review.") != "",
       "policy: запрет автоматизации распознан")
    ok(policy_verdict("Please open an issue before a PR. Tests required.") == "",
       "policy: обычный CONTRIBUTING проходит")

    # ФИКСТУРА ИЗ ЖИЗНИ (#46): ни одной проверки period в файле.
    tv = ("def calc_ema(closes, period):\n    k = 2 / (period + 1)\n"
          "    sma = sum(closes[:period]) / period\n    return sma\n")
    ok(div0_verdict(tv) == "PY_DIV0_NO_CONTRADICTION", "div0: #46 подавлен (нет противоречия)")
    # ФИКСТУРА СИЛЬНОГО ОТЧЁТА: проверка есть в соседней функции.
    strong = tv + ("\ndef calc_donchian(highs, period):\n    if period < 1:\n"
                   "        raise ValueError('period')\n")
    ok(div0_verdict(strong) == "", "div0: внутреннее противоречие пропускает находку")

    rows = [{"number": 3521, "title": "utf8 nth index panic in scan", "state": "OPEN"}]
    ok(duplicate_of(rows, "src/scan.rs utf8 nth index panic") != "", "дубли: найден #3521")
    ok(duplicate_of(rows, "alloc size overflow in render buffer") == "",
       "дубли: другая тема проходит")

    live = load_blocklist()
    ok(len(live) >= 6, f"blocklist на диске: {len(live)} записей (нужно >= 6)")
    ok(is_blocked("newmathphys/kern", live) == "", "blocklist: собственный репозиторий не в списке")
    print(f"[HUNT-FILTER-SELFTEST] точек 12 | провалов: {bad}")
    return 0 if bad == 0 else 1


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return _selftest()
    if "--list" in argv:
        for repo, why in sorted(load_blocklist().items()):
            print(f"{repo}\t{why}")
        return 0
    print("usage: hunt_filter.py --selftest | --list")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
