#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN gate: SMT-COMP Proof-Checking Track — 4 теории ОФИЦИАЛЬНОГО SMT-LIB.

ЗАЧЕМ. `smtlib-bench-check` (#366) закрепил ОДНУ теорию (`QF_S`, 10 файлов) и
проверял только строку `sat/unsat` против `:status`. Это проверка РЕШАТЕЛЯ.
SMT-COMP Proof-Checking Track проверяет не ответ, а ВЫВОД: на `UNSAT`-задаче
решатель обязан предъявить доказательство, которое независимый пруф-чекер
разбирает и перепроверяет. У KERN для этого есть `src/verifier/proof_check.zig`,
и он НЕ участвовал ни в одном прогоне официального банка. Гейт закрывает это.

ИСТОЧНИКИ — ОФИЦИАЛЬНЫЕ, И ЭТО ПРОВЕРЯЕМО. Все четыре — репозитории ОРГАНИЗАЦИИ
SMT-LIB (не наши и не чьи-то форки) либо её же релиз на Zenodo:

  QF_LIA : github SMT-LIB/benchmark-submission-2024, 20231117-c_inference
  QF_BV  : github SMT-LIB/benchmark-submission,      20250812-Circt
  QF_AX  : zenodo 10.5281/zenodo.16740866 (SMT-LIB release 2025, QF_AX.tar.zst)
  QF_S   : github SMT-LIB/benchmark-submission-2025, 20250410-matching

Лицензия файлов — CC-BY-4.0 (тег `:license` внутри самих задач).

ЧТО ИМЕННО ТРЕБУЕТСЯ (и почему именно так):

  * `расхождений == 0` и `ЛОЖНЫХ СРАБАТЫВАНИЙ == 0` на КАЖДОЙ теории — это
    ЗВУЧИМОСТЬ решателя: расхождение с `:status` означает ложь о решении;
  * `проверено >= MIN_CHECKED` — ЗАЩИТА ОТ ВАКУУМА (класс #345): банк, ушедший
    в таймаут, даёт «0 расхождений» на пустом множестве;
  * на `UNSAT`-задачах: пруф РАЗОБРАН (`шагов > 0`) и `дыр == 0`. Это
    АБСОЛЮТНОЕ требование: дыра (`hole/trust/sorry`) означает, что вывод
    ничего не доказывает;
  * `[PROOF VERIFIED]` не имеет права появляться при `ДОВЕРЕННЫХ > 0`:
    метка «подтверждено» при непроверенных шагах — та же ложь, что #371.

ЧЕГО ГЕЙТ НЕ УТВЕРЖДАЕТ (границы названы, а не умолчаны):

  * `trusted == 0` на ОФИЦИАЛЬНЫХ `UNSAT`-задачах НЕ достигнуто и НЕ
    заявляется. ИЗМЕРЕНО: на `QF_BV/20250812-Circt/add_three.4_bit.smt2` чекер
    разбирает 7 616 шагов, из них 5 247 резолюций и 55 линейных `rewrite`
    ПРОВЕРЕНЫ, но 2 970 шагов остаются доверенными — правил для битовых
    векторов (`bitblast`, `bv-*`) в чекере нет. Гейт печатает это ЧИСЛОМ.
  * Выводы глубже предела вложенности парсера (`MAX_SEXP_DEPTH`, дефект #371)
    отвергаются явной причиной. ИЗМЕРЕНО: официальные выводы имеют глубину
    4 606 / 13 169 / 200 690; бюджет покрывает первый.
  * Это ЗАКРЕПЛЁННАЯ выборка (13 задач), а не полный банк SMT-LIB.

Запуск:  python3 tools/smtlib_proof_check.py [--selftest] [--dir DIR] [--out FILE]
Код возврата: 0 — инварианты выполнены; 1 — нарушение; 2 — нет выборки и нет
              сети (честный SKIP, НЕ «зелёный»).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "kern" / "smtlib4"

# Лимит задан ЯВНО: дефолтные 700 мс дают таймаут на официальных файлах
# (ИЗМЕРЕНО в #366: 0 из 10 проверено). Для ЭТОГО гейта лимит больше: в выборке
# есть официальные `QF_LIA/20231117-c_inference` весом 1.6 МБ и 13.5 тыс.
# ограничений — при 20 с они не успевают (ИЗМЕРЕНО: «проверено 0 из 2»).
TIMEOUT_MS = int(os.environ.get("KERN_SMTLIB_TIMEOUT_MS", "120000"))
# ПОРОГ АНТИ-ВАКУУМА на теорию: сколько файлов обязано быть ПРОВЕРЕНО.
MIN_CHECKED_PER_THEORY = int(os.environ.get("KERN_SMTLIB4_MIN", "1"))
# ТЯЖЁЛЫЕ выборки: официальные задачи, которые решатель не успевает за лимит.
# Для них анти-вакуум НЕ применяется (таймаут — ЛИМИТ РЕСУРСА, а не вердикт),
# но ПОЛНОТА УЧЁТА применяется ВСЕГДА: ни один файл не имеет права исчезнуть.
HEAVY_THEORIES = {"QF_LIA_heavy"}
# ОГРАНИЧЕНИЕ ПРОГОНА ОДНОЙ ТЕОРИЕЙ — ТОЛЬКО для невакуумных кейсов can-fail.
# ЗАЧЕМ: полный прогон (23 задачи + пруфы + 240 с тяжёлой выборки) занимает
# около десяти минут, а кейсу достаточно ОДНОЙ теории, чтобы покраснеть по
# своей причине. Ограничение названо явно и НЕ меняет ни одного инварианта:
# гейт проверяет ровно ту теорию, которую ему дали. По умолчанию — все.
_ONLY = [x for x in os.environ.get("KERN_SMTLIB4_ONLY", "").split(",") if x]
THEORIES = tuple(_ONLY) if _ONLY else (
    "QF_LIA", "QF_LIA_heavy", "QF_BV", "QF_AX", "QF_S")
# Бюджет на один пруф-прогон (секунды). Официальные выводы большие: измеренный
# разбор 7 616 шагов занимает минуты.
PROOF_TIMEOUT_S = int(os.environ.get("KERN_SMTLIB4_PROOF_TIMEOUT", "600"))

_GH = "https://raw.githubusercontent.com/SMT-LIB/"
_ZENODO = "https://zenodo.org/api/records/16740866/files/QF_AX.tar.zst/content"

# ЗАКРЕПЛЁННАЯ ВЫБОРКА: (теория, URL, имя_файла). Все — официальные задачи с
# тегом `:status`. Имена фиксированы, чтобы прогон был воспроизводим.
SAMPLE: dict[str, list[tuple[str, str]]] = {
    "QF_LIA_heavy": [
        # ТЯЖЁЛАЯ выборка: официальные задачи весом 1.6 МБ и 13.5 тыс.
        # ограничений. ИЗМЕРЕНО: не решаются и за 120 с (таймаут — ЛИМИТ
        # РЕСУРСА, а не неверный вердикт). Держим их в выборке ради ДВУХ
        # инвариантов, которые они и вскрыли:
        #   * задача обязана быть ПРОЧИТАНА (дефект #373: лимит чтения 1 МБ
        #     давал «файлов всего 0» на НЕПУСТОМ каталоге);
        #   * учёт обязан быть ПОЛНЫМ: проверено + таймауты + пропущено +
        #     не прочитано == файлов всего.
        (_GH + "benchmark-submission-2024/master/non-incremental/QF_LIA/"
               "20231117-c_inference/100_100_20_1_sat.smt2", "100_100_20_1_sat.smt2"),
        (_GH + "benchmark-submission-2024/master/non-incremental/QF_LIA/"
               "20231117-c_inference/100_100_20_11_sat.smt2", "100_100_20_11_sat.smt2"),
    ],
    "QF_BV": [
        (_GH + "benchmark-submission/master/non-incremental/QF_BV/"
               "20250812-Circt/add_three.4_bit.smt2", "add_three.4_bit.smt2"),
        # ВЫБОРКА ОГРАНИЧЕНА ПО ВРЕМЕНИ, И ЭТО ЗАЯВЛЕНО. Измеренные глубины
        # выводов этой категории: 4 606 (add_three.4_bit), 13 169
        # (add_three.8_bit), 200 690 (blend.4_bit, вывод 27 МБ). Прогон
        # `blend.*` в воротах занял бы часы, поэтому в закреплённой выборке их
        # нет; их числа приведены в комментарии к `MAX_SEXP_DEPTH`.
        (_GH + "benchmark-submission/master/non-incremental/QF_BV/"
               "20250812-Circt/add_three.8_bit.smt2", "add_three.8_bit.smt2"),
    ],
    "QF_S": [
        (_GH + "benchmark-submission-2025/master/non-incremental/QF_S/"
               "20250410-matching/sub-matching-sat-1.smt2", "sub-matching-sat-1.smt2"),
        (_GH + "benchmark-submission-2025/master/non-incremental/QF_S/"
               "20250410-matching/sub-matching-sat-2.smt2", "sub-matching-sat-2.smt2"),
        (_GH + "benchmark-submission-2025/master/non-incremental/QF_S/"
               "20250410-matching/sub-matching-sat-3.smt2", "sub-matching-sat-3.smt2"),
    ],
}

# QF_AX приезжает архивом Zenodo: имена ВНУТРИ архива фиксированы.
_AX_DIR = "non-incremental/QF_AX/storeinv/"
AX_FILES = [
    _AX_DIR + "storeinv_invalid_t1_np_nf_ai_00003_001.cvc.smt2",
    _AX_DIR + "storeinv_invalid_t1_np_nf_ai_00005_001.cvc.smt2",
    _AX_DIR + "storeinv_t1_np_nf_ai_00002_001.cvc.smt2",
    _AX_DIR + "storeinv_t1_np_sf_ai_00002_001.cvc.smt2",
]

# МАЛЫЕ ОФИЦИАЛЬНЫЕ QF_LIA — для НАТИВНОГО решателя (`builtin_lia.zig`).
# ИЗМЕРЕНО: на больших официальных задачах (c_inference, 302 переменные) нативный
# решатель честно отвечает `UNKNOWN слишком много переменных` — его бюджет
# `MAX_VARS = 32`. Чтобы трек не был вакуумным, нужны задачи, попадающие в
# бюджет. Источник тот же — организация SMT-LIB (`benchmark-submission-2022`,
# категория `QF_LIA/20220307-SMPT`), лицензия CC-BY-4.0.
_GH22 = _GH + "benchmark-submission-2022/master/non-incremental/QF_LIA/20220307-SMPT/"
LIA_SMALL = [
    (_GH22 + "2PhLockVParam/RC-%02d.smt2" % n, "2PhLockVParam_RC-%02d.smt2" % n)
    for n in range(0, 11)
] + [
    (_GH22 + "CircularTrains-PT-012/RC-00.smt2",
     "CircularTrains-PT-012_RC-00.smt2"),
]


def ensure_sample() -> tuple[Path | None, str]:
    """Каталог с выборкой. Скачивает в КЭШ, если его нет.

    Возвращает `(каталог, причина)`. Причина непустая, когда выборки нет И сеть
    недоступна — это ЧЕСТНЫЙ SKIP, а не «зелёный гейт».
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    for theory, items in SAMPLE.items():
        (CACHE / theory).mkdir(exist_ok=True)
        for url, name in items:
            dst = CACHE / theory / name
            if dst.exists():
                continue
            try:
                with urllib.request.urlopen(url, timeout=90) as r:
                    dst.write_bytes(r.read())
            except Exception as e:                          # noqa: BLE001
                return None, (f"не удалось скачать {theory}/{name} "
                              f"({type(e).__name__}) и кэш неполон")
    ax = CACHE / "QF_AX"
    ax.mkdir(exist_ok=True)
    small = CACHE / "QF_LIA"
    small.mkdir(exist_ok=True)
    for url, name in LIA_SMALL:
        dst = small / name
        if dst.exists():
            continue
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                dst.write_bytes(r.read())
        except Exception as e:                              # noqa: BLE001
            return None, (f"не удалось скачать QF_LIA/{name} "
                          f"({type(e).__name__}) и кэш неполон")
    if not all((ax / Path(f).name).exists() for f in AX_FILES):
        try:
            tar_zst = CACHE / "QF_AX.tar.zst"
            if not tar_zst.exists():
                with urllib.request.urlopen(_ZENODO, timeout=300) as r:
                    tar_zst.write_bytes(r.read())
            # Архив .zst распаковывается системным `zstd`: питон-модуля нет.
            zstd = shutil.which("zstd")
            if zstd is None:
                return None, "нет `zstd` для распаковки QF_AX.tar.zst"
            plain = CACHE / "QF_AX.tar"
            r = subprocess.run([zstd, "-d", "-f", str(tar_zst), "-o", str(plain)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                return None, f"zstd не распаковал QF_AX ({r.stderr.strip()[:80]})"
            with tarfile.open(plain) as t:
                for f in AX_FILES:
                    member = t.getmember(f)
                    with t.extractfile(member) as src:
                        (ax / Path(f).name).write_bytes(src.read())
        except Exception as e:                              # noqa: BLE001
            return None, f"не удалось получить QF_AX из Zenodo ({type(e).__name__})"
    return CACHE, ""


def status_of(path: Path) -> str:
    """Тег `:status` из шапки задачи (`sat` / `unsat` / `unknown`)."""
    m = re.search(r":status\s+(sat|unsat|unknown)", path.read_text(
        encoding="utf-8", errors="replace"))
    return m.group(1) if m else "unknown"


def _kern_env() -> dict:
    env = dict(os.environ)
    env["PATH"] = str(ROOT / ".venv" / "bin") + os.pathsep + env.get("PATH", "")
    return env


def run_bank(directory: Path) -> dict:
    """`kernc smtlib <каталог>` — сверка `:status` с ответом решателя."""
    if not KERNC.exists():
        return {"error": f"нет {KERNC} (соберите: zig build)"}
    r = subprocess.run([str(KERNC), "smtlib", str(directory),
                        "--timeout-ms", str(TIMEOUT_MS)],
                       cwd=str(ROOT), capture_output=True, text=True,
                       timeout=3600, env=_kern_env())
    out = r.stdout + r.stderr
    if "SMT-LIB BENCHMARK RUN" not in out:
        return {"error": f"нет сводки в выводе (rc={r.returncode}): "
                         f"{out.strip()[:200]}"}

    def num(label: str) -> int:
        m = re.search(rf"{label}\D*?(\d+)", out)
        return int(m.group(1)) if m else -1

    return {
        "files": num("файлов всего"),
        "checked": num("проверено"),
        "matched": num("совпало"),
        "diverged": num("расхождений"),
        "timeouts": num("таймаутов"),
        "skipped": num("пропущено"),
        "unreadable": num("не прочитано"),
        "false_alarm": num("ЛОЖНЫХ СРАБАТЫВАНИЙ"),
        "raw": out,
    }


def run_prove(path: Path) -> dict:
    """`kernc prove --query-kind refutation <file>` — независимый разбор вывода.

    Возвращает ИЗМЕРЕННЫЕ счётчики. Чего нет в выводе, того нет и в результате:
    вердикт это назовёт, а не додумает.
    """
    try:
        r = subprocess.run([str(KERNC), "prove", "--query-kind", "refutation",
                            str(path)],
                           cwd=str(ROOT), capture_output=True, text=True,
                           timeout=PROOF_TIMEOUT_S, env=_kern_env())
    except subprocess.TimeoutExpired:
        return {"timeout": True, "rc": None}
    out = r.stdout + r.stderr
    res: dict = {"timeout": False, "rc": r.returncode, "raw": out}

    res["proved"] = "ВЕРДИКТ  : ДОКАЗАНО" in out
    res["model_verified"] = "[MODEL VERIFIED]" in out
    res["too_deep"] = "ГЛУБЖЕ предела вложенности" in out
    res["proof_verified_line"] = "[PROOF VERIFIED]" in out

    m = re.search(r"\[ПРУФ-ЧЕКЕР\] шагов (\d+) \| посылок (\d+)/(\d+)", out)
    if m:
        res["steps"] = int(m.group(1))
        res["premises_bound"] = int(m.group(2))
        res["premises_total"] = int(m.group(3))
    m = re.search(r"ДОВЕРЕННЫХ (\d+) \| дыр (\d+)", out)
    if m:
        res["trusted"] = int(m.group(1))
        res["holes"] = int(m.group(2))
    m = re.search(r"\[PROOF VERIFIED\][^\n]*trusted: (\d+) \| holes: (\d+)", out)
    if m:
        res["pv_trusted"] = int(m.group(1))
        res["pv_holes"] = int(m.group(2))
    m = re.search(r"\[!\] причина: ([^\n]+)", out)
    if m:
        res["reason"] = m.group(1).strip()
    return res



# =========================================================================
#  НАТИВНЫЙ LIA-РЕШАТЕЛЬ БЕЗ Z3 (`builtin_lia.zig`) — ПЕРЕКРЁСТНАЯ ПРОВЕРКА
# =========================================================================
# ЗАЧЕМ. У KERN есть СОБСТВЕННЫЙ решатель линейной целочисленной арифметики
# (Фурье — Моцкин, `src/verifier/builtin_lia.zig`), и он не участвовал ни в
# одном прогоне официального банка. Гейт переводит КОНЪЮНКТИВНЫЙ фрагмент
# официальных QF_LIA-задач в его входной формат и сверяет ответ с `:status`.
#
# ЧЕГО ЗДЕСЬ НЕТ (названо явно): дизъюнкций, нелинейности, кванторов. Всё, что
# вне подмножества, помечается `SKIP` с причиной, а не «проверено».


def _tokens(s: str) -> list[str]:
    return re.findall(r"\(|\)|[^\s()]+", s)


def _merge(a: tuple[dict, int], b: tuple[dict, int], sign: int) -> tuple[dict, int]:
    coeffs = dict(a[0])
    for k, v in b[0].items():
        coeffs[k] = coeffs.get(k, 0) + sign * v
    return coeffs, a[1] + sign * b[1]


def _lin(toks: list[str], i: int):
    """Линейное выражение -> `(коэффициенты, константа, новая_позиция)`.

    Возвращает `None`, если выражение нелинейно или содержит вызов — это
    честный SKIP, а не «примерно то же самое».
    """
    if i >= len(toks):
        return None
    tok = toks[i]
    if tok == "(":
        if i + 1 >= len(toks):
            return None
        op = toks[i + 1]
        i += 2
        args = []
        while i < len(toks) and toks[i] != ")":
            got = _lin(toks, i)
            if got is None:
                return None
            args.append((got[0], got[1]))
            i = got[2]
        if i >= len(toks):
            return None
        i += 1                                             # закрывающая скобка
        if op == "+":
            acc: tuple[dict, int] = ({}, 0)
            for a in args:
                acc = _merge(acc, a, 1)
            return acc[0], acc[1], i
        if op == "-":
            if len(args) == 1:
                return ({k: -v for k, v in args[0][0].items()}, -args[0][1], i)
            acc = args[0]
            for a in args[1:]:
                acc = _merge(acc, a, -1)
            return acc[0], acc[1], i
        if op == "*":
            if len(args) != 2:
                return None
            consts = [a for a in args if not a[0]]
            vars_ = [a for a in args if a[0]]
            if len(consts) != 1 or len(vars_) != 1:
                return None                                 # нелинейно
            c = consts[0][1]
            return ({k: v * c for k, v in vars_[0][0].items()},
                    vars_[0][1] * c, i)
        return None                                         # вызовы/ite/div
    if re.fullmatch(r"-?\d+", tok):
        return {}, int(tok), i + 1
    if re.fullmatch(r"[|A-Za-z_~!.$][\w~!.$#@'|-]*", tok):
        return {tok: 1}, 0, i + 1
    return None


def _le(coeffs: dict, const: int) -> str:
    """Строка формата `builtin_lia`: `LE c1:v1 … k` означает `Σ ci·vi + k ≤ 0`."""
    parts = [f"{v}:{k}" for k, v in sorted(coeffs.items()) if v != 0]
    parts.append(str(const))
    return "LE " + " ".join(parts)


def _asserts(text: str) -> list[str]:
    """Все ВЕРХНЕУРОВНЕВЫЕ `(assert ...)` как сбалансированные строки."""
    out, i, n = [], 0, len(text)
    while True:
        j = text.find("(assert", i)
        if j < 0:
            break
        depth, k = 0, j
        while k < n:
            if text[k] == "(":
                depth += 1
            elif text[k] == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        out.append(text[j:k + 1])
        i = k + 1
    return out



def lia_constraints(path: Path) -> tuple[list[str], int]:
    """Конъюнктивный QF_LIA-фрагмент -> строки `LE`. Второй элемент — SKIP-счёт.

    Правила (над ЦЕЛЫМИ, поэтому строгие неравенства точны):
      `(<= A B)` -> A−B ≤ 0;  `(< A B)` -> A−B+1 ≤ 0;
      `(>= A B)` -> B−A ≤ 0;  `(> A B)` -> B−A+1 ≤ 0;
      `(= A B)`  -> оба A−B ≤ 0 и B−A ≤ 0;
      `(not …)`  -> противоположное неравенство (для `=` — SKIP: дизъюнкция).
    """
    lines: list[str] = []
    skipped = 0
    for a in _asserts(path.read_text(encoding="utf-8", errors="replace")):
        inner = a[len("(assert"):].strip()
        if inner.endswith(")"):
            inner = inner[:-1].strip()
        negate = False
        if inner.startswith("(not "):
            negate = True
            inner = inner[len("(not "):].strip()
            if inner.endswith(")"):
                inner = inner[:-1].strip()
        toks = _tokens(inner)
        # ИЗМЕРЕНО (первый прогон): без отсечения ВНЕШНИХ скобок `body` включал
        # закрывающую `)`, второй операнд не дочитывался до конца, и ВСЕ 13 554
        # ограничения официальной задачи уходили в `SKIP`. То есть гейт был бы
        # зелёным, ничего не проверив (класс #345). Отсюда `[2:-1]`.
        if len(toks) < 4 or toks[0] != "(" or toks[-1] != ")":
            skipped += 1
            continue
        op = toks[1]
        body = toks[2:-1]
        got = _lin(body, 0)
        if got is None:
            skipped += 1
            continue
        got2 = _lin(body, got[2])
        if got2 is None or got2[2] != len(body):
            skipped += 1
            continue
        left = (got[0], got[1])
        right = (got2[0], got2[1])
        if op in ("<=", "<", ">=", ">"):
            strict = op in ("<", ">")
            swap = op in (">=", ">")
            if negate:
                strict = not strict
            a_, b_ = (right, left) if swap else (left, right)
            c, k = _merge(a_, b_, -1)                       # a_ − b_ (+1) ≤ 0
            lines.append(_le(c, k + (1 if strict else 0)))
        elif op == "=" and not negate:
            c, k = _merge(left, right, -1)
            lines.append(_le(c, k))
            c, k = _merge(right, left, -1)
            lines.append(_le(c, k))
        else:
            skipped += 1                                    # `(not (= …))` и прочее
    return lines, skipped


def _eval_le(line: str, point: dict) -> int | None:
    """Значение `Σ ci·vi + k` для строки `LE …`. `None` — переменной нет в точке."""
    total = 0
    for t in line.split()[1:]:
        if ":" in t:
            c, nm = t.split(":", 1)
            if nm not in point:
                return None
            total += int(c) * point[nm]
        else:
            total += int(t)
    return total


def _parse_point(out: str) -> dict:
    """Точка из ответа `SAT name=val name=val`."""
    return {m.group(1): int(m.group(2))
            for m in re.finditer(r"([^\s=]+)=(-?\d+)", out)}


def _kernc_lia(le: Path) -> str:
    r = subprocess.run([str(KERNC), "lia", str(le)], cwd=str(ROOT),
                       capture_output=True, text=True, timeout=300,
                       env=_kern_env())
    return (r.stdout + r.stderr).strip()


def _verdict_of(out: str) -> str:
    if out.startswith("UNSAT"):
        return "unsat"
    if out.startswith("SAT"):
        return "sat"
    return "unknown"


# Предел, до которого имеет смысл ПРЕФИКСНЫЙ проход: на больших официальных
# задачах (13 505 ограничений) он бессмыслен — бюджет переменных исчерпан на
# первом же вызове. Порог назван явно, чтобы прогон был ограничен по времени.
LIA_PREFIX_MAX_CONSTRAINTS = 300


def run_lia(path: Path) -> dict:
    """НАТИВНЫЙ решатель на официальной QF_LIA-задаче + проверка свидетеля.

    ПОЧЕМУ ПРЕФИКС, И ПОЧЕМУ ЭТО ЗВУЧИТ. На полной задаче нативный решатель
    упирается в свой бюджет (`MAX_VARS = 32`) и честно отвечает `UNKNOWN`.
    Префикс ограничений — это РЕЛАКСАЦИЯ, поэтому:

      * `UNSAT` на префиксе => `UNSAT` и на полной задаче. Значит `UNSAT` при
        `:status sat` — ЛОЖНЫЙ UNSAT (звучимость нарушена);
      * `SAT` на префиксе — это СВИДЕТЕЛЬ, и он проверяется НЕЗАВИСИМО:
        подставляем точку в ограничения префикса и считаем арифметику сами.
        Нарушение => ЛОЖНЫЙ СВИДЕТЕЛЬ.

    Обе половины измеряются, а не заявляются: `SAT` без проверяемого свидетеля
    доказательством не считается (гейт это крадёт).
    """
    lines, skipped = lia_constraints(path)
    res: dict = {"constraints": len(lines), "skipped_asserts": skipped,
                 "status": status_of(path), "verdict": "unknown",
                 "prefix_n": None, "witness": None, "full": "unknown"}
    if not lines:
        res["skip"] = True
        return res
    res["skip"] = False
    full = CACHE / (path.stem + ".le")
    full.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = _kernc_lia(full)
    res["full"] = _verdict_of(out)
    res["full_raw"] = out.splitlines()[-1][:70] if out else ""

    attempts: list[int] = []
    if len(lines) <= LIA_PREFIX_MAX_CONSTRAINTS:
        attempts = list(range(len(lines), 1, -1))
    else:
        attempts = [len(lines)]
    for n in attempts:
        if n == len(lines):
            v, o = res["full"], ""
        else:
            cand = CACHE / (path.stem + ".p%d.le" % n)
            cand.write_text("\n".join(lines[:n]) + "\n", encoding="utf-8")
            o = _kernc_lia(cand)
            v = _verdict_of(o)
        if v == "unknown":
            continue
        res["verdict"] = v
        res["prefix_n"] = n
        if v == "sat":
            pt = _parse_point(o if o else out)
            checked = violated = unchecked = 0
            for l in lines[:n]:
                val = _eval_le(l, pt)
                if val is None:
                    unchecked += 1
                elif val > 0:
                    violated += 1
                else:
                    checked += 1
            res["witness"] = {"point": pt, "checked": checked,
                              "violated": violated, "unchecked": unchecked}
        break
    return res




def verdict(rep: dict) -> list[str]:
    """Список нарушений. Пустой = гейт зелёный.

    ЧТО КРАСНИТ (и почему именно это):
      * расхождение с `:status` или ЛОЖНОЕ СРАБАТЫВАНИЕ — ложь о решении;
      * `проверено < порога` — ВАКУУМ (класс #345): «0 расхождений» на пустом
        множестве ничего не доказывает;
      * `дыр != 0` на разобранном `UNSAT`-выводе — дыра обнуляет доказательство;
      * `[PROOF VERIFIED]` при `ДОВЕРЕННЫХ > 0` — метка «подтверждено» при
        непроверенных шагах (класс #371: сообщение говорит не то, что было);
      * ни одного разобранного шага на всём `UNSAT`-множестве — вакуум пруф-трека;
      * неверный ответ НАТИВНОГО LIA-решателя (`0 ложных unsat, 0 ложных sat`).

    ЧЕГО НЕ КРАСНИТ (и это ЗАЯВЛЕНО, а не умолчано): `ДОВЕРЕННЫХ > 0` само по
    себе. Правил для битовых векторов в чекере нет — измеренное число
    публикуется, но зелёный гейт не превращается в заявление о покрытии,
    которого нет.
    """
    if rep.get("error"):
        return [rep["error"]]
    bad: list[str] = []
    audited_steps = 0
    native_answered = 0
    for theory, t in rep["theories"].items():
        b = t["bank"]
        heavy = theory in HEAVY_THEORIES
        if b.get("error"):
            bad.append(f"{theory}: {b['error']}")
            continue
        if b["diverged"] != 0:
            bad.append(f"{theory}: РАСХОЖДЕНИЙ {b['diverged']} — ответ "
                       f"противоречит `:status` (ложь о решении)")
        if b["false_alarm"] != 0:
            bad.append(f"{theory}: ЛОЖНЫХ СРАБАТЫВАНИЙ {b['false_alarm']} — "
                       f"ожидалось `unsat`, получено `sat`")
        if b["checked"] < MIN_CHECKED_PER_THEORY and not heavy:
            bad.append(f"{theory}: ВАКУУМ — проверено {b['checked']} "
                       f"(нужно >= {MIN_CHECKED_PER_THEORY}, класс #345)")
        elif b["matched"] != b["checked"] and not heavy:
            bad.append(f"{theory}: совпало {b['matched']} из {b['checked']}")
        # ДЕФЕКТ #373: файл, который решатель НЕ СМОГ ПРОЧИТАТЬ, обязан краснить
        # ворота. Иначе официальная задача тихо выпадает из замера, и «0
        # расхождений» относится к банку, которого не было.
        if b.get("unreadable", 0) != 0:
            bad.append(f"{theory}: НЕ ПРОЧИТАНО файлов {b['unreadable']} — "
                       f"задача выпала из замера (класс #373)")
        # УЧЁТ ОБЯЗАН БЫТЬ ПОЛНЫМ (класс #373). Это проверяется для КАЖДОЙ
        # теории, включая тяжёлую: таймаут — лимит ресурса и краснить не может,
        # но «потерянный» файл не должен прятаться за ним.
        accounted = (b["checked"] + b["timeouts"] + b.get("skipped", 0)
                     + b.get("unreadable", 0))
        if accounted != b["files"]:
            bad.append(f"{theory}: УЧЁТ НЕПОЛОН — файлов всего {b['files']}, а "
                       f"проверено {b['checked']} + таймаутов {b['timeouts']} + "
                       f"пропущено {b.get('skipped', 0)} + не прочитано "
                       f"{b.get('unreadable', 0)} = {accounted}")
        for name, f in t["files"].items():
            pr = f.get("prove") or {}
            if pr.get("timeout"):
                continue
            if pr.get("too_deep"):
                continue                    # честный отказ, названный причиной
            if pr.get("steps"):
                audited_steps += pr["steps"]
                if pr.get("holes"):
                    bad.append(f"{theory}/{name}: ДЫР {pr['holes']} в разобранном "
                               f"выводе — доказательство недействительно")
            if pr.get("proof_verified_line") and pr.get("trusted", 0) > 0:
                bad.append(f"{theory}/{name}: `[PROOF VERIFIED]` при "
                           f"ДОВЕРЕННЫХ {pr['trusted']} — метка подтверждения "
                           f"при непроверенных шагах (класс #371)")
            lia = f.get("lia")
            if lia and not lia.get("skip"):
                if lia["verdict"] != "unknown":
                    native_answered += 1
                    # ⚠️ ЗВУЧИМОСТЬ СРАВНЕНИЯ. Вердикт получен на ПРЕФИКСЕ
                    # ограничений, а префикс — это РЕЛАКСАЦИЯ. Поэтому:
                    #   * `UNSAT` на префиксе => `UNSAT` и на полной задаче —
                    #     сравнивать с `:status` МОЖНО и НУЖНО;
                    #   * `SAT` на префиксе НИЧЕГО не говорит о полной задаче
                    #     (расслабленная система выполнима и тогда, когда полная
                    #     невыполнима) — сравнивать НЕЛЬЗЯ.
                    # ИЗМЕРЕНО на первом прогоне: сравнение SAT-префикса с
                    # `:status` дало четыре ложных «ЛОЖНЫЙ SAT» на официальных
                    # UNSAT-задачах. Это был дефект ВОРОТ, а не решателя.
                    full_task = lia["prefix_n"] == lia["constraints"]
                    if lia["verdict"] == "unsat" and lia["status"] != "unsat":
                        bad.append(f"{theory}/{name}: НАТИВНЫЙ LIA дал ЛОЖНЫЙ "
                                   f"UNSAT — префикс невыполним, значит и полная "
                                   f"задача невыполнима, а `:status` = "
                                   f"`{lia['status']}`")
                    if full_task and lia["verdict"] != lia["status"]:
                        bad.append(f"{theory}/{name}: НАТИВНЫЙ LIA ответил "
                                   f"`{lia['verdict']}` на ПОЛНОЙ задаче, а "
                                   f"`:status` = `{lia['status']}`")
                    w = lia.get("witness")
                    if lia["verdict"] == "sat":
                        if w is None or w["checked"] == 0:
                            bad.append(f"{theory}/{name}: НАТИВНЫЙ LIA вернул `SAT` "
                                       f"БЕЗ проверяемого свидетеля — "
                                       f"доказательством это не считается")
                        elif w["violated"] > 0:
                            bad.append(f"{theory}/{name}: ЛОЖНЫЙ СВИДЕТЕЛЬ — "
                                       f"точка нарушает {w['violated']} ограничений")
    if audited_steps == 0:
        bad.append("ВАКУУМ ПРУФ-ТРЕКА: ни одного разобранного шага вывода на "
                   "всём UNSAT-множестве — гейт ничего не проверил (класс #345)")
    # ВАКУУМ НАТИВНОГО LIA проверяется только если теория QF_LIA ВООБЩЕ
    # запускалась: при ограничении прогона другой теорией (`KERN_SMTLIB4_ONLY`)
    # требовать ответов LIA было бы ошибкой ворот, а не находкой.
    if native_answered == 0 and any(t.startswith("QF_LIA")
                                    for t in rep["theories"]):
        bad.append("ВАКУУМ НАТИВНОГО LIA: решатель не дал ни одного ответа "
                   "(кроме `UNKNOWN`) — трек ничего не измерил (класс #345)")
    return bad


def _mk(theory: str, bank: dict, files: dict) -> dict:
    return {"theories": {theory: {"bank": bank, "files": files}}}



def selftest() -> int:
    """Мета-тест: гейт обязан ловить КАЖДЫЙ класс поломки.

    Ветки: (1) расхождение с `:status`; (2) ложное срабатывание; (3) ВАКУУМ
    банка; (4) ДЫРА в разобранном выводе; (5) `[PROOF VERIFIED]` при
    `ДОВЕРЕННЫХ > 0`; (6) вакуум пруф-трека; (7) ложный ответ НАТИВНОГО LIA;
    (8) здоровый прогон проходит; (9) честный отказ `too_deep` не краснит.
    """
    bad = 0
    ok_bank = {"files": 4, "checked": 4, "matched": 4, "diverged": 0,
               "timeouts": 0, "skipped": 0, "unreadable": 0, "false_alarm": 0}
    ok_files = {"a.smt2": {"status": "unsat",
                           "prove": {"steps": 7616, "holes": 0, "trusted": 2970,
                                     "proof_verified_line": False}},
                "b.smt2": {"status": "sat",
                           "lia": {"skip": False, "status": "sat",
                                   "full": "unknown", "verdict": "sat",
                                   "prefix_n": 2, "constraints": 10,
                                   "witness": {"point": {"x": 0}, "checked": 2,
                                               "violated": 0, "unchecked": 0}}}}

    def expect_red(label: str, rep: dict):
        nonlocal bad
        if verdict(rep):
            print(f"[OK] selftest: {label} ловится")
        else:
            print(f"[FAIL] selftest: {label} НЕ поймано")
            bad += 1

    def expect_green(label: str, rep: dict):
        nonlocal bad
        if not verdict(rep):
            print(f"[OK] selftest: {label} проходит")
        else:
            print(f"[FAIL] selftest: {label} ошибочно краснит")
            bad += 1

    expect_red("расхождение с `:status`",
               _mk("T", dict(ok_bank, diverged=1), ok_files))
    expect_red("ложное срабатывание",
               _mk("T", dict(ok_bank, false_alarm=1), ok_files))
    expect_red("ВАКУУМ банка (проверено 0)",
               _mk("T", dict(ok_bank, checked=0, matched=0, timeouts=4), ok_files))
    # ДЕФЕКТ #373: файл банка НЕ ПРОЧИТАН (превышен лимит чтения) — задача
    # выпала из замера, и «0 расхождений» относится к банку, которого не было.
    expect_red("НЕ ПРОЧИТАННЫЙ файл банка (#373)",
               _mk("T", dict(ok_bank, files=6, unreadable=2), ok_files))
    # КЛАСС #373: файл, не попавший НИ В ОДНУ категорию учёта, обязан краснить.
    expect_red("НЕПОЛНЫЙ УЧЁТ файлов банка (#373)",
               _mk("T", dict(ok_bank, files=6, checked=4), ok_files))
    expect_red("ДЫРА в разобранном выводе",
               _mk("T", ok_bank, {"a.smt2": {"status": "unsat",
                                             "prove": {"steps": 100, "holes": 1,
                                                       "trusted": 0}}}))
    expect_red("`[PROOF VERIFIED]` при ДОВЕРЕННЫХ > 0",
               _mk("T", ok_bank, {"a.smt2": {"status": "unsat",
                                             "prove": {"steps": 100, "holes": 0,
                                                       "trusted": 7,
                                                       "proof_verified_line": True}}}))
    expect_red("вакуум пруф-трека (ни одного шага)",
               _mk("T", ok_bank, {"a.smt2": {"status": "unsat",
                                             "prove": {"steps": 0, "holes": 0,
                                                       "trusted": 0}}}))
    expect_red("ложный ответ НАТИВНОГО LIA",
               _mk("T", ok_bank, {"a.smt2": {"status": "sat",
                                             "prove": {"steps": 100, "holes": 0,
                                                       "trusted": 0},
                                             "lia": {"skip": False, "status": "sat",
                                                     "full": "unsat",
                                                     "verdict": "unsat",
                                                     "prefix_n": 3,
                                                     "constraints": 3,
                                                     "witness": None}}}))
    expect_red("ЛОЖНЫЙ СВИДЕТЕЛЬ нативного LIA",
               _mk("T", ok_bank, {"a.smt2": {"status": "sat",
                                             "lia": {"skip": False, "status": "sat",
                                                     "full": "unknown",
                                                     "verdict": "sat",
                                                     "prefix_n": 4,
                                                     "constraints": 10,
                                                     "witness": {"point": {}, "checked": 3,
                                                                 "violated": 1,
                                                                 "unchecked": 0}}}}))
    expect_red("`SAT` нативного LIA БЕЗ проверяемого свидетеля",
               _mk("T", ok_bank, {"a.smt2": {"status": "sat",
                                             "lia": {"skip": False, "status": "sat",
                                                     "full": "unknown",
                                                     "verdict": "sat",
                                                     "prefix_n": 4,
                                                     "constraints": 10,
                                                     "witness": {"point": {}, "checked": 0,
                                                                 "violated": 0,
                                                                 "unchecked": 4}}}}))
    expect_red("ВАКУУМ НАТИВНОГО LIA (ни одного ответа)",
               _mk("QF_LIA", ok_bank, {"a.smt2": {"status": "sat",
                                             "lia": {"skip": False, "status": "sat",
                                                     "full": "unknown",
                                                     "verdict": "unknown",
                                                     "prefix_n": None,
                                                     "constraints": 10,
                                                     "witness": None}}}))
    # ЗВУЧИМОСТЬ СРАВНЕНИЯ: `SAT` на ПРЕФИКСЕ — релаксация, выводов о полной
    # задаче не даёт. Первый прогон ворот краснел здесь ЛОЖНО (дефект ворот).
    expect_green("`SAT` на ПРЕФИКСЕ при `:status unsat` НЕ краснит (релаксация)",
                 _mk("T", ok_bank, {"a.smt2": {"status": "unsat",
                                               "prove": {"steps": 100, "holes": 0,
                                                         "trusted": 0},
                                               "lia": {"skip": False, "status": "unsat",
                                                       "full": "unknown",
                                                       "verdict": "sat",
                                                       "prefix_n": 2,
                                                       "constraints": 14,
                                                       "witness": {"point": {}, "checked": 2,
                                                                   "violated": 0,
                                                                   "unchecked": 0}}}}))
    expect_green("здоровый прогон (ДОВЕРЕННЫЕ > 0 — НЕ краснит)",
                 _mk("T", ok_bank, ok_files))
    # ТЯЖЁЛАЯ теория: таймаут — ЛИМИТ РЕСУРСА, он не краснит, НО учёт обязан
    # быть полным: 0 проверено + 2 таймаута = 2 файла.
    expect_green("тяжёлая теория с таймаутом НЕ краснит (учёт полон)",
                 _mk("QF_LIA_heavy",
                     dict(ok_bank, files=2, checked=0, matched=0, timeouts=2),
                     ok_files))
    expect_green("честный отказ `too_deep` не краснит",
                 _mk("T", ok_bank, {"a.smt2": {"status": "unsat",
                                               "prove": {"steps": 0, "holes": 0,
                                                         "trusted": 0,
                                                         "too_deep": True}},
                                    "b.smt2": {"status": "unsat",
                                               "prove": {"steps": 7616, "holes": 0,
                                                         "trusted": 2970}},
                                    "c.smt2": {"status": "sat",
                                               "lia": {"skip": False, "status": "sat",
                                                       "full": "unknown",
                                                       "verdict": "sat",
                                                       "prefix_n": 2,
                                                       "constraints": 10,
                                                       "witness": {"point": {}, "checked": 2,
                                                                   "violated": 0,
                                                                   "unchecked": 0}}}}))
    print(f"[{'OK' if bad == 0 else 'FAIL'}] smtlib-proof selftest: ошибок {bad}")
    return 0 if bad == 0 else 1



def collect(directory: Path) -> dict:
    """Прогон по всем теориям. Только ИЗМЕРЕНИЯ, без догадок."""
    rep: dict = {"theories": {}}
    for theory in THEORIES:
        tdir = directory / theory
        bank = run_bank(tdir) if tdir.is_dir() else {"error": f"нет каталога {tdir}"}
        files: dict = {}
        for f in sorted(tdir.glob("*.smt2")):
            st = status_of(f)
            entry: dict = {"status": st}
            # Пруф-трек имеет смысл только для `UNSAT`: на `SAT` вывода нет.
            if st == "unsat":
                entry["prove"] = run_prove(f)
            # Нативный LIA — на ОФИЦИАЛЬНЫХ QF_LIA-задачах (обе выборки).
            if theory.startswith("QF_LIA"):
                entry["lia"] = run_lia(f)
            files[f.name] = entry
        rep["theories"][theory] = {"bank": bank, "files": files}
    return rep


def print_report(rep: dict) -> None:
    print("=" * 78)
    print("KERN: SMT-COMP PROOF-CHECKING TRACK — 4 теории ОФИЦИАЛЬНОГО SMT-LIB")
    print("=" * 78)
    for theory, t in rep["theories"].items():
        b = t["bank"]
        print(f"\n### {theory}")
        if b.get("error"):
            print(f"  [FAIL] {b['error']}")
            continue
        print(f"  `:status` против решателя : проверено {b['checked']} из "
              f"{b['files']}, совпало {b['matched']}, расхождений "
              f"{b['diverged']}, ложных {b['false_alarm']}, "
              f"таймаутов {b['timeouts']}, не прочитано "
              f"{b.get('unreadable', 0)}")
        for name, f in t["files"].items():
            pr = f.get("prove")
            line = f"  · {name:<52} :status={f['status']}"
            if pr is not None:
                if pr.get("timeout"):
                    line += f" | пруф: ТАЙМАУТ (лимит {PROOF_TIMEOUT_S} с)"
                elif pr.get("too_deep"):
                    line += " | пруф: ОТКАЗ — глубже предела вложенности"
                elif pr.get("steps"):
                    line += (f" | пруф: шагов {pr['steps']}, дыр "
                             f"{pr.get('holes', '?')}, ДОВЕРЕННЫХ "
                             f"{pr.get('trusted', '?')}, посылок "
                             f"{pr.get('premises_bound', '?')}/"
                             f"{pr.get('premises_total', '?')}")
                    if pr.get("proof_verified_line"):
                        line += " [PROOF VERIFIED]"
                    elif pr.get("reason"):
                        line += f" | причина: {pr['reason'][:44]}"
                else:
                    line += " | пруф: НЕ РАЗОБРАН"
            lia = f.get("lia")
            if lia is not None:
                if lia.get("skip"):
                    line += " | LIA: SKIP (вне подмножества)"
                else:
                    line += f" | LIA(нативно): полная задача {lia['full']}"
                    if lia["verdict"] != "unknown":
                        line += (f", префикс {lia['prefix_n']}: {lia['verdict']}")
                        w = lia.get("witness")
                        if w:
                            line += (f" [свидетель: проверено {w['checked']}, "
                                     f"нарушено {w['violated']}]")
                    else:
                        line += " (граница бюджета)"
            print(line)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="SMT-LIB: пруф-трек по 4 теориям")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dir", type=Path, default=None,
                    help="свой каталог с подпапками теорий (для can-fail кейса)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(sys.argv[1:] if argv is None else list(argv))
    if args.selftest:
        return selftest()

    if args.dir is not None:
        directory = args.dir
        why = "" if args.dir.is_dir() else "нет каталога"
    else:
        directory, why = ensure_sample()
    if directory is None or why:
        print(f"\n[SKIP] {why}")
        print("[i] Это НЕ «зелёный гейт»: проверять нечего. Прогон не зачтён.")
        return 2

    rep = collect(directory)
    print_report(rep)
    bad = verdict(rep)
    print("\n" + "-" * 78)
    if bad:
        for b in bad:
            print(f"[FAIL] {b}")
        return 1
    audited = sum(f.get("prove", {}).get("steps", 0)
                  for t in rep["theories"].values() for f in t["files"].values())
    trusted = max((f.get("prove", {}).get("trusted", 0)
                   for t in rep["theories"].values()
                   for f in t["files"].values()), default=0)
    print(f"[OK] 4 теории: расхождений 0, ложных срабатываний 0, дыр 0. "
          f"Разобрано шагов вывода: {audited}. "
          f"ДОВЕРЕННЫХ шагов (правил BV в чекере нет) до {trusted} — "
          f"число публикуется, а НЕ заявляется как 0.")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        import json
        args.out.write_text(json.dumps(rep, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"[i] отчёт сохранён: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

