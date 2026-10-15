#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
"""
KERN GUARDRAIL PROXY — живой перехватчик галлюцинаций ИИ-агента.

ЧТО ЭТО. HTTP-прокси между агентом и потребителем его кода. Ответ агента
проверяется через Врата Истины KERN: контракт уходит в реальный Z3 через
C-ABI (`libkern.so`). Если контракт НЕ доказан — код не отдаётся, а
возвращается HTTP 409 Conflict.

ПОЧЕМУ 409. RFC 9110: «409 Conflict — запрос не может быть выполнен из-за
конфликта с текущим состоянием целевого ресурса». Это ровно состояние Белнапа
B (Both): свидетельства «за» и «против» сосуществуют.

ЧТО ПЕРЕИСПОЛЬЗУЕТСЯ (ничего не пишется заново):
  * `libkern.so` + `include/kern.h` — C-ABI (kern_smt_verify, ...);
  * `kernc` — сборка образов и Врата (`verify`);
  * `tools/scan_to_kern.py` — текст -> контракты `.kern`;
  * Белнап-аккумулятор `T ⊔ F = B` (Lean-теорема `contradiction_isolation`).

Запуск:
    python3 examples/guardrail_proxy.py --port 8731
    curl -s localhost:8731/health
    curl -s -X POST localhost:8731/verify -d '{"label":"fix"}'

Зависимости: только стандартная библиотека + собранная `libkern.so`.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB_CANDIDATES = [ROOT / "zig-out" / "lib" / "libkern.so", ROOT / "libkern.so"]

# Коды вердикта из include/kern.h
KERN_PROVED, KERN_REFUTED, KERN_UNKNOWN, KERN_TOOL_ERROR = 0, 1, 2, -1
NAMES = {0: "PROVED", 1: "REFUTED", 2: "UNKNOWN", -1: "TOOL_ERROR"}


def load_kern():
    """Загружает C-ABI ядра. Без него прокси не имеет смысла — падаем явно."""
    for p in LIB_CANDIDATES:
        if p.exists():
            k = ctypes.CDLL(str(p))
            k.kern_version.restype = ctypes.c_char_p
            k.kern_smt_verify.restype = ctypes.c_int
            k.kern_smt_verify.argtypes = [ctypes.c_char_p, ctypes.c_ulong]
            return k, p
    raise FileNotFoundError(
        "нет libkern.so — соберите: zig build lib\n"
        "  (ищем: " + ", ".join(str(p) for p in LIB_CANDIDATES) + ")"
    )


def verify_smt(kern, smt: str) -> tuple[int, str]:
    """Прогон контракта через Врата. Возвращает (код_вердикта, имя)."""
    b = smt.encode("utf-8")
    rc = int(kern.kern_smt_verify(b, len(b)))
    return rc, NAMES.get(rc, f"UNKNOWN({rc})")


# Пример контракта: «списание не увеличивает баланс».
# Ровно тот случай из examples/toy_ai_hallucination: агент забыл проверку
# amount <= 0, поэтому постусловие нарушается при amount = -1.
DEFAULT_CONTRACT = """
(set-logic QF_LIA)
(declare-const balance Int)
(declare-const amount  Int)
(declare-const result  Int)
(assert (> balance 0))
(assert (= result (- balance amount)))
(assert (> result balance))
(check-sat)
"""


class GuardrailHandler(BaseHTTPRequestHandler):
    kern = None
    server_version = "KERN-Guardrail/1.0"

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # тише в консоли
        sys.stderr.write("  [proxy] " + (fmt % args) + "\n")

    def do_GET(self):
        if self.path.startswith("/health"):
            v = self.kern.kern_version()
            self._send(200, {"status": "ok",
                             "kernel": v.decode() if v else "?",
                             "gate": "Truth Gate (Z3 via C-ABI)"})
        else:
            self._send(404, {"error": "not found", "hint": "GET /health, POST /verify"})

    def do_POST(self):
        if not self.path.startswith("/verify"):
            self._send(404, {"error": "not found", "hint": "POST /verify"})
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(n) if n else b"{}"
            req = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError) as e:
            self._send(400, {"error": f"bad JSON: {e}"})
            return

        smt = req.get("smt") or DEFAULT_CONTRACT
        label = req.get("label", "agent-fix")

        try:
            rc, name = verify_smt(self.kern, smt)
        except Exception as e:  # noqa: BLE001 — прокси не должен падать
            # Fail-closed: не смогли проверить -> НЕ пропускаем.
            self._send(503, {"verdict": "e=0", "belnap_state": "N", "status": 503,
                             "label": label, "error": f"verifier unavailable: {e!r}",
                             "action": "BLOCKED (fail-closed)"})
            return

        if rc == KERN_PROVED:
            self._send(200, {
                "verdict": "e=1", "belnap_state": "T", "status": 200,
                "label": label, "checker": name,
                "action": "ADMITTED — контракт доказан на всей области определения",
            })
        elif rc == KERN_REFUTED:
            self._send(409, {
                "verdict": "e=0", "belnap_state": "B", "status": 409,
                "label": label, "checker": name,
                "error": "Truth Gate blocked AI hallucination: contract violation",
                "counterexample_hint": "amount < 0 -> баланс УВЕЛИЧИВАЕТСЯ при списании",
                "action": "BLOCKED — контрпример предъявлен",
            })
        else:
            # UNKNOWN / TOOL_ERROR — тоже НЕ пропускаем (fail-closed).
            self._send(409, {
                "verdict": "e=0", "belnap_state": "N", "status": 409,
                "label": label, "checker": name,
                "error": "verdict undecided (timeout / solver unavailable)",
                "action": "BLOCKED (fail-closed): неизвестность не является доказательством",
            })


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8731)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    try:
        kern, lib = load_kern()
    except FileNotFoundError as e:
        print(f"[!] {e}")
        return 1
    GuardrailHandler.kern = kern
    v = kern.kern_version()
    print(f"[i] KERN: {v.decode() if v else '?'}")
    print(f"[i] C-ABI: {lib}")
    srv = ThreadingHTTPServer((args.host, args.port), GuardrailHandler)
    print(f"[i] Guardrail слушает http://{args.host}:{args.port}")
    print("    GET  /health    — состояние ядра")
    print("    POST /verify    — {'smt': '<smt2>', 'label': '...'}")
    print("    200 = ДОКАЗАНО (пропущено) · 409 = КОНФЛИКТ/ОПРОВЕРГНУТО (заблокировано)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[i] остановлено")
    return 0


if __name__ == "__main__":
    sys.exit(main())

