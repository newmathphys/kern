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

ПОДКЛЮЧЕНИЕ (MCP-клиенты):
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


def _bootstrap_env() -> list[str]:
    """Дополняет PATH путями к z3/kernc и возвращает список ОТСУТСТВУЮЩИХ.

    ЗАЧЕМ (Дефект #154, класс #110): без `z3` в PATH SMT-контракты честно
    возвращают `N` (e=0), и тест падал «10 провалов», хотя регрессии нет.
    Теперь путь ищется сам (venv -> ~/.local/bin -> /usr/*), а если решателя
    действительно нет — это НАЗЫВАЕТСЯ, а не выглядит как поломка.
    """
    import shutil
    parts = os.environ.get("PATH", "").split(os.pathsep)
    for cand in (Path.home() / "ai_lab" / ".venv" / "bin",
                 Path.home() / ".venv" / "bin",
                 ROOT / ".venv" / "bin",
                 Path.home() / ".local" / "bin",
                 Path("/usr/local/bin"), Path("/usr/bin")):
        if cand.is_dir() and str(cand) not in parts:
            parts.append(str(cand))
    os.environ["PATH"] = os.pathsep.join(parts)
    missing: list[str] = []
    if shutil.which("z3") is None:
        missing.append("z3")
    if not Path(KERNC).exists():
        missing.append("kernc")
    return missing
PROTOCOL = "2024-11-05"
SERVER_INFO = {"name": "kern", "version": "2.5.1"}

TOOLS = [
    {
        "name": "kern_verify_smt",
        "description": ("Verify an SMT-LIB2 contract with KERN: an external Z3 "
                        "run plus an independent proof-DAG checker. Returns the "
                        "verdict (proven / not proven) and a checker summary."),
        "inputSchema": {
            "type": "object",
            "properties": {"smt": {"type": "string",
                                   "description": "SMT-LIB2 contract text"}},
            "required": ["smt"],
        },
    },
    {
        "name": "kern_prove_with_checker",
        "description": ("Same as kern_verify_smt, but returns the FULL proof-checker "
                        "breakdown: how many Z3 proof steps were re-checked "
                        "independently and how many were left trusted."),
        "inputSchema": {
            "type": "object",
            "properties": {"smt": {"type": "string"}},
            "required": ["smt"],
        },
    },
    {
        "name": "kern_verify_multi_belnap",
        "description": ("Verify MULTIPLE contracts and join the verdicts in Belnap "
                        "B4 (T/F/B/N). A conflict (T and F together) yields B: "
                        "the contradiction is never collapsed into a proof."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "contracts": {"type": "array", "items": {"type": "string"},
                              "description": "List of SMT-LIB2 contracts"},
            },
            "required": ["contracts"],
        },
    },
    {
        "name": "kern_verify_python",
        "description": ("Verify Python code carrying contracts in comments "
                        "(`# @kern:requires` / `# @kern:ensures`). Branches "
                        "if/elif/else and local assignments are supported: they "
                        "are translated into SMT `ite`. For each function the "
                        "status (PASS/FAIL/SKIP), the Belnap verdict and a "
                        "COUNTEREXAMPLE on violation are returned. Loops and "
                        "calls yield an honest SKIP."),
        "inputSchema": {
            "type": "object",
            "properties": {"python_source": {
                "type": "string",
                "description": "Python source carrying @kern: annotations"}},
            "required": ["python_source"],
        },
    },
    {
        "name": "kern_check_equivalence",
        "description": ("Prove refactoring EQUIVALENCE without writing any "
                        "contracts: for same-named functions of two sources it "
                        "checks `∃x: f_old(x) != f_new(x)`. UNSAT -> "
                        "[EQUIVALENT] (behaviour unchanged), SAT -> "
                        "[DIVERGED] plus a COUNTEREXAMPLE where the old and new "
                        "functions disagree. Loops/calls yield an honest SKIP."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "old_source": {"type": "string",
                               "description": "Source BEFORE the refactoring"},
                "new_source": {"type": "string",
                               "description": "Source AFTER the refactoring"}},
            "required": ["old_source", "new_source"],
        },
    },
    {
        "name": "kern_xray_code",
        "description": (
            "ZERO-ANNOTATION code X-ray: dead branches "
            "[DEAD BRANCH] (UNSAT), redundant guards [REDUNDANT GUARD], "
            "crash paths [CRASH PATH] (division by zero, overflow) and McCabe "
            "complexity. Works with no @kern: annotation at all."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string",
                           "description": "Source file (.py, .zig, .c, .rs, .ts, .js, .go)"},
                "filename": {"type": "string", "description": "file name (default x.py)"}},
            "required": ["source"],
        },
    },
    {
        "name": "kern_verify_action",
        "description": (
            "FinOps / Action Firewall: evaluates an agent's JSON tool call "
            "against a policy BEFORE execution. T -> 200, F -> 422 (with a "
            "counterexample), B -> 409 (the policies contradict each other)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "object", "description": "{tool, args}"},
                "policy": {"type": "object", "description": "{allow, forbid[]}"}},
            "required": ["action", "policy"],
        },
    },
    {
        "name": "kern_rlvr_reward",
        "description": (
            "RLVR reward oracle: +1.0 for a PROVEN contract (trusted: 0), "
            "-1.0 for a counterexample, -2.0 for reward hacking, "
            "0.0 when abstaining (outside the supported fragment)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Candidate source (.py)"}},
            "required": ["source"],
        },
    },
]

# ============================================================================
# MCP Tool Annotations (MCP 2025/2026). Внешние каталоги (m8ven.ai, Smithery,
# Glama, Official MCP Registry) читают ИМЕННО `annotations`, а не только имя:
# без них поверхность инструментов помечается как «unread».
#
# Все 8 инструментов KERN работают локально и не имеют побочных эффектов:
#   * readOnlyHint   — ничего не изменяют (только читают файлы/код);
#   * destructiveHint — не удаляют и не перезаписывают данные;
#   * idempotentHint — повторный вызов с теми же аргументами даёт тот же ответ;
#   * openWorldHint  — не ходят в сеть (Z3/kernc запускаются локально).
#
# `title` — короткое АНГЛИЙСКОЕ имя для каталогов; `description` остаётся
# источником истины в TOOLS (не дублируем текст, только отображаемое имя).
# ============================================================================
_TOOL_TITLES = {
    "kern_verify_smt": "Verify an SMT-LIB2 contract",
    "kern_prove_with_checker": "Prove and machine-check a proof DAG",
    "kern_verify_multi_belnap": "Verify several claims in Belnap B4",
    "kern_verify_python": "Verify Python contracts (@kern: annotations)",
    "kern_check_equivalence": "Prove two functions equivalent (refactoring)",
    "kern_xray_code": "Zero-annotation X-ray of any code file",
    "kern_verify_action": "Verify an AI agent action against policy",
    "kern_rlvr_reward": "Verifiable reward for generated code (RLVR)",
}

for _t in TOOLS:
    _ann = _t.setdefault("annotations", {})
    _ann["title"] = _TOOL_TITLES[_t["name"]]
    _ann["readOnlyHint"] = True
    _ann["destructiveHint"] = False
    _ann["idempotentHint"] = True
    _ann["openWorldHint"] = False




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
                or t.startswith("[VACUOUS]") or t.startswith("[IMPURE]")
                or t.startswith("[КОНТРПРИМЕР]") or t.startswith("[RUNTIME CONFIRMED]")
                or t.startswith("ИТОГО:")
                or "SKIP —" in t or "ДЕЛЕНИЕ НА НОЛЬ" in t or "ПЕРЕПОЛНЕНИЕ" in t
                or "RUNTIME НЕ подтвердил" in t):
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
    if name in ("kern_xray_code", "kern_rlvr_reward", "kern_verify_action"):
        import tempfile
        ex = ROOT / "tools" / "kern_contracts.py"
        with tempfile.TemporaryDirectory() as td:
            if name == "kern_xray_code":
                src = args.get("source", "")
                if not src.strip():
                    return text_result("нужен непустой 'source'", True)
                f = Path(td) / (args.get("filename") or "x.py")
                f.write_text(src, encoding="utf-8")
                argv = [str(f), "--xray", str(f)]
            elif name == "kern_rlvr_reward":
                src = args.get("source", "")
                if not src.strip():
                    return text_result("нужен непустой 'source'", True)
                f = Path(td) / "candidate.py"
                f.write_text(src, encoding="utf-8")
                argv = ["--rlvr-reward", str(f)]
            else:
                act = args.get("action") or {}
                pol = args.get("policy") or {}
                if not isinstance(act, dict) or not isinstance(pol, dict):
                    return text_result("нужны объекты 'action' и 'policy'", True)
                af = Path(td) / "action.json"
                pf = Path(td) / "policy.json"
                af.write_text(json.dumps(act), encoding="utf-8")
                pf.write_text(json.dumps(pol), encoding="utf-8")
                argv = ["--verify-action", str(af), str(pf)]
            r = subprocess.run([sys.executable, str(ex), *argv],
                               capture_output=True, text=True, timeout=300)
            out = ((r.stdout or "") + (r.stderr or "")).strip()
            return text_result(out or "(пустой вывод)", r.returncode not in (0, 1))

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
    # сервер тоже обязан видеть z3: иначе ЛЮБОЙ клиент получит N (Дефект #154)
    _bootstrap_env()
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
