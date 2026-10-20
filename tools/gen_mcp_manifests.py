#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Генератор MCP-манифестов из ЕДИНСТВЕННОГО источника — `examples/kern_mcp_server.py`.

ЗАЧЕМ. Внешние каталоги (m8ven.ai, Smithery, Glama, Official MCP Registry)
читают декларативный манифест в корне репозитория. Раньше его не было, и
`m8ven.ai` писал «tool surface unread» — при том что сервер исправно отдаёт
8 инструментов через `tools/list`.

ПРИНЦИП. Манифесты НЕ пишутся руками: они ГЕНЕРИРУЮТСЯ из `TOOLS`, чтобы
имена, `inputSchema` и `annotations` не могли разъехаться с кодом.

  python3 tools/gen_mcp_manifests.py           # перезаписать манифесты
  python3 tools/gen_mcp_manifests.py --check   # проверить синхронность (rc!=0 при расхождении)

Выход:
  server.json            — карточка сервера для реестров (все 8 инструментов)
  mcp.json               — готовый конфиг для MCP-клиентов
  .well-known/mcp.json   — discovery-документ (tools + entrypoint)

🔴 ЧЕСТНАЯ ГРАНИЦА: `$schema` — ссылка на схему реестра, но мы НЕ заявляем,
что файл прошёл валидацию официального реестра (офлайн её выполнить нельзя).
Проверяется собственная структурная корректность и ПОЛНАЯ синхронность с кодом.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "examples" / "kern_mcp_server.py"

VERSION = "2.5.0"
# Лицензия: строго как в LICENSE (PolyForm Noncommercial 1.0.0, source-available).
LICENSE_FIELD = "PolyForm-Noncommercial-1.0.0"
LICENSE_TEXT = "PolyForm Noncommercial License 1.0.0"

DESCRIPTION = (
    "Zero-trust verification gateway: Z3 + a native Zig proof-DAG checker "
    "(trusted steps 0), Belnap B4 logic, Lean 4 soundness theorems, and "
    "zero-annotation X-ray for Python, Zig, C, Rust, Go and TS/JS."
)


def load_tools() -> tuple[list[dict], dict]:
    spec = importlib.util.spec_from_file_location("kern_mcp_server", SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return list(mod.TOOLS), dict(mod.SERVER_INFO)


def manifest_tools(tools: list[dict]) -> list[dict]:
    out = []
    for t in tools:
        ann = t.get("annotations") or {}
        out.append({
            "name": t["name"],
            "description": t["description"],
            "inputSchema": t["inputSchema"],
            "annotations": {
                "title": ann.get("title", t["name"]),
                "readOnlyHint": bool(ann.get("readOnlyHint")),
                "destructiveHint": bool(ann.get("destructiveHint")),
                "idempotentHint": bool(ann.get("idempotentHint")),
                "openWorldHint": bool(ann.get("openWorldHint")),
            },
        })
    return out



def build(tools: list[dict], info: dict) -> dict[str, dict]:
    t = manifest_tools(tools)
    common = {
        "name": "io.github.newmathphys/kern",
        "title": "KERN — zero-trust verification gateway",
        "description": DESCRIPTION,
        "version": VERSION,
        "license": LICENSE_FIELD,
        "repository": {
            "url": "https://github.com/newmathphys/kern",
            "source": "github",
        },
        "homepage": "https://newmathphys.github.io/kern/",
        "keywords": [
            "formal-verification", "z3", "smt", "lean4", "belnap-logic",
            "ai-safety", "zero-trust", "mutation-testing", "blake3", "zig",
        ],
    }
    server = {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-07-09/server.schema.json",
        **common,
        "transport": {"type": "stdio"},
        "entrypoint": {"command": "python3", "args": ["examples/kern_mcp_server.py"]},
        "serverInfo": {"name": info.get("name", "kern"),
                       "version": info.get("version", VERSION)},
        "tools": t,
    }
    desktop = {
        "mcpServers": {
            "kern": {
                "command": "python3",
                "args": ["examples/kern_mcp_server.py"],
                "env": {"PYTHONUNBUFFERED": "1"},
            }
        }
    }
    wellknown = {
        "name": common["name"],
        "title": common["title"],
        "version": VERSION,
        "description": DESCRIPTION,
        "license": LICENSE_FIELD,
        "homepage": common["homepage"],
        "transport": "stdio",
        "entrypoint": server["entrypoint"],
        "tools": [{"name": x["name"], "title": x["annotations"]["title"],
                   "inputSchema": x["inputSchema"], "annotations": x["annotations"]}
                  for x in t],
    }
    # Glama.ai: свой манифест с maintainers + аннотациями (каталог ищет
    # `glama.json` в корне; без него карточка остаётся неразмеченной).
    glama = {
        "$schema": "https://glama.ai/mcp/schemas/server.json",
        "name": common["name"],
        "title": common["title"],
        "version": VERSION,
        "description": DESCRIPTION,
        "repository": "https://github.com/newmathphys/kern",
        "homepage": common["homepage"],
        "license": LICENSE_FIELD,
        "maintainers": ["newmathphys"],
        "runtime": "python",
        "startCommand": {"type": "stdio",
                         "command": server["entrypoint"]["command"],
                         "args": server["entrypoint"]["args"]},
        "tools": [{"name": x["name"], "description": x.get("description", ""),
                   "annotations": x["annotations"]} for x in t],
    }
    return {
        "server.json": server,
        "mcp.json": desktop,
        ".well-known/mcp.json": wellknown,
        "glama.json": glama,
    }


def write(docs: dict[str, dict]) -> int:
    for rel, doc in docs.items():
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
        n = len(doc.get("tools", doc.get("mcpServers", {})))
        print(f"[ok] {rel} ({n} записей)")
    return 0


def check(docs: dict[str, dict]) -> int:
    """Манифесты == код · аннотации на месте · лицензия консистентна."""
    bad = 0
    tools, _info = load_tools()
    names = [t["name"] for t in tools]
    if len(names) != 8 or len(set(names)) != 8:
        print(f"[!] в TOOLS ожидалось 8 уникальных инструментов, получено {names}")
        bad += 1

    for t in tools:
        ann = t.get("annotations") or {}
        for key in ("title", "readOnlyHint", "destructiveHint",
                    "idempotentHint", "openWorldHint"):
            if key not in ann:
                print(f"[!] {t['name']}: нет annotations.{key}")
                bad += 1

    for rel, doc in docs.items():
        p = ROOT / rel
        if not p.is_file():
            print(f"[!] нет файла {rel} — запустите без --check")
            bad += 1
            continue
        try:
            on_disk = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"[!] {rel}: невалидный JSON ({e})")
            bad += 1
            continue
        if on_disk != doc:
            print(f"[!] {rel}: УСТАРЕЛ (расходится с examples/kern_mcp_server.py)")
            bad += 1

    # Smithery.yaml — статический шаблон запуска; проверяем, что он не
    # разъехался с версией/точкой входа/лицензией манифестов.
    try:
        import yaml  # noqa: PLC0415
        sm = yaml.safe_load((ROOT / "smithery.yaml").read_text(encoding="utf-8"))
        assert str(sm.get("version")) == VERSION, sm.get("version")
        assert sm.get("license") == LICENSE_FIELD, sm.get("license")
        assert sm["startCommand"]["type"] == "stdio"
        assert "examples/kern_mcp_server.py" in " ".join(sm["startCommand"]["commandFunction"].split())
    except Exception as e:  # noqa: BLE001
        print(f"[!] smithery.yaml: {e}")
        bad += 1
    lic = (ROOT / "LICENSE").read_text(encoding="utf-8", errors="replace")
    if LICENSE_TEXT not in lic:
        print(f"[!] LICENSE не содержит «{LICENSE_TEXT}», "
              f"а манифесты объявляют {LICENSE_FIELD}")
        bad += 1
    for rel in ("server.json", ".well-known/mcp.json"):
        p = ROOT / rel
        if p.is_file():
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("license") != LICENSE_FIELD:
                print(f"[!] {rel}: license={d.get('license')!r}, "
                      f"ожидалось {LICENSE_FIELD!r}")
                bad += 1

    if bad:
        print(f"[!] ecosystem: {bad} расхождени(й) — манифесты НЕ синхронны")
        return 1
    print(f"[ok] ecosystem: {len(names)} инструментов синхронны с манифестами; "
          f"license={LICENSE_FIELD}; annotations на месте у всех")
    return 0


def main() -> int:
    tools, info = load_tools()
    docs = build(tools, info)
    if "--check" in sys.argv[1:]:
        return check(docs)
    return write(docs)


if __name__ == "__main__":
    sys.exit(main())
