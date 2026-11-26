#!/usr/bin/env python3
"""Сборка ПЕРЕНОСИМОГО пакета документации: `TRANSFER/`.

ЗАЧЕМ. Человек, получивший папку проекта, должен суметь (1) прочитать, что это,
(2) запустить проверку — руками и машиной, (3) убедиться, что файлы не подменены.
Рукописный документ обо всём проекте стареет за неделю (в этом репозитории это
случалось трижды: `41a30ede`, `54892bbe`, `407a65bf` — `scorecard.json` отставал
от дерева и CI краснел). Поэтому пакет ГЕНЕРИРУЕТСЯ из трёх источников:

  * `docs/facts.json` — единственный источник чисел;
  * `git`             — HEAD, ветка, первый коммит, тег, число коммитов;
  * файловая система  — состав архива и контрольные суммы.

ЧТО ПИШЕТ:
  TRANSFER/START_HERE.md      инструкция для человека (английский)
  TRANSFER/START_HERE.ru.md   то же по-русски
  TRANSFER/project.json       машиночитаемый паспорт проекта
  TRANSFER/INDEX.json         каждый файл: байты + sha256
  TRANSFER/MANIFEST.sha256    то же в формате `sha256sum -c`

ЗАПУСК:  python3 tools/gen_transfer_bundle.py [--check]
  --check — перегенерировать в память и сравнить с диском (код 1 при расхождении),
            по образцу `make scorecard-check`.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "TRANSFER"
SCHEMA = "kern.transfer/1"

# Цели, которыми читатель проверяет проект сам. Список — часть ПАСПОРТА, а не
# текста: `--check` заметит, если цель исчезла из пакета.
GATES = (
    ("claims-audit", "числа в документах совпадают с facts.json"),
    ("docs-parity", "английские и русские версии не разошлись по фактам"),
    ("docs-map-check", "каждый документ в docs/ есть в карте"),
    ("scorecard-check", "паспорт scorecard.json соответствует дереву"),
    ("xray-precision", "--xray: 5 известных ошибок найдены, ложных 0"),
    ("canfail", "мутационный харнесс: вакуумных кейсов 0"),
)


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


_VOLATILE = re.compile(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ")


def _norm(text: str) -> str:
    """Убрать ВОЛАТИЛЬНОЕ поле `generated_at`: иначе `--check` краснеет на каждом
    прогоне, и гейт перестают читать (та же ошибка, что у гейтов, которые
    сравнивали дату вместо содержимого)."""
    return _VOLATILE.sub("<generated_at>", text)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _first_heading(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[:40]:
            if line.startswith("# "):
                return line[2:].strip()
    except OSError:
        pass
    return ""


def collect() -> dict:
    facts = json.loads((ROOT / "docs" / "facts.json").read_text(encoding="utf-8"))
    index = []
    for rel in [f for f in _git("ls-files").splitlines() if f]:
        p = ROOT / rel
        if p.is_file():
            index.append({"path": rel, "bytes": p.stat().st_size, "sha256": _sha256(p)})
    docs = [{"path": p.relative_to(ROOT).as_posix(), "bytes": p.stat().st_size,
             "title": _first_heading(p)}
            for p in sorted((ROOT / "docs").glob("*.md"))]
    first = _git("log", "--reverse", "--format=%H%x09%ad%x09%s", "--date=short").splitlines()[0]
    sha, date, subject = first.split("\t")
    try:
        tag = _git("describe", "--tags", "--abbrev=0")
    except subprocess.CalledProcessError:
        tag = ""
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": "tools/gen_transfer_bundle.py",
        "sources": ["docs/facts.json", "git", "filesystem"],
        "repository": {
            "url": "https://github.com/newmathphys/kern",
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "head": _git("rev-parse", "--short", "HEAD"),
            "commits_total": int(_git("rev-list", "--count", "HEAD")),
            "first_commit": {"sha": sha[:8], "date": date, "subject": subject},
            "last_release_tag": tag,
            "license": "AGPL-3.0-or-later OR LicenseRef-KERN-Commercial",
            "files_tracked": len(index),
            "bytes_tracked": sum(i["bytes"] for i in index),
        },
        "facts": facts,
        "layout": {
            "src/": "Zig core: kernc, proof checker, C ABI",
            "formal/": "Lean metatheory + certification (KNOWN_LIMITATIONS)",
            "tools/": "Python gates, hunters, xray, SMT translation",
            "tests/": "Zig and Python suites",
            "docs/": "documentation, facts.json, evidence",
            "audits/": "corpora used for external audits",
            "examples/": "demos, MCP server, xray_demo.py",
        },
        "entrypoints": {
            "xray_no_build": "python3 tools/kern_contracts.py --xray <path>",
            "build_core": "make build   (needs Zig 0.17: ZIG=/path/to/zig make build)",
            "tests": "ZIG=/path/to/zig make test test-next",
            "gate_example": "make claims-audit",
        },
        "gates": [{"target": t, "checks": d, "command": f"make {t}"} for t, d in GATES],
        "docs_index": docs,
        "file_index": index,
    }

_EN = """# KERN — start here

This bundle was generated automatically on {gen} from commit `{head}`
(branch `{branch}`, {commits} commits, first one {first_date}).

## What this is

A verifier for code written by AI. Given a function with a contract it answers in
**three ways**, and the third is never replaced by the first: **proven** /
**counterexample** / **unknown** (with a named reason).

## Check in 5 seconds (no dependencies at all)

```bash
./zig-out/bin/kernc --version     # v2.8.26 (Zig 0.17.0)
```

The executable is statically linked and prebuilt for **x86_64-linux**
(`TRANSFER/bin/kernc`, covered by `MANIFEST.sha256`; copied to `zig-out/bin/`, where the
tools look for it). If it is missing there:

```bash
mkdir -p zig-out/bin && cp TRANSFER/bin/kernc zig-out/bin/kernc
```

## Check in 2 minutes (one external dependency: z3)

Every audit path needs a solver; `kernc check-proof` is the only offline mode and it
verifies a READY proof. Install z3 once:

```bash
python3 -m venv .venv && .venv/bin/pip install z3-solver
PATH="$PWD/.venv/bin:$PATH" python3 tools/kern_contracts.py --xray examples/xray_demo.py
```

Expect `[CRASH PATH] ... y == 0` and `[XRAY SUMMARY] checked 4 / 4` (measured on this
package, 2026-11-26).

## Full build and tests (requires Zig 0.17)

```bash
ZIG=/path/to/zig make build      # the kernc core
ZIG=/path/to/zig make test       # {core} core tests
ZIG=/path/to/zig make test-next  # {next} next-stage tests
```

## Verify the integrity of this bundle (run from the project root)

```bash
sha256sum -c TRANSFER/MANIFEST.sha256   # from the project root
```

## Project gates (one command each)

{gates}

## Where things are

{layout}

## Numbers (from `docs/facts.json`, the single source)

version {version} · core tests {core} · next-stage tests {next} · contract catalog
{catalog} · CHECK targets {check} · canfail cases {cases} · mutation sites {mut} ·
goal registry {registry} · cross-arch passed {cross}

## What it does NOT do (measured, not assumed)

See `formal/certification/KNOWN_LIMITATIONS.md` — C-function coverage: `libgit2`
503/2748, `libarchive` 25/226; `break`/`continue`/`goto` only partly modelled;
helper-function contracts are unknown; interprocedural invariants are not checked.

## Machine-readable companions

| File | Contents |
|---|---|
| `project.json` | passport: commit, facts, gates, layout, docs index |
| `INDEX.json` | every file: bytes and sha256 |
| `MANIFEST.sha256` | the same, for `sha256sum -c` |

License: {license}. Russian versions of documents sit next to the English ones with the
`.ru.md` suffix.
"""

_RU = """# KERN — начните здесь

Пакет собран автоматически {gen} из коммита `{head}` (ветка `{branch}`, коммитов
{commits}, первый — {first_date}).

## Что это

Верификатор кода, написанного ИИ. На функцию с контрактом он отвечает **тремя
способами**, и третий не подменяется первым: **доказано** / **контрпример** /
**не знаю** (с названной причиной).

## Проверка за 5 секунд (зависимостей нет вообще)

```bash
./zig-out/bin/kernc --version     # v2.8.26 (Zig 0.17.0)
```

Исполняемый файл статический, предсобран под **x86_64-linux**
(`TRANSFER/bin/kernc`, покрыт `MANIFEST.sha256`; скопирован в `zig-out/bin/`, где его
ищут инструменты). Если его там нет:

```bash
mkdir -p zig-out/bin && cp TRANSFER/bin/kernc zig-out/bin/kernc
```

## Проверка за 2 минуты (одна внешняя зависимость: z3)

Любой путь аудита требует решателя; `kernc check-proof` — единственный офлайн-режим,
он проверяет ГОТОВОЕ доказательство. Поставьте z3 один раз:

```bash
python3 -m venv .venv && .venv/bin/pip install z3-solver
PATH="$PWD/.venv/bin:$PATH" python3 tools/kern_contracts.py --xray examples/xray_demo.py
```

Ожидается `[CRASH PATH] ... y == 0` и `[XRAY SUMMARY] checked 4 / 4` (измерено на этом
пакете, 2026-11-26).

## Полная сборка и тесты (нужен Zig 0.17)

```bash
ZIG=/путь/к/zig make build      # ядро kernc
ZIG=/путь/к/zig make test       # {core} тестов ядра
ZIG=/путь/к/zig make test-next  # {next} тестов следующей ступени
```

## Проверка целостности пакета (из корня проекта)

```bash
sha256sum -c TRANSFER/MANIFEST.sha256   # из корня проекта
```

## Гейты проекта (каждый — одна команда)

{gates}

## Карта каталогов

{layout}

## Числа (из `docs/facts.json`, единственного источника)

версия {version} · тестов ядра {core} · следующей ступени {next} · каталог контрактов
{catalog} · CHECK-целей {check} · кейсов canfail {cases} · мест мутаций {mut} ·
реестр целей {registry} · cross-arch пройдено {cross}

## Чего НЕ умеет (измерено, не «предполагается»)

См. `formal/certification/KNOWN_LIMITATIONS.md`: покрытие C-функций `libgit2`
503/2748, `libarchive` 25/226; `break`/`continue`/`goto` моделируются частично;
контракты вспомогательных функций неизвестны; межпроцедурные инварианты не
проверяются.

## Машиночитаемые спутники

| Файл | Что внутри |
|---|---|
| `project.json` | паспорт: коммит, факты, гейты, карта, индекс документов |
| `INDEX.json` | каждый файл: байты и sha256 |
| `MANIFEST.sha256` | то же для `sha256sum -c` |

Лицензия: {license}. Русские версии документов лежат рядом с английскими,
суффикс `.ru.md`.


"""


def _start_here(d: dict, ru: bool) -> str:
    r, f = d["repository"], d["facts"]
    fields = {
        "gen": d["generated_at"], "head": r["head"], "branch": r["branch"],
        "commits": r["commits_total"], "first_date": r["first_commit"]["date"],
        "license": r["license"],
        "gates": "\n".join(f'- `make {g["target"]}` — {g["checks"]}' for g in d["gates"]),
        "layout": "\n".join(f"- `{k}` — {v}" for k, v in d["layout"].items()),
        "version": f.get("version"), "core": f.get("core_tests"),
        "next": f.get("next_tests"), "catalog": f.get("catalog"),
        "check": f.get("check_targets"), "cases": f.get("canfail_cases"),
        "mut": f.get("mutation_sites"), "registry": f.get("registry_targets"),
        "cross": f.get("cross_arch_passed"),
    }
    return (_RU if ru else _EN).format(**fields)


def _stage_binary(index: list) -> None:
    """Предсобранный `kernc` в пакет. ИЗМЕРЕНО: без него 60-секундная проверка
    из START_HERE ПАДАЛА (`не найден kernc: …/zig-out/bin/kernc`) — инструкция
    обещала запуск без сборки, которого не было. Бинарник кладём в
    `TRANSFER/bin/` и включаем в MANIFEST, чтобы его байты тоже проверялись; в
    развёрнутом виде он же лежит в `zig-out/bin/kernc`, где его ищет инструмент.
    """
    src = ROOT / "zig-out" / "bin" / "kernc"
    if not src.is_file():
        return
    dst = OUT / "bin" / "kernc"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("strip"):
        subprocess.run(["strip", "-o", str(dst), str(src)], check=False)
    if not dst.is_file():
        shutil.copy2(src, dst)
    dst.chmod(0o755)
    index.append({"path": "TRANSFER/bin/kernc", "bytes": dst.stat().st_size,
                  "sha256": _sha256(dst)})


def main(argv: list[str]) -> int:
    check = "--check" in argv
    data = collect()
    index = data.pop("file_index")
    _stage_binary(index)
    files = {
        "project.json": json.dumps(data, ensure_ascii=False, indent=1) + "\n",
        "INDEX.json": json.dumps({"schema": "kern.transfer-index/1",
                                  "generated_at": data["generated_at"],
                                  "files": index}, ensure_ascii=False, indent=1) + "\n",
        "MANIFEST.sha256": "".join(f"{i['sha256']}  {i['path']}\n" for i in index),
        "START_HERE.md": _start_here(data, ru=False),
        "START_HERE.ru.md": _start_here(data, ru=True),
    }
    if check:
        bad = [n for n, t in files.items()
               if not (OUT / n).is_file()
               or _norm((OUT / n).read_text(encoding="utf-8")) != _norm(t)]
        if bad:
            print(f"[FAIL] пакет устарел: {', '.join(bad)} — перегенерируйте "
                  "`python3 tools/gen_transfer_bundle.py`")
            return 1
        print(f"[OK] TRANSFER актуален: {len(files)} файлов, {len(index)} записей индекса")
        return 0
    OUT.mkdir(exist_ok=True)
    for name, body in files.items():
        (OUT / name).write_text(body, encoding="utf-8")
    print(f"[OK] TRANSFER собран: {len(files)} файлов, {len(index)} файлов в индексе, "
          f"{data['repository']['bytes_tracked']} байт под контролем")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

