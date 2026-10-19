#!/usr/bin/env python3
"""KERN: живая проверка MCP-сервера (JSON-RPC 2.0 поверх stdio).

Запускает `examples/kern_mcp_server.py` как ДОЧЕРНИЙ ПРОЦЕСС и общается с ним
точно так же, как реальный клиент (Claude Code, Cursor): пишет строки JSON в
stdin, читает строки JSON из stdout.

ПРОВЕРЯЕТСЯ (14 пунктов):
  1. `initialize`      — протокол и serverInfo;
  2. уведомление (без `id`) — ответа быть НЕ ДОЛЖНО;
  3. `tools/list`      — ПЯТЬ инструментов;
  4. `kern_verify_smt` на ДОКАЗУЕМОМ контракте -> «ДОКАЗАНО», e=1;
  5. `kern_verify_smt` на ОПРОВЕРГАЕМОМ -> «НЕ доказано», e=0;
  6. `kern_prove_with_checker` -> есть строка `PROOF VERIFIED`;
  7. `kern_verify_multi_belnap` [T, F] -> `JOIN_K: B` (конфликт не схлопывается);
  7b. kern_verify_python (ветвления -> ite) -> контрпример;
  7c. `kern_check_equivalence`: эквивалентный рефакторинг -> `[EQUIVALENT]`,
      расходящийся -> `[DIVERGED]` + контрпример (УЛУЧШЕНИЕ №3);
  8. неизвестный метод -> -32601; битый JSON -> -32700.

Запуск: python3 tools/mcp_selftest.py
"""
from __future__ import annotations

import json
import select
import subprocess
import sys
import time
from pathlib import Path


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
    if not (ROOT / "zig-out" / "bin" / "kernc").exists():
        missing.append("kernc")
    return missing

import os

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "examples" / "kern_mcp_server.py"

PROVABLE = ("(set-logic ALL)\n(declare-const x Int)\n"
            "(assert (and (> x 10) (< x 5)))\n(check-sat)\n")
REFUTABLE = ("(set-logic ALL)\n(declare-const x Int)\n"
             "(assert (> x 0))\n(check-sat)\n")


class Client:
    def __init__(self, proc):
        self.p = proc
        self.buf = b""

    def send(self, obj):
        self.p.stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode())
        self.p.stdin.flush()

    def read_one(self, timeout=180.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                if line.strip():
                    return json.loads(line.decode())
                continue
            r, _, _ = select.select([self.p.stdout], [], [], 0.5)
            if r:
                chunk = self.p.stdout.readline()
                if not chunk:
                    return None
                self.buf += chunk
        return None

    def no_response(self, timeout=3.0):
        """True, если за `timeout` секунд ответа НЕ пришло."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            r, _, _ = select.select([self.p.stdout], [], [], 0.3)
            if r:
                if self.p.stdout.readline():
                    return False
        return True


def main() -> int:
    missing = _bootstrap_env()
    if missing:
        # НАЗЫВАЕМ, а не маскируем: без решателя SMT-контракты дают `N` (e=0).
        print(f"[!] не найдено: {', '.join(missing)} -> SMT-проверки вернут N "
              f"(это НЕ регрессия, см. Дефект #110/#154)")
    if not SERVER.exists():
        print(f"[!] нет сервера: {SERVER}")
        return 1
    proc = subprocess.Popen([sys.executable, str(SERVER)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    c = Client(proc)
    fails = []
    print("=" * 74)
    print("KERN MCP: живая проверка протокола (stdio, JSON-RPC 2.0)")
    print("=" * 74)

    def check(name, cond, detail=""):
        print(f"  {'[OK]  ' if cond else '[FAIL]'} {name}"
              + (f"  {detail}" if detail else ""))
        if not cond:
            fails.append(name)

    # 1. initialize
    c.send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "selftest", "version": "1"}}})
    r = c.read_one()
    ok = bool(r and r.get("id") == 1
              and r["result"]["protocolVersion"] == "2024-11-05"
              and r["result"]["serverInfo"]["name"] == "kern")
    check("initialize", ok,
          f"protocol={r['result']['protocolVersion'] if ok else '?'} "
          f"server={r['result']['serverInfo']['name'] if ok else '?'}")

    # 2. уведомление -> ответа быть не должно
    c.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    check("уведомление не даёт ответа", c.no_response())

    # 3. tools/list
    c.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    r = c.read_one()
    names = [t["name"] for t in r["result"]["tools"]] if r else []
    check("tools/list (8 инструментов)",
          len(names) == 8 and "kern_check_equivalence" in names
          and "kern_xray_code" in names and "kern_verify_action" in names
          and "kern_rlvr_reward" in names,
          ", ".join(names))

    # 4. доказуемый контракт
    c.send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "kern_verify_smt",
                       "arguments": {"smt": PROVABLE}}})
    r = c.read_one()
    txt = r["result"]["content"][0]["text"] if r else ""
    check("kern_verify_smt (доказуемый)",
          "ДОКАЗАНО" in txt and "e       : 1" in txt,
          txt.splitlines()[0] if txt else "")

    # 5. опровергаемый контракт
    c.send({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "kern_verify_smt",
                       "arguments": {"smt": REFUTABLE}}})
    r = c.read_one()
    txt = r["result"]["content"][0]["text"] if r else ""
    check("kern_verify_smt (опровергаемый)",
          "НЕ доказано" in txt and "e       : 0" in txt,
          txt.splitlines()[0] if txt else "")

    # 6. полная разбивка пруф-чекера
    c.send({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "kern_prove_with_checker",
                       "arguments": {"smt": PROVABLE}}})
    r = c.read_one()
    txt = r["result"]["content"][0]["text"] if r else ""
    line = ([l for l in txt.splitlines() if "PROOF VERIFIED" in l] or [""])[0]
    check("kern_prove_with_checker", "PROOF VERIFIED" in txt, line)

    # 7. Белнап-конфликт: T + F -> B
    #    ВНИМАНИЕ: CLI печатает "JOIN_K): B" (закрывающая скобка перед ':').
    #    Проверяем по существу: состояние B и оба канала поддержки p=1 n=1.
    c.send({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"name": "kern_verify_multi_belnap",
                       "arguments": {"contracts": [PROVABLE, REFUTABLE]}}})
    r = c.read_one()
    txt = r["result"]["content"][0]["text"] if r else ""
    first = txt.splitlines()[0] if txt else ""
    check("Белнап: T ⊔ F = B (конфликт)",
          "JOIN_K" in txt and "B" in first and "p=1" in first and "n=1" in first,
          first)

    # 7b. Python-контракты: ветвления -> SMT ite, контрпример при баге.
    PY = ("# @kern:requires True\n"
          "# @kern:ensures  result <= balance\n"
          "def withdraw_missing_neg(balance: int, amount: int) -> int:\n"
          "    if amount > balance:\n"
          "        return balance\n"
          "    return balance - amount\n")
    c.send({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
            "params": {"name": "kern_verify_python",
                       "arguments": {"python_source": PY}}})
    r = c.read_one(timeout=300)
    txt = r["result"]["content"][0]["text"] if r else ""
    ok = ("[FAIL] withdraw_missing_neg" in txt and "КОНТРПРИМЕР" in txt
          and "amount = -1" in txt)
    check("kern_verify_python: ветвления + контрпример", ok,
          ([l for l in txt.splitlines() if "КОНТРПРИМЕР" in l] or [""])[0])

    # 7b-2. ВАКУУМНОЕ ПРЕДУСЛОВИЕ через MCP (УЛУЧШЕНИЕ №1).
    PY_VAC = ("# @kern:requires x > 10 and x < 5\n"
              "# @kern:ensures  result == x\n"
              "def broken(x: int) -> int:\n"
              "    return x + 1\n")
    c.send({"jsonrpc": "2.0", "id": 11, "method": "tools/call",
            "params": {"name": "kern_verify_python",
                       "arguments": {"python_source": PY_VAC}}})
    r = c.read_one(timeout=300)
    txt = r["result"]["content"][0]["text"] if r else ""
    check("kern_verify_python: [VACUOUS] ловится через MCP",
          "[VACUOUS] broken" in txt and "B4: N, e = 0" in txt,
          ([l for l in txt.splitlines() if "VACUOUS" in l] or [""])[0])

    # 7b-3. ДЕЛЕНИЕ НА НОЛЬ через MCP (Этап 2).
    PY_DIV = ("# @kern:requires balance >= 0\n"
              "# @kern:ensures  result >= 0\n"
              "def share(balance: int, amount: int) -> int:\n"
              "    return balance // amount\n")
    c.send({"jsonrpc": "2.0", "id": 12, "method": "tools/call",
            "params": {"name": "kern_verify_python",
                       "arguments": {"python_source": PY_DIV}}})
    r = c.read_one(timeout=300)
    txt = r["result"]["content"][0]["text"] if r else ""
    check("kern_verify_python: деление на ноль ловится через MCP",
          "ДЕЛЕНИЕ НА НОЛЬ" in txt and "amount = 0" in txt,
          ([l for l in txt.splitlines() if "ДЕЛЕНИЕ" in l] or [""])[0])

    # 7c. ЭКВИВАЛЕНТНОСТЬ РЕФАКТОРИНГА (5-й инструмент, УЛУЧШЕНИЕ №3).
    OLD_SRC = ("def charge(balance: int, amount: int) -> int:\n"
               "    return balance - amount\n")
    EQ_SRC = ("def charge(balance: int, amount: int) -> int:\n"
              "    return -amount + balance\n")
    DIV_SRC = ("def charge(balance: int, amount: int) -> int:\n"
               "    return balance + amount\n")
    c.send({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
            "params": {"name": "kern_check_equivalence",
                       "arguments": {"old_source": OLD_SRC, "new_source": EQ_SRC}}})
    r = c.read_one(timeout=300)
    txt = r["result"]["content"][0]["text"] if r else ""
    check("kern_check_equivalence: эквивалент", "[EQUIVALENT] charge" in txt,
          ([l for l in txt.splitlines() if "EQUIVALENT" in l] or [""])[0])

    c.send({"jsonrpc": "2.0", "id": 10, "method": "tools/call",
            "params": {"name": "kern_check_equivalence",
                       "arguments": {"old_source": OLD_SRC, "new_source": DIV_SRC}}})
    r = c.read_one(timeout=300)
    txt = r["result"]["content"][0]["text"] if r else ""
    check("kern_check_equivalence: расхождение + контрпример",
          "[DIVERGED] charge" in txt and "КОНТРПРИМЕР" in txt,
          ([l for l in txt.splitlines() if "DIVERGED" in l] or [""])[0])

    # 7d. XRAY (Пункт 13): мёртвая ветка находится без аннотаций.
    # ВАЖНО: первая ветка ШИРЕ второй -> вторая НЕДОСТИЖИМА (иначе теста нет).
    # ЦЕПОЧКА if/elif: вторая ветка НЕДОСТИЖИМА (x <= 5 и x > 10 несовместны).
    # ОГРАНИЧЕНИЕ --xray (названо в METRICS): последовательные `if ... return`
    # пока путь НЕ сужают — только цепочки.
    XRAY_SRC = ("def f(x):\n"
                "    if x > 5:\n"
                "        return 2\n"
                "    elif x > 10:\n"
                "        return 1\n"
                "    return 0\n")
    c.send({"jsonrpc": "2.0", "id": 13, "method": "tools/call",
            "params": {"name": "kern_xray_code", "arguments": {"source": XRAY_SRC}}})
    r = c.read_one(timeout=300)
    txt = r["result"]["content"][0]["text"] if r else ""
    check("kern_xray_code: мёртвая ветка найдена", "[DEAD BRANCH]" in txt,
          ([l for l in txt.splitlines() if "DEAD BRANCH" in l] or [""])[0][:80])

    # 7e. FIREWALL (Пункт 36): превышение бюджета -> 422.
    c.send({"jsonrpc": "2.0", "id": 14, "method": "tools/call",
            "params": {"name": "kern_verify_action",
                       "arguments": {
                           "action": {"tool": "transfer",
                                      "args": {"amount": 900, "daily_spent": 200,
                                               "daily_limit": 1000}},
                           "policy": {"allow": "amount + daily_spent <= daily_limit",
                                      "forbid": []}}}})
    r = c.read_one(timeout=300)
    txt = r["result"]["content"][0]["text"] if r else ""
    check("kern_verify_action: 422 на превышении бюджета", "HTTP 422" in txt,
          ([l for l in txt.splitlines() if "422" in l] or [""])[0][:80])

    # 7f. RLVR (Пункт 38): чит -> -2.0.
    CHEAT_SRC = ("import sys\n\n"
                 "# @kern:requires x >= 0\n"
                 "# @kern:ensures result >= 0\n"
                 "def hack(x):\n"
                 "    if x > 1:\n"
                 "        sys.exit(0)\n"
                 "    return x\n")
    c.send({"jsonrpc": "2.0", "id": 15, "method": "tools/call",
            "params": {"name": "kern_rlvr_reward",
                       "arguments": {"source": CHEAT_SRC}}})
    r = c.read_one(timeout=300)
    txt = r["result"]["content"][0]["text"] if r else ""
    check("kern_rlvr_reward: чит -> -2.0", "R=-2.0" in txt,
          ([l for l in txt.splitlines() if "REWARD" in l] or [""])[0][:80])

    # 8a. неизвестный метод
    c.send({"jsonrpc": "2.0", "id": 7, "method": "no/such/method"})
    r = c.read_one()
    check("неизвестный метод -> -32601",
          bool(r and r.get("error", {}).get("code") == -32601))

    # 8b. битый JSON
    proc.stdin.write(b"{not json}\n")
    proc.stdin.flush()
    r = c.read_one()
    check("битый JSON -> -32700",
          bool(r and r.get("error", {}).get("code") == -32700))

    proc.stdin.close()
    proc.wait(timeout=10)
    print("-" * 74)
    if fails:
        print(f"ПРОВАЛОВ: {len(fails)} — {', '.join(fails)}")
        return 1
    print("ВСЁ ПРОЙДЕНО: сервер отвечает по протоколу и реально проверяет контракты")
    return 0


if __name__ == "__main__":
    sys.exit(main())
