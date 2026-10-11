#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PTE-lite: сканер проекта -> .kern (KERN-Next).

Превращает реальный проект в описание на языке KERN:
  * artifact — каждый исходный файл (sha256);
  * claim    — извлекается из ФАКТИЧЕСКИХ маркеров (тесты, TODO, доки);
  * link     — связи документов с модулями.

Честность: утверждения из README/доков помечаются status empirical
(«самозаявлено»), НЕ proven — у нас нет машинного прогона их тестов.
"""
import argparse
import hashlib
import os
import re
import sys

EXCLUDE_DIRS = {
    ".git", ".venv", ".venvs", "__pycache__", "node_modules", "library",
    "books", "sites", "images", "_trash", ".models", ".pdfium", "logs",
    ".mypy_cache", ".pytest_cache", "dist", "build",
}
SOURCE_EXT = {".py", ".md", ".yaml", ".yml", ".json", ".sh", ".toml", ".cfg", ".ini"}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def clean(s: str) -> str:
    return s.replace('"', "'").replace("\\", "/").replace("\n", " ").strip()[:120]


def scan(root: str, max_files: int, max_size: int):
    arts, claims, links = [], [], []
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            ext = os.path.splitext(fn)[1].lower()
            if ext not in SOURCE_EXT:
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            try:
                if os.path.getsize(full) > max_size:
                    continue
                digest = sha256(full)
                text = open(full, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            arts.append((rel, digest))

            # (1) тесты: файл test_*.py или наличие def test_
            if re.search(r"(^|/)test_[^/]*\.py$", rel) or re.search(r"^\s*def test_\w+", text, re.M):
                claims.append((f"tests present: {rel}", "tested", rel))

            # (2) документация: .md в docs/ или корневой README
            if ext == ".md" and (rel.startswith("docs/") or rel == "README.md"):
                claims.append((f"documented: {rel}", "verified", rel))

            # (3) незавершённое: TODO/FIXME/XXX
            #
            # 🔴 ДЕФЕКТ (найден ПРОГОНОМ KERN НА САМОМ СЕБЕ, исправлен):
            # сканер считал ЛЮБОЕ вхождение слов TODO/FIXME/XXX, из-за чего
            # выдавал ЛОЖНЫЕ блокеры:
            #   • свои собственные regex-шаблоны в этом файле;
            #   • упоминания в прозе документации («статус blocked: 1 (TODO)»).
            # На прогоне KERN по своему репозиторию это дало 2 ложных блокера
            # из 3. Теперь:
            #   • собственный исходник сканера исключён;
            #   • в коде/доках маркер считается только В КОММЕНТАРИИ;
            #   • в .jsonl/.json (свидетельства) считаются все вхождения —
            #     там это реальный вывод LLM (напр. «# TODO: Implement me»).
            if os.path.basename(rel) == os.path.basename(__file__):
                todos = 0
            elif ext in (".jsonl", ".json"):
                todos = len(re.findall(r"\b(TODO|FIXME|XXX)\b", text))
            else:
                todos = len(re.findall(
                    r"(?:#|//|/\*|\*|<!--|;|--)\s*(?:TODO|FIXME|XXX)\b", text))
            if todos > 0:
                claims.append((f"open TODOs in {rel}: {todos}", "blocked", rel))

            # (4) self-claims из README (✅ ... проверено)
            if rel == "README.md":
                for m in re.finditer(r"^\|\s*([^|]+)\|\s*`([^`]+)`\s*\|\s*(✅[^|]*)\|?", text, re.M):
                    step, mod, mark = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
                    claims.append((f"README claims '{clean(step)}' via {mod}", "empirical", rel))

            # связи: документ -> модуль (documents)
            if ext == ".md":
                for m in re.finditer(r"`([a-zA-Z0-9_/]+\.(?:py|sh|yaml|json))`", text):
                    target = m.group(1)
                    if os.path.exists(os.path.join(root, target)):
                        links.append((f"artifact:{rel}", f"artifact:{target}", "documents"))
            if len(arts) >= max_files:
                break
        if len(arts) >= max_files:
            break
    return arts, claims, links


def emit(root, arts, claims, links) -> str:
    name = os.path.basename(os.path.abspath(root))
    out = [f'project "{clean(name)}" {{', '  version "1.0"', f'  root "."', '}', '']
    for rel, digest in arts:
        out.append(f'artifact "{clean(rel)}" {{')
        out.append('  kind "source"')
        out.append(f'  hash "sha256:{digest}"')
        out.append('}')
        out.append('')
    for text, status, src in claims:
        out.append(f'claim "{clean(text)}" {{')
        out.append(f'  status {status}')
        out.append(f'  evidence "file:{clean(src)}"')
        out.append('}')
        out.append('')
    seen = set()
    for a, b, rel in links:
        if (a, b) in seen:
            continue
        seen.add((a, b))
        out.append(f'link "{clean(a)}" -> "{clean(b)}" {{')
        out.append(f'  relation "{rel}"')
        out.append('}')
        out.append('')
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="PTE-lite: проект -> .kern")
    ap.add_argument("root")
    ap.add_argument("-o", "--out", default="project.kern")
    ap.add_argument("--max-files", type=int, default=5000)
    ap.add_argument("--max-size", type=int, default=1 << 20)
    args = ap.parse_args()
    arts, claims, links = scan(args.root, args.max_files, args.max_size)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(emit(args.root, arts, claims, links))
    print(f"[OK] {args.out}: артефактов={len(arts)}, утверждений={len(claims)}, связей={len(set((a,b) for a,b,_ in links))}")


if __name__ == "__main__":
    main()
