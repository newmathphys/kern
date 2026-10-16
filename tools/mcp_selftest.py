#!/usr/bin/env python3
"""KERN: живая проверка MCP-сервера (JSON-RPC 2.0 поверх stdio).

Запускает `examples/kern_mcp_server.py` как ДОЧЕРНИЙ ПРОЦЕСС и общается с ним
точно так же, как реальный клиент (Claude Code, Cursor): пишет строки JSON в
stdin, читает строки JSON из stdout.

ПРОВЕРЯЕТСЯ (8 пунктов):
  1. `initialize`      — протокол и serverInfo;
  2. уведомление (без `id`) — ответа быть НЕ ДОЛЖНО;
  3. `tools/list`      — три инструмента;
  4. `kern_verify_smt` на ДОКАЗУЕМОМ контракте -> «ДОКАЗАНО», e=1;
  5. `kern_verify_smt` на ОПРОВЕРГАЕМОМ -> «НЕ доказано», e=0;
  6. `kern_prove_with_checker` -> есть строка `PROOF VERIFIED`;
  7. `kern_verify_multi_belnap` [T, F] -> `JOIN_K: B` (конфликт не схлопывается);
  7b. kern_verify_python (ветвления -> ite) -> контрпример;
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
    check("tools/list", len(names) == 4, ", ".join(names))

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
