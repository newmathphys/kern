#!/usr/bin/env python3
"""KERN MCP-сервер (Улучшение №4): доступ к Вратам Истины из ИИ-агентов.

ПРОТОКОЛ. MCP (Model Context Protocol) — JSON-RPC 2.0 поверх stdio, сообщения
разделены переводами строк. Никаких зависимостей: только stdlib.

ЧТО ЭКСПОРТИРУЕТ (3 инструмента):
  kern_verify_smt           — проверить SMT-LIB2 контракт через Z3 + пруф-чекер;
  kern_prove_with_checker   — то же, но с ПОЛНОЙ разбивкой пруф-чекера;
  kern_verify_multi_belnap  — несколько контрактов -> аккумуляция Белнапа
                              (конфликт T+F не схлопывается в «доказано»);
  kern_verify_python        — контракты ПРЯМО В Python-КОДЕ (@kern:requires /
                              @kern:ensures), с контрпримером при нарушении;
  kern_check_equivalence    — доказать ЭКВИВАЛЕНТНОСТЬ рефакторинга БЕЗ
                              контрактов: `∃x: f_old(x) != f_new(x)` -> UNSAT
                              = [EQUIVALENT], SAT = [DIVERGED] + контрпример.
                              (T / F / B / N): T ⊔ F = B (конфликт).

ПОДКЛЮЧЕНИЕ (Claude Code / Cursor):
    {"mcpServers": {"kern": {"command": "python3",
      "args": ["/path/to/kern/examples/kern_mcp_server.py"]}}}

ПОЧЕМУ ЧЕРЕЗ CLI, А НЕ libkern.so. CLI печатает сводку пруф-чекера
(`[PROOF VERIFIED] ... trusted: N`); через C-ABI её пришлось бы дублировать.

Проверка: python3 tools/mcp_selftest.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = os.environ.get("KERNC", str(ROOT / "zig-out" / "bin" / "kernc"))
PROTOCOL = "2024-11-05"
SERVER_INFO = {"name": "kern", "version": "2.2.0"}

TOOLS = [
    {
        "name": "kern_verify_smt",
        "description": ("Проверить SMT-LIB2 контракт через KERN: внешний Z3 "
                        "плюс независимый пруф-чекер. Возвращает вердикт "
                        "(ДОКАЗАНО / НЕ доказано) и сводку проверки вывода."),
        "inputSchema": {
            "type": "object",
            "properties": {"smt": {"type": "string",
                                   "description": "Текст контракта в SMT-LIB2"}},
            "required": ["smt"],
        },
    },
    {
        "name": "kern_prove_with_checker",
        "description": ("То же, что kern_verify_smt, но возвращает ПОЛНУЮ "
                        "разбивку пруф-чекера: сколько шагов вывода Z3 "
                        "перепроверено независимо и сколько осталось "
                        "доверенными (trusted)."),
        "inputSchema": {
            "type": "object",
            "properties": {"smt": {"type": "string"}},
            "required": ["smt"],
        },
    },
    {
        "name": "kern_verify_multi_belnap",
        "description": ("Проверить НЕСКОЛЬКО контрактов и сложить вердикты по "
                        "Белнапу (T/F/B/N). Конфликт (T и F вместе) даёт B — "
                        "противоречие НЕ схлопывается в пользу доказательства."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "contracts": {"type": "array", "items": {"type": "string"},
                              "description": "Список контрактов SMT-LIB2"},
            },
            "required": ["contracts"],
        },
    },
    {
        "name": "kern_verify_python",
        "description": ("Проверить Python-код с контрактами в комментариях "
                        "(`# @kern:requires` / `# @kern:ensures`). Поддерживаются "
                        "ветвления if/elif/else и локальные присваивания: они "
                        "транслируются в SMT `ite`. Для каждой функции возвращается "
                        "статус (PASS/FAIL/SKIP), вердикт Белнапа и КОНТРПРИМЕР при "
                        "нарушении контракта. Циклы и вызовы -> честный SKIP."),
        "inputSchema": {
            "type": "object",
            "properties": {"python_source": {
                "type": "string",
                "description": "Исходник Python с аннотациями @kern:"}},
            "required": ["python_source"],
        },
    },
    {
        "name": "kern_check_equivalence",
        "description": ("Доказать ЭКВИВАЛЕНТНОСТЬ рефакторинга БЕЗ написания "
                        "контрактов: для одноимённых функций двух исходников "
                        "проверяется `∃x: f_old(x) != f_new(x)`. UNSAT -> "
                        "[EQUIVALENT] (поведение не изменилось), SAT -> "
                        "[DIVERGED] + КОНТРПРИМЕР, на котором старая и новая "
                        "функции дают РАЗНЫЙ ответ. Циклы/вызовы -> честный SKIP."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "old_source": {"type": "string",
                               "description": "Исходник ДО рефакторинга"},
                "new_source": {"type": "string",
                               "description": "Исходник ПОСЛЕ рефакторинга"}},
            "required": ["old_source", "new_source"],
        },
    },
]


def run_prove(smt: str) -> dict:
    """Прогнать контракт через `kernc prove` и вернуть СТРУКТУРНЫЙ результат.

    Разбираются только строки фиксированного формата, которые печатает CLI:
    `e        : 1`, `ВЕРДИКТ  : ...`, `[PROOF VERIFIED] ...`, `KERN-EQ2 : X`.
    Свободный текст не угадывается.
    """
    if not Path(KERNC).exists():
        return {"error": f"kernc не найден: {KERNC}"}
    with tempfile.NamedTemporaryFile("w", suffix=".smt2", delete=False) as tf:
        tf.write(smt)
        path = tf.name
    try:
        r = subprocess.run([KERNC, "prove", path], capture_output=True,
                           text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return {"verdict": "timeout", "e": 0, "belnap": "N", "proof": None}
    out = r.stdout + r.stderr
    res = {"rc": r.returncode, "e": 0, "verdict": "НЕ доказано",
           "proof": None, "belnap": "N", "counterexample": None}
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("e ") and ":" in s:
            try:
                res["e"] = int(s.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif s.startswith("ВЕРДИКТ"):
            res["verdict"] = s.split(":", 1)[1].strip()
        elif "PROOF VERIFIED" in s:
            res["proof"] = s
        elif "[КОНТРПРИМЕР]" in s:
            # Конкретные значения, сломавшие контракт (модель Z3).
            res["counterexample"] = s.split("]", 1)[1].strip()
        elif "KERN-EQ2" in s:
            sym = s.split(":")[-1].strip()
            if sym in ("T", "F", "B", "N"):
                res["belnap"] = sym
    if res["e"] == 1:
        res["belnap"] = "T"
    return res


def run_python_contracts(src: str) -> str:
    """Проверить Python-исходник с аннотациями `# @kern:` через экстрактор контрактов.

    Переиспользуется `tools/kern_contracts.py` (тот же код, что в `make contracts`):
    дублировать трансляцию Python -> SMT здесь нельзя — разошлись бы версии.
    """
    tool = ROOT / "tools" / "kern_contracts.py"
    if not tool.exists():
        return f"[!] не найден экстрактор контрактов: {tool}"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
        tf.write(src)
        path = tf.name
    try:
        r = subprocess.run([sys.executable, str(tool), path],
                           capture_output=True, text=True, timeout=300,
                           cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        return "[!] таймаут проверки контрактов"
    out = (r.stdout + r.stderr).strip()
    # Возвращаем структурный итог: строки вердиктов + контрпримеры.
    keep = []
    for line in out.splitlines():
        t = line.strip()
        if (t.startswith("[PASS]") or t.startswith("[FAIL]") or t.startswith("[SKIP]")
                or t.startswith("[КОНТРПРИМЕР]") or t.startswith("ИТОГО:")
                or "SKIP —" in t):
            keep.append(t)
    return "\n".join(keep) if keep else out


def run_diff_equiv(old_src: str, new_src: str) -> str:
    """Доказать эквивалентность рефакторинга (УЛУЧШЕНИЕ №3) через тот же
    `tools/kern_contracts.py` — версии трансляции Python -> SMT не расходятся.
    """
    tool = ROOT / "tools" / "kern_contracts.py"
    if not tool.exists():
        return f"[!] не найден экстрактор контрактов: {tool}"
    paths = []
    try:
        for src in (old_src, new_src):
            with tempfile.NamedTemporaryFile("w", suffix=".py",
                                             delete=False) as tf:
                tf.write(src)
                paths.append(tf.name)
        r = subprocess.run([sys.executable, str(tool), "--diff-equiv",
                            paths[0], paths[1]],
                           capture_output=True, text=True, timeout=300,
                           cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        return "[!] таймаут проверки эквивалентности"
    return (r.stdout + r.stderr).strip()


def text_result(s: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": s}], "isError": is_error}


def call_tool(name: str, args: dict) -> dict:
    if name in ("kern_verify_smt", "kern_prove_with_checker"):
        smt = args.get("smt", "")
        if not smt.strip():
            return text_result("нужен непустой параметр 'smt'", True)
        r = run_prove(smt)
        if "error" in r:
            return text_result(r["error"], True)
        lines = [f"вердикт : {r['verdict']}",
                 f"e       : {r['e']}",
                 f"Белнап  : {r['belnap']}"]
        if r["proof"]:
            lines.append(f"вывод   : {r['proof']}")
        elif name == "kern_prove_with_checker":
            lines.append("пруф-чекер: сводка недоступна (вывод не получен)")
        # КОНТРПРИМЕР: при опровергнутом контракте агент получает КОНКРЕТНЫЕ
        # значения входов — их можно сразу подать модели для исправления.
        if r.get("counterexample"):
            lines.append(f"counterexample: {r['counterexample']}")
        return text_result("\n".join(lines))

    if name == "kern_verify_python":
        src = args.get("python_source", "")
        if not src.strip():
            return text_result("нужен непустой параметр 'python_source'", True)
        return text_result(run_python_contracts(src))

    if name == "kern_check_equivalence":
        old_src = args.get("old_source", "")
        new_src = args.get("new_source", "")
        if not old_src.strip() or not new_src.strip():
            return text_result("нужны непустые 'old_source' и 'new_source'", True)
        return text_result(run_diff_equiv(old_src, new_src))

    if name == "kern_verify_multi_belnap":
        contracts = args.get("contracts") or []
        if not isinstance(contracts, list) or not contracts:
            return text_result("нужен непустой список 'contracts'", True)
        p = n = 0
        rows = []
        for i, c in enumerate(contracts):
            r = run_prove(c)
            if "error" in r:
                return text_result(r["error"], True)
            rows.append(f"  #{i}: {r['belnap']} ({r['verdict']})")
            if r["belnap"] == "T":
                p = 1
            elif r["belnap"] == "F":
                n = 1
        # JOIN_K: (p, n) -> T / F / B / N. Конфликт НЕ схлопывается.
        state = "B" if (p and n) else ("T" if p else ("F" if n else "N"))
        head = f"Белнап (JOIN_K): {state}   p={p} n={n}"
        extra = ("  ВНИМАНИЕ: T и F вместе = КОНФЛИКТ (B); "
                 "доказательство НЕ выдаётся") if state == "B" else ""
        return text_result("\n".join([head] + rows + ([extra] if extra else [])))

    return text_result(f"неизвестный инструмент: {name}", True)


def handle(msg: dict):
    """Вернуть ответ или None для уведомления."""
    method = msg.get("method")
    mid = msg.get("id")
    if mid is None:
        return None  # уведомление — ответа не требуется
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params") or {}
        res = call_tool(params.get("name", ""), params.get("arguments") or {})
        return {"jsonrpc": "2.0", "id": mid, "result": res}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def main() -> int:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as e:
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": f"parse error: {e}"}}) + "\n")
            sys.stdout.flush()
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
