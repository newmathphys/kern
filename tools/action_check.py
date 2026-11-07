#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""`action_check` — ЛОКАЛЬНАЯ ПРОВЕРКА `action.yml` (Шаг 2 плана ROI).

ЗАЧЕМ. До этой правки `action.yml` ОБЕЩАЛ то, чего не делал: он качал один
бинарник `kernc` и запускал `--xray` через `tools/kern_contracts.py` из
раннера — то есть требовал Python-окружение клиента, а `sarif-file` в режиме
`--xray` НЕ создавался вовсе (ИЗМЕРЕНО на kerna-dist-v2.8.1: флаг принимается,
файла нет). Обещание без артефакта — класс #497/#370. Кроме того `make
audit-delta` не умел сравнивать РАЗНЫЕ корни (дефект #498, измерен: две
идентичные папки давали «новых 5 + исчезло 5»), поэтому PR-гейт на дельте был
бы ЛОЖНЫМ по построению.

ЧТО ДОКАЗЫВАЕТСЯ (каждое — проверка, не обещание):

  R1 СТРУКТУРА: `action.yml` разбирается fail-closed парсером (неизвестная
     конструкция — ОТКАЗ, а не «пропустим»), `runs.using == composite`,
     каждый шаг имеет `shell: bash` и `run:`;
  R2 ПЕРЕМЕННЫЕ: каждое `${{ inputs.X }}` объявлено в `inputs`, каждый
     `outputs.*.value` ссылается на существующий шаг;
  R3 SUPPLY-CHAIN: в шаге установки есть `sha256sum -c` (архив не
     распаковывается до сверки) — и нет `--sarif` (измерено: не выпускается);
  R4 СУХОЙ ПРОГОН: шаги `action.yml` ИСПОЛНЯЮТСЯ здесь же, на локальном
     источнике релиза (`KERN_RELEASE_BASE=file://…`) — сеть не нужна. Матрица:
        head=чисто, base нет      -> rc 0
        head=баг,   base нет      -> rc 1 (все находки новые)
        base=чисто, head=баг      -> rc 1 (регресс внесён этим изменением)
        base=баг,   head=баг      -> rc 0 (НИЧЕГО нового — главный анти-FP)
        base=баг,   head=чисто    -> rc 0 (исправлено)
        битый архив               -> rc 3 (НЕ «код чист»)
        SHA256SUMS без ассета     -> rc 3
        `--doctor` не проходит    -> rc 2 (НАЗВАННЫЙ отказ, не «находок 0»)
  R5 НЕВАКУУМНОСТЬ: `--selftest` доказывает, что R1–R3 УМЕЮТ падать (4 вида
     поломки файла), а не «зелены всегда».

ЧЕГО ЭТО НЕ ДОКАЗЫВАЕТ (граница названа): шаги исполняются в ЭМУЛЯЦИИ
раннера (переменные `GITHUB_ENV`/`GITHUB_PATH` подхватываются между шагами
этим скриптом), а не на GitHub-hosted runner. Установка `actions/checkout`
тоже не проверяется — она в рабочем процессе пользователя, не в actions.

Запуск:
  python3 tools/action_check.py                 # статика + сухой прогон (fake-релиз)
  python3 tools/action_check.py --release-dir dist-release
                                                # тот же прогон на РЕАЛЬНОМ
                                                # архиве (сверяет настоящий SHA-256)
  python3 tools/action_check.py --selftest      # невакуумность (гейт умеет падать)
Код возврата: 0 — все инварианты выполнены; 1 — нарушение; 2 — нет входа/архива.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACTION = ROOT / "action.yml"
VER_RE = re.compile(r"^v\d+\.\d+\.\d+$")
EXPR_RE = re.compile(r"\$\{\{\s*([^}]*?)\s*\}\}")


class YamlError(Exception):
    """Конструкция вне поддерживаемого подмножества — ОТКАЗ, а не догадка."""


def _scalar(text: str) -> str:
    t = text.strip()
    if not t:
        return ""
    if t[0] in "{[&*!|>%@`":
        raise YamlError(f"конструкция вне подмножества: {t[:40]!r}")
    if t[0] in "'\"":
        q = t[0]
        if len(t) < 2 or t[-1] != q:
            raise YamlError(f"незакрытая кавычка: {t[:40]!r}")
        return t[1:-1]
    return t


def parse_action(text: str) -> dict:
    """Fail-closed разбор ТОЛЬКО тех конструкций, что нужны `action.yml`.

    Поддерживается: блочные отображения, блочные последовательности, скаляры
    в кавычках/без, блочные скаляры `|`. Всё прочее (табы в отступе, flow
    `{...}`/`[...]`, якоря, дубликаты ключей) — YamlError. Смысл именно в
    строгости: непонятый файл обязан КРАСНЕТЬ, а не проходить «по тексту».
    """
    raw = text.splitlines()
    lines: list[tuple[int, str]] = []
    for n, line in enumerate(raw, 1):
        stripped = line.lstrip(" ")
        if not stripped or stripped.startswith("#"):
            continue
        if "\t" in line[: len(line) - len(stripped)]:
            raise YamlError(f"строка {n}: табуляция в отступе")
        lines.append((len(line) - len(stripped), stripped))

    pos = 0

    def block(indent: int):
        nonlocal pos
        if pos < len(lines) and lines[pos][1].startswith("- "):
            seq: list = []
            while pos < len(lines):
                ind, body = lines[pos]
                if ind != indent or not body.startswith("- "):
                    if ind > indent:
                        raise YamlError(f"неожиданный отступ у пункта: {body[:40]!r}")
                    break
                rest = body[2:]
                if re.match(r"[A-Za-z_][\w.-]*\s*:", rest):
                    lines[pos] = (indent + 2, rest)
                    seq.append(block(indent + 2))
                else:
                    pos += 1
                    seq.append(_scalar(rest))
            return seq

        mapping: dict = {}
        while pos < len(lines):
            ind, body = lines[pos]
            if ind < indent:
                break
            if ind > indent:
                raise YamlError(f"неожиданный отступ: {body[:40]!r}")
            if body.startswith("- "):
                break
            m = re.match(r"([A-Za-z_][\w.-]*)\s*:(?:\s+(.*))?$", body)
            if not m:
                raise YamlError(f"не ключ верхнего уровня: {body[:40]!r}")
            key, rest = m.group(1), (m.group(2) or "")
            if key in mapping:
                raise YamlError(f"дубликат ключа {key!r}")
            pos += 1
            if rest.strip() in ("|", "|-", ">", ">-"):
                block_indent = None
                chunk: list[str] = []
                while pos < len(lines) and lines[pos][0] > indent:
                    ind2, body2 = lines[pos]
                    if block_indent is None:
                        block_indent = ind2
                    # блочный скаляр сохраняет содержимое КАК ЕСТЬ (в т.ч. '#')
                    chunk.append(" " * (ind2 - block_indent) + body2)


                    pos += 1
                mapping[key] = "\n".join(chunk) + "\n"
            elif rest.strip():
                mapping[key] = _scalar(rest)
            elif pos < len(lines) and lines[pos][0] > indent:
                mapping[key] = block(lines[pos][0])
            else:
                mapping[key] = ""
        return mapping

    doc = block(lines[0][0] if lines else 0)
    if pos != len(lines):
        raise YamlError(f"не разобран остаток файла со строки {pos + 1}")
    if not isinstance(doc, dict):
        raise YamlError("верхний уровень обязан быть отображением")
    return doc

def _walk_strings(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_strings(v)
    elif isinstance(node, str):
        yield node


def static_contract(doc: dict) -> list[str]:
    """R1–R3: структура композитного action, переменные, supply-chain."""
    bad: list[str] = []
    runs = doc.get("runs")
    if not isinstance(runs, dict):
        return ["нет блока runs"]
    if runs.get("using") != "composite":
        bad.append(f"runs.using = {runs.get('using')!r}, ожидалось 'composite'")
    steps = runs.get("steps")
    if not isinstance(steps, list) or not steps:
        return bad + ["runs.steps пуст или не список"]
    ids: set[str] = set()
    for i, st in enumerate(steps, 1):
        if not isinstance(st, dict):
            bad.append(f"шаг {i}: не отображение")
            continue
        extra = set(st) - {"name", "id", "shell", "run"}
        if extra:
            # иначе эмулятор молча проигнорировал бы поведение раннера
            bad.append(f"шаг {i}: ключи вне подмножества {sorted(extra)}")
        if st.get("shell") != "bash":
            bad.append(f"шаг {i}: shell = {st.get('shell')!r}, ожидалось 'bash'")
        if not str(st.get("run", "")).strip():
            bad.append(f"шаг {i}: нет блока run")
        if st.get("id"):
            ids.add(str(st["id"]))

    declared = set((doc.get("inputs") or {}).keys())
    for s in _walk_strings(doc):
        for expr in EXPR_RE.findall(s):
            if expr.startswith("inputs."):
                if expr.split(".", 1)[1] not in declared:
                    bad.append(f"выражение {expr!r}: вход не объявлен")
            elif expr == "github.action_path":
                continue
            elif re.match(r"steps\.[\w-]+\.outputs\.[\w-]+$", expr):
                if expr.split(".")[1] not in ids:
                    bad.append(f"выражение {expr!r}: шага с таким id нет")
            else:
                bad.append(f"выражение {expr!r}: вне подмножества (гейт обязан краснеть)")

    for name, out in (doc.get("outputs") or {}).items():
        val = str((out or {}).get("value", ""))
        m = re.search(r"steps\.([\w-]+)\.", val)
        if not m or m.group(1) not in ids:
            bad.append(f"выход {name!r}: value не ссылается на существующий шаг ({val!r})")

    joined = "\n".join(str(s.get("run", "")) for s in steps if isinstance(s, dict))
    if "sha256sum -c" not in joined:
        bad.append("в шагах нет `sha256sum -c` — архив не сверяется перед распаковкой")
    if "--sarif" in joined:
        bad.append("шаг обещает SARIF: измерено, что `--xray --sarif` НЕ создаёт файл "
                   "(класс #497/#370) — обещание без артефакта запрещено")
    if "KERN_RELEASE_BASE" not in joined:
        bad.append("нет точки подмены источника релиза (KERN_RELEASE_BASE) — "
                   "локальный сухой прогон был бы невозможен")
    return bad


EXAMPLE = ROOT / "examples" / "ci" / "kern-gate.yml"


def example_contract(doc: dict, example: Path) -> list[str]:
    """R6: ОБРАЗЕЦ процесса обязан ссылаться на ЭТО действие и его входы.

    Иначе `README-RUN.txt` и план ссылались бы на «работающий пример»,
    которого нет или который зовёт несуществующий вход (класс #497).
    """
    if not example.exists():
        return [f"нет образца {example.relative_to(ROOT)} — ссылка на него была бы обещанием"]
    try:
        wf = parse_action(example.read_text(encoding="utf-8"))
    except YamlError as e:
        return [f"{example.name}: не разобран: {e}"]
    ver = str(((doc.get("inputs") or {}).get("version") or {}).get("default", ""))
    declared = set((doc.get("inputs") or {}).keys())
    bad: list[str] = []
    used = 0
    for job, body in (wf.get("jobs") or {}).items():
        for st in (body or {}).get("steps") or []:
            uses = str((st or {}).get("uses", ""))
            if not uses.startswith("newmathphys/kern@"):
                continue
            used += 1
            if not uses.endswith("@" + ver):
                bad.append(f"{job}: образец ссылается на {uses}, а action.yml объявляет {ver}")
            for key in ((st or {}).get("with") or {}):
                if key not in declared:
                    bad.append(f"{job}: вход {key!r} не объявлен в action.yml")
    if not used:
        bad.append("образец не использует newmathphys/kern@ — тогда он ничего не проверяет")
    return bad


def render(script: str, values: dict) -> str:
    """Подстановка `${{ … }}`. Неподставленное выражение — ОТКАЗ, не литерал."""
    def sub(m: re.Match) -> str:
        e = m.group(1)
        if e in values:
            return values[e]
        raise YamlError(f"выражение {e!r} не подставлено — исполнять литерал запрещено")
    return EXPR_RE.sub(sub, script)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ПОДСТАВНОЙ апплаенс: те же ДВА интерфейса, что у настоящего `kerna`
# (`--doctor`; `--xray DIR --xray-json` -> ABI-документ #483). Нужен, чтобы
# прогонять ТРУБУ действия (сверка SHA-256, распаковка, доктор, дельта) в CI без
# 27-мегабайтного архива; сам РЕАЛЬНЫЙ бинарь проверяет `make kerna-check` (#494).
FAKE_KERNA = r"""#!/usr/bin/env bash
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cmd="${1:-}"
if [ "$cmd" = "--doctor" ]; then
  if [ -f "$here/NO_SOLVER" ]; then
    echo "[!] kerna doctor: нет решателя z3 (fake)" >&2
    exit 2
  fi
  echo "[OK] kerna doctor: зависимости на месте (fake)"
  exit 0
fi
if [ "$cmd" = "--xray" ]; then
  dir="${2:-}"
  [ -n "$dir" ] || { echo "нужен каталог" >&2; exit 3; }
  case " $* " in *" --xray-json "*) : ;; *) echo "ожидался --xray-json" >&2; exit 3 ;; esac
  abs="$(cd "$dir" 2>/dev/null && pwd)" || { echo "нет каталога: $dir" >&2; exit 3; }
  list="$here/.findings.$$"
  : > "$list"
  find "$abs" -type f -name 'buggy.py' 2>/dev/null | sort >> "$list"
  n=$(wc -l < "$list")
  printf '{\n  "schema_version": "1.0",\n  "audit_target": "%s",\n' "$abs"
  printf '  "summary": {"files": %d, "total": %d, "checked": 0, "trivial": %d, "skipped": 0, "findings": %d, "unreadable": 0},\n' "$n" "$n" "$n" "$n"
  printf '  "findings": ['
  i=0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    i=$((i+1))
    [ "$i" -eq 1 ] || printf ','
    printf '\n    {"file": "%s", "type": "CRASH PATH", "details": "div_unguarded: строка 3 — возможно деление на ноль: b == 0"}' "$f"
  done < "$list"
  printf '\n  ],\n  "skipped": [],\n  "notes": []\n}\n'
  rm -f "$list"
  exit 0
fi
echo "неизвестный аргумент: $cmd" >&2
exit 3
"""




def write_tree(dest: Path, kind: str) -> None:
    """Дерево фикстур: `buggy.py` ловится детектором деления без гарда."""
    dest.mkdir(parents=True, exist_ok=True)
    if kind == "buggy":
        (dest / "buggy.py").write_text("def div_unguarded(a, b):\n    return a / b\n",
                                      encoding="utf-8")
    elif kind == "clean":
        (dest / "clean.py").write_text("def ok(a, b):\n    return a + b\n",
                                      encoding="utf-8")
    else:
        raise ValueError(f"неизвестный вид дерева: {kind}")


def make_fake_release(release_dir: Path, ver: str, *, variant: str = "ok") -> Path:
    """Собрать ЛОКАЛЬНЫЙ релиз (архив + SHA256SUMS) без сети и без 27 МБ."""
    stage = release_dir / f"kerna-dist-{ver}"
    stage.mkdir(parents=True)
    k = stage / "kerna"
    k.write_text(FAKE_KERNA, encoding="utf-8")
    k.chmod(0o755)
    (stage / "LIMITS.md").write_text("fake limits (гейт проверяет только наличие)\n",
                                     encoding="utf-8")
    if variant == "doctor":
        (stage / "NO_SOLVER").write_text("", encoding="utf-8")
    inner = [f"{sha256_file(p)}  ./{p.relative_to(stage).as_posix()}"
             for p in sorted(stage.rglob("*")) if p.is_file()]
    (stage / "SHA256SUMS").write_text("\n".join(inner) + "\n", encoding="utf-8")

    tar = release_dir / f"kerna-dist-{ver}.tar.gz"
    with tarfile.open(tar, "w:gz") as tf:
        tf.add(stage, arcname=stage.name)
    digest = sha256_file(tar)
    if variant == "corrupt":
        data = bytearray(tar.read_bytes())
        data[len(data) // 2] ^= 0xFF          # порча ПОСЛЕ подсчёта суммы
        tar.write_bytes(bytes(data))
    (release_dir / "SHA256SUMS").write_text(f"{digest}  {tar.name}\n", encoding="utf-8")
    if variant == "no_asset":
        (release_dir / "SHA256SUMS").write_text("0" * 64 + "  something-else.tgz\n",
                                                encoding="utf-8")
    return release_dir


def _git(cwd: Path, *args: str) -> None:
    p = subprocess.run(["git", "-C", str(cwd), "-c", "user.email=gate@example.com",
                        "-c", "user.name=gate", *args],
                       capture_output=True, text=True)
    if p.returncode != 0:
        # ОТКАЗ С ПРИЧИНОЙ: молчаливый fail дал бы «гейт сломался» вместо диагноза
        raise RuntimeError(f"git {' '.join(args)}: rc={p.returncode} "
                           f"{p.stderr.strip() or p.stdout.strip()}")


def make_workspace(tmp: Path, base_kind: str | None, head_kind: str) -> Path:
    """Рабочее дерево головы + (если задан base) bare-origin с веткой `base-ref`."""
    work = tmp / "work"
    if base_kind is None:
        write_tree(work, head_kind)
        return work
    seed = tmp / "seed"
    write_tree(seed, base_kind)
    _git(seed, "init", "-q")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-qm", "base")
    _git(seed, "branch", "base-ref")
    for p in seed.iterdir():
        if p.name != ".git":
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    write_tree(seed, head_kind)
    _git(seed, "add", "-A")
    _git(seed, "commit", "--allow-empty", "-qm", "head")
    bare = tmp / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(bare)],
                   check=True, capture_output=True, text=True)
    subprocess.run(["git", "clone", "-q", str(bare), str(work)],
                   check=True, capture_output=True, text=True)
    return work


def _absorb(env: dict, path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and line.strip() and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v


def run_action(doc: dict, *, work: Path, temp: Path, release_base: str,
               values: dict) -> tuple[int, str]:
    """ЭМУЛЯЦИЯ раннера: шаги исполняются по порядку, env-файлы подхватываются."""
    holder = work / ".runner"
    holder.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k != "KERN_RELEASE_BASE"}
    # ВНЕ рабочего дерева: иначе распакованный апплаенс попал бы в аудит
    env["RUNNER_TEMP"] = str(temp)
    temp.mkdir(parents=True, exist_ok=True)
    env["KERN_RELEASE_BASE"] = release_base
    log: list[str] = []
    for i, st in enumerate(doc["runs"]["steps"], 1):
        ge, go, gp = (holder / f"env_{i}", holder / f"out_{i}", holder / f"path_{i}")
        for f in (ge, go, gp):
            f.write_text("", encoding="utf-8")
        env.update(GITHUB_ENV=str(ge), GITHUB_OUTPUT=str(go), GITHUB_PATH=str(gp))
        script = render(str(st["run"]), values)
        p = subprocess.run(["bash", "-c", script], cwd=str(work), env=env,
                           capture_output=True, text=True)
        log.append(f"--- шаг {i}: {st.get('name', '')} (rc={p.returncode})\n"
                   f"{p.stdout}{p.stderr}".rstrip())
        _absorb(env, ge)
        extra = gp.read_text(encoding="utf-8").strip()
        if extra:
            env["PATH"] = extra.replace("\n", ":") + ":" + env["PATH"]
        if p.returncode != 0:
            return p.returncode, "\n".join(log)
    return 0, "\n".join(log)


CASES = [
    # (описание, вид base, вид head, вариант релиза, ожидаемый rc, ожидаемых новых)
    ("head=чисто, base нет -> rc 0", None, "clean", "ok", 0, 0),
    ("head=баг, base нет -> rc 1 (все находки новые)", None, "buggy", "ok", 1, 1),
    ("base=чисто, head=баг -> rc 1 (регресс этого изменения)", "clean", "buggy", "ok", 1, 1),
    ("base=баг, head=баг -> rc 0 (НИЧЕГО нового: анти-FP)", "buggy", "buggy", "ok", 0, 0),
    ("base=баг, head=чисто -> rc 0 (исправлено)", "buggy", "clean", "ok", 0, 0),
    ("битый архив -> rc 3 (НЕ «код чист»)", None, "buggy", "corrupt", 3, None),
    ("SHA256SUMS без ассета -> rc 3", None, "buggy", "no_asset", 3, None),
    ("--doctor rc=2 -> rc 2 (названный отказ)", None, "buggy", "doctor", 2, None),
]

REAL_CASES = [c for c in CASES if c[3] == "ok"]


def _report_new_findings(temp: Path) -> int | None:
    rep = temp / "kern-delta.json"
    if not rep.exists():
        return None
    try:
        return len(json.loads(rep.read_text(encoding="utf-8")).get("new_findings", []))
    except json.JSONDecodeError:
        return None


def run_matrix(doc: dict, ver: str, *, release_dir: Path | None) -> int:
    fails = 0
    cases = CASES if release_dir is None else REAL_CASES
    for desc, base_kind, head_kind, variant, want_rc, want_new in cases:
        with tempfile.TemporaryDirectory(prefix="kern_action_case_") as td:
            tmp = Path(td)
            rel = (make_fake_release(tmp / "release", ver, variant=variant)
                   if release_dir is None else Path(release_dir))
            work = make_workspace(tmp / "ws", base_kind, head_kind)
            temp = tmp / "runner_temp"
            values = {
                "inputs.version": ver,
                "inputs.path": ".",
                "inputs.base": "base-ref" if base_kind else "",
                "github.action_path": str(ROOT),
            }
            rc, log = run_action(doc, work=work, temp=temp,
                                 release_base=rel.as_uri(), values=values)
            got_new = _report_new_findings(temp)
            ok = rc == want_rc and (want_new is None or got_new == want_new)
            if ok:
                extra = "" if want_new is None else f", новых {got_new}"
                print(f"  OK   {desc}: rc={rc}{extra}")
            else:
                fails += 1
                print(f"  FAIL {desc}: rc={rc} (ожидался {want_rc}), "
                      f"новых={got_new} (ожидалось {want_new})")
                print("\n".join("       " + ln for ln in log.splitlines()[-12:]))
    return fails


def selftest() -> int:
    """R5: гейт обязан КРАСНЕТЬ. Каждая поломка вносится в копию текста."""
    src = ACTION.read_text(encoding="utf-8")
    fails = 0

    def expect(name: str, text: str) -> None:
        nonlocal fails
        try:
            doc = parse_action(text)
        except YamlError as e:
            print(f"  OK   {name}: ОТКАЗ разбора ({e})")
            return
        problems = static_contract(doc)
        if problems:
            print(f"  OK   {name}: замечено — {problems[0]}")
        else:
            fails += 1
            print(f"  FAIL {name}: гейт НЕ заметил поломку (вакуум)")

    expect("табуляция в отступе", src.replace("  icon:", "\ticon:", 1))
    expect("flow-коллекция", src.replace("  icon: 'shield'", "  icon: {a: b}", 1))
    expect("ключ шага вне подмножества (if:)",
           src.replace("      shell: bash", "      if: true\n      shell: bash", 1))
    expect("нет сверки SHA-256", src.replace("sha256sum -c", "echo no-check", 2))
    expect("обещан SARIF", src.replace(
        'python3 "${{ github.action_path }}/tools/audit_delta.py"',
        'python3 "${{ github.action_path }}/tools/audit_delta.py" --sarif out.sarif', 1))
    expect("вход не объявлен", src.replace("${{ inputs.path }}", "${{ inputs.nope }}", 1))

    # R6: образец с НЕСУЩЕСТВУЮЩИМ входом обязан краснеть (иначе README-RUN
    # ссылался бы на пример, который не запустится).
    broken_text = EXAMPLE.read_text(encoding="utf-8").replace("          base:",
                                                              "          base-nope:", 1)
    with tempfile.TemporaryDirectory() as td:
        broken = Path(td) / "kern-gate.yml"
        broken.write_text(broken_text, encoding="utf-8")
        probs = example_contract(parse_action(src), broken)
    if probs:
        print(f"  OK   образец с неверным входом: замечено — {probs[0]}")
    else:
        fails += 1
        print("  FAIL образец с неверным входом: гейт НЕ заметил (вакуум)")

    good = static_contract(parse_action(src))
    if good:
        fails += 1
        print(f"  FAIL эталон обязан быть чистым: {good}")
    else:
        print("  OK   эталон: нарушений нет")
    print(f"[{'FAIL' if fails else 'OK'}] action-check selftest: провалов {fails}")
    return 1 if fails else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Локальная проверка action.yml")
    ap.add_argument("path", nargs="?", default=str(ACTION))
    ap.add_argument("--release-dir", default=None,
                    help="каталог с РЕАЛЬНЫМ релизом (архив + SHA256SUMS); без него "
                         "сухой прогон идёт на локальном fake-релизе")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(sys.argv[1:] if argv is None else list(argv))

    if a.selftest:
        return selftest()

    path = Path(a.path)
    if not path.exists():
        print(f"[!] нет {path}")
        return 2
    missing = [t for t in ("bash", "curl", "git") if not shutil.which(t)]
    if missing:
        print(f"[!] для сухого прогона нужны: {missing}")
        return 2

    try:
        doc = parse_action(path.read_text(encoding="utf-8"))
    except YamlError as e:
        print(f"[FAIL] action.yml не разобран: {e}")
        return 1
    problems = static_contract(doc) + example_contract(doc, EXAMPLE)
    if problems:
        print("[FAIL] статический контракт:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("[OK] статика: структура, входы/выходы, sha256-сверка, KERN_RELEASE_BASE")

    ver = str(((doc.get("inputs") or {}).get("version") or {}).get("default", ""))
    if not VER_RE.match(ver):
        print(f"[FAIL] inputs.version.default = {ver!r} (ожидался тег vX.Y.Z)")
        return 1

    rel = Path(a.release_dir).resolve() if a.release_dir else None
    if rel is not None:
        tar, sums = rel / f"kerna-dist-{ver}.tar.gz", rel / "SHA256SUMS"
        if not tar.exists() or not sums.exists():
            print(f"[!] в {rel} нет {tar.name} / SHA256SUMS — реальный прогон "
                  f"невозможен (сначала: make kerna-dist)")
            return 2
        print(f"[i] РЕАЛЬНЫЙ архив: {tar.name}, {tar.stat().st_size} Б, "
              f"sha256 {sha256_file(tar)[:16]}…")
    else:
        print("[i] вход: fake-релиз (труба действия; настоящий бинарь — make kerna-check)")

    fails = run_matrix(doc, ver, release_dir=rel)
    print(f"[{'FAIL' if fails else 'OK'}] action-check: провалов {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

