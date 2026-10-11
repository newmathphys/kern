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


# ============================================================================
# АРХИТЕКТУРНЫЙ МОСТ «ТЕКСТ → КОНТРАКТ» (Spec-Anchors)
#
# Заявление в свободном тексте (README/спецификация) НЕ доказать: это буквы.
# Чтобы получить e=1, рядом с фразой ставится машинный якорь:
#
#   <!-- @kern:spec path="formal/bench_speed.smt2" -->
#   Скорость чтения не менее 200 МБ/с.
#
#   <!-- @kern:evidence path="docs/evidence/arm64_run.json" -->
#   Тесты проходят на ARM64 без утечек.
#
# Сканер НЕ понимает смысл фразы (иначе он превратился бы в ненадёжную LLM).
# Он лишь СВЯЗЫВАЕТ текст с контрактом/свидетельством, а вердикт выносит
# решатель в `kernc verify`: e=1 — только если Z3 доказал формулу.
# ============================================================================

ANCHOR_RE = re.compile(
    r"<!--\s*@kern:(spec|evidence)\s+path=\"([^\"]+)\""
    r"(?:\s+claim=\"([^\"]*)\")?\s*-->")


def _next_text_line(lines, idx):
    """Первая содержательная строка после якоря — текст заявления."""
    for j in range(idx + 1, min(idx + 8, len(lines))):
        s = lines[j].strip()
        if not s or s.startswith("<!--") or s.startswith("#") or s.startswith("|"):
            continue
        return s.lstrip("-*> ").strip()
    return ""


def extract_anchors(rel, text, root):
    """Возвращает (anchored_claims, proof_artifacts, proof_links).

    anchored_claims: (текст, статус, источник, путь_контракта)
    proof_artifacts: (путь, digest) — чтобы контракт попал в .kimg
    proof_links:     (claim_ref, artifact_ref, relation)
    """
    anchored, proots, plinks = [], [], []
    if "@kern:" not in text:
        return anchored, proots, plinks
    # Собственный исходник сканера содержит ЯКОРЬ-ПРИМЕР в docstring — это не
    # настоящая аннотация (та же ловушка, что и с TODO). Исключаем.
    if os.path.basename(rel) == os.path.basename(__file__):
        return anchored, proots, plinks
    lines = text.split("\n")
    in_fence = False
    for i, line in enumerate(lines):
        # 🔴 ДЕФЕКТ (найден на первом же прогоне): якорь, показанный ВНУТРИ
        # блока кода (```), — это ПРИМЕР синтаксиса, а не настоящая аннотация.
        # Без этой проверки документация о мосте сама создавала ложное
        # утверждение («Текст утверждения.» → context формально/gate_mask.smt2).
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = ANCHOR_RE.search(line)
        if not m:
            continue
        kind, path, claim_attr = m.group(1), m.group(2).strip(), (m.group(3) or "").strip()
        phrase = claim_attr or _next_text_line(lines, i)
        if not phrase:
            phrase = f"{kind}: {path}"
        full = os.path.join(root, path)
        if not os.path.exists(full):
            # Якорь указывает на НЕСУЩЕСТВУЮЩИЙ контракт — это блокер,
            # а не тихо проигнорированная строка.
            anchored.append((f"anchor broken: {path} ({rel})", "blocked", rel, ""))
            continue
        proots.append((path, sha256(full)))
        relation = "proved_by" if kind == "spec" else "supported_by"
        anchored.append((phrase, "empirical", rel, path))
        plinks.append((f"claim:{clean(phrase)}", f"artifact:{path}", relation))
    return anchored, proots, plinks


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
                claims.append((f"tests present: {rel}", "tested", rel, ""))

            # (2) документация: .md в docs/ или корневой README
            if ext == ".md" and (rel.startswith("docs/") or rel == "README.md"):
                claims.append((f"documented: {rel}", "verified", rel, ""))

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
                claims.append((f"open TODOs in {rel}: {todos}", "blocked", rel, ""))

            # (4) self-claims из README (✅ ... проверено)
            if rel == "README.md":
                for m in re.finditer(r"^\|\s*([^|]+)\|\s*`([^`]+)`\s*\|\s*(✅[^|]*)\|?", text, re.M):
                    step, mod, mark = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
                    claims.append((f"README claims '{clean(step)}' via {mod}", "empirical", rel, ""))

            # (5) АРХИТЕКТУРНЫЙ МОСТ: якоря @kern:spec / @kern:evidence.
            # Именно они превращают фразу в проверяемое утверждение.
            a_claims, a_arts, a_links = extract_anchors(rel, text, root)
            for c in a_claims:
                claims.append(c)
            for pa in a_arts:
                if pa not in arts:
                    arts.append(pa)
            for lk in a_links:
                links.append(lk)

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
    for text, status, src, contract in claims:
        out.append(f'claim "{clean(text)}" {{')
        out.append(f'  status {status}')
        out.append(f'  evidence "file:{clean(src)}"')
        # МОСТ: путь к машинному контракту. `kernc build` кладёт его в payload
        # заявления, а `kernc verify` находит контракт в образе и прогоняет
        # через Z3. Без этой строки утверждение остаётся e=0.
        if contract:
            out.append(f'  context "{clean(contract)}"')
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
