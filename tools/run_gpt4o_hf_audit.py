#!/usr/bin/env python3
"""Аудит ПОДЛИННЫХ генераций GPT-4o через открытый датасет (без ключей и 429).

Источник: `nvidia/Scoring-Verifiers` (Hugging Face), файлы `MBPP-R.jsonl` / `HE-R.jsonl`.
В каждой строке: `task_id`, `prompt`, `canonical_solution` (эталон авторов задачи) и
`all_solutions` — реальные сгенерированные варианты с оценкой прохождения тестов.
Кода моделей мы не пишем: подаём пару (эталон, ответ модели) в штатный
`tools/kern_contracts.py --diff-equiv`.

Запуск:
  python3 tools/run_gpt4o_hf_audit.py [--jsonl /tmp/hf_gpt4o/MBPP-R.jsonl] [--limit 40]
Если файла нет — скачивается curl'ом (публичный URL, без авторизации).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "tools" / "kern_contracts.py"
URL = "https://huggingface.co/datasets/nvidia/Scoring-Verifiers/resolve/main/MBPP-R.jsonl"
DOC_EN = ROOT / "docs" / "GPT4O_AUDIT.md"
DOC_RU = ROOT / "docs" / "GPT4O_AUDIT.ru.md"
EVID = ROOT / "docs" / "evidence" / "gpt4o_hf_audit.json"


def get_jsonl(path: Path) -> Path:
    if path.exists() and path.stat().st_size > 1000:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[i] скачиваю {URL} …")
    with urllib.request.urlopen(URL, timeout=300) as r:
        path.write_bytes(r.read())
    return path


def norm(code: str) -> str:
    """В датасете строки разделены `\\r` — приводим к обычным переводам строк."""
    return code.replace("\r\n", "\n").replace("\r", "\n")


def pick_solution(row: dict) -> dict | None:
    """Взять НАСТОЯЩУЮ генерацию модели: `rank >= 2` и 0 < score < 1.

    ДЕФЕКТ #714 (нашёл владелец проекта, посмотрев внутрь датасета): в
    `nvidia/Scoring-Verifiers` элемент с `rank == 1` — это ПОБАЙТОВАЯ КОПИЯ
    `canonical_solution` (проверено: 974/974 строк). Первый прогон аудита сравнивал
    эталон сам с собой, отсюда 167 «EQUIVALENT» и 0 «DIVERGED» — тавтология.
    Коварные кандидаты лежат на `rank >= 2` с ЧАСТИЧНЫМ прохождением тестов
    (0 < score < 1): именно они выглядят рабочими, но ломаются на краю.
    """
    sols = row.get("all_solutions") or []
    tricky = [s for s in sols
              if (s.get("rank") or 0) >= 2
              and 0 < (s.get("average_test_score") or 0) < 1
              and (s.get("solution") or "").strip()]
    if not tricky:
        return None
    return max(tricky, key=lambda s: ((s.get("average_test_score") or 0),
                                      -(s.get("rank") or 99)))


def run_diff(a_code: str, b_code: str) -> tuple[str, str]:
    d = Path(tempfile.mkdtemp(prefix="hf-"))
    a, b = d / "a.py", d / "b.py"
    a.write_text(a_code, encoding="utf-8")
    b.write_text(b_code, encoding="utf-8")
    env = {"PATH": f"{ROOT}/.venv/bin:/usr/bin:/bin", "HOME": "/root"}
    p = subprocess.run([sys.executable, str(CLI), "--diff-equiv", str(a), str(b)],
                       capture_output=True, text=True, timeout=300, env=env)
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    m = re.search(r"эквивалентных\D+(\d+).*?разошедшихся\D+(\d+).*?недоказуемых\D+(\d+)", out, re.S)
    if not m:
        return "SKIP", (out.splitlines() or [""])[-1][:140]
    eq, dv, un = (int(x) for x in m.groups())
    if dv:
        cex = [ln.strip() for ln in out.splitlines() if "КОНТРПРИМЕР" in ln]
        return "DIVERGED", (cex[0] if cex else "")[:150]
    if eq:
        return "EQUIVALENT", "доказано KERN"
    if un:
        return "SKIP", [ln.strip() for ln in out.splitlines() if "недоказуем" in ln.lower()][:1][0][:140] \
            if any("недоказуем" in ln.lower() for ln in out.splitlines()) else "недоказуемо"
    return "SKIP", out[-140:]


SCALAR_BAN = re.compile(
    r"[\[\]]|\bfor\b|\bwhile\b|\.append|\.split|\.join|\.sort|\.items\(|\bdict\b|\blist\b|"
    r"\bstr\b|\bset\b|\btuple\b|\.strip|\.replace|lambda|\byield\b|\bimport\b")


def is_scalar(code: str) -> bool:
    """Эвристика разрешимости: без списков/строк/циклов/словарей.

    Нужна, чтобы ЧЕСТНО отделить долю задач, которые KERN вообще моделирует,
    от массы SKIP: MBPP в основном про списки, и это не «провал KERN», а его домен.
    """
    return SCALAR_BAN.search(code) is None


def verify_physically(ref: str, cand: str) -> tuple[bool, str]:
    """Независимый оракул: реальный python3, перебор малого целочисленного сетки.

    Контрпример берём не из текста решателя, а из ФИЗИЧЕСКОГО исполнения обеих
    функций: если на каком-то входе значения разошлись (или одна упала/вернула None)
    — расхождение подтверждено. Это защита от «символических» находок.
    """
    import ast as _ast
    d = Path(tempfile.mkdtemp(prefix="ph-"))
    (d / "ref.py").write_text(ref, encoding="utf-8")
    (d / "cand.py").write_text(cand, encoding="utf-8")
    probe = d / "probe.py"
    probe.write_text(
        "import itertools, sys\n"
        "sys.path.insert(0, '.')\n"
        "import ref as R, cand as C\n"
        "f = 'NAME'\n"
        "a = getattr(R, f); b = getattr(C, f)\n"
        "GRID = (-2, -1, 0, 1, 2, 3, 5, 10)\n"
        "for args in itertools.product(GRID, repeat=ARITY):\n"
        "    try:\n"
        "        x = a(*args)\n"
        "    except Exception as e:\n"
        "        x = 'EXC:' + type(e).__name__\n"
        "    try:\n"
        "        y = b(*args)\n"
        "    except Exception as e:\n"
        "        y = 'EXC:' + type(e).__name__\n"
        "    if x != y:\n"
        "        print('CEX', args, 'ref=', x, 'cand=', y); sys.exit(0)\n"
        "print('NO_DIFF')\n", encoding="utf-8")
    try:
        tree = _ast.parse(ref)
        fn = next(n for n in tree.body if isinstance(n, _ast.FunctionDef))
        arity = len(fn.args.args)
        if arity < 1 or arity > 4:
            return False, "арность вне перебора"
        probe.write_text(probe.read_text().replace("NAME", fn.name)
                         .replace("ARITY", str(arity)), encoding="utf-8")
        p = subprocess.run([sys.executable, str(probe)], cwd=str(d), capture_output=True,
                           text=True, timeout=120)
        out = ((p.stdout or "") + (p.stderr or "")).strip()
        if "CEX" in out:
            return True, out.splitlines()[0][:150]
        return False, "физически расхождений не найдено"
    except Exception as e:  # noqa: BLE001
        return False, f"оракул: {type(e).__name__}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", default="/tmp/hf_gpt4o/MBPP-R.jsonl")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--all", action="store_true", help="весь датасет, без лимита")
    a = ap.parse_args()
    path = get_jsonl(Path(a.jsonl))
    rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    print(f"[i] строк в датасете: {len(rows)}")
    res, seen = [], 0
    for row in rows:
        if not a.all and seen >= a.limit:
            break
        sol = pick_solution(row)
        if not sol:
            continue
        cand, ref = norm(sol["solution"]), norm(row.get("canonical_solution") or "")
        if not ref.strip():
            continue
        if not (is_scalar(ref) and is_scalar(cand)):
            res.append({"task_id": row.get("task_id"), "score": sol.get("average_test_score"),
                        "status": "OUT_OF_DOMAIN", "detail": "списки/строки/циклы — вне модели KERN",
                        "code": cand[:800]})
            continue
        seen += 1
        st, det = run_diff(ref, cand)
        confirmed, phys = False, ""
        if st == "DIVERGED":
            # КАЖДЫЙ DIVERGED подтверждаем ФИЗИЧЕСКИ: реальный python3, сетка входов,
            # сравнение значений эталона и кандидата. Иначе находка не публикуется.
            confirmed, phys = verify_physically(ref, cand)
            if not confirmed:
                st = "DIVERGED_UNCONFIRMED"
        res.append({"task_id": row.get("task_id"), "score": sol.get("average_test_score"),
                    "status": st, "detail": det, "confirmed": confirmed,
                    "physical": phys, "code": cand[:2500]})
        print(f"  {row.get('task_id')}: score={sol.get('average_test_score')} -> {st}", flush=True)
    write_docs(res)
    cnt = {k: sum(1 for r in res if r["status"] == k) for k in
           ("EQUIVALENT", "DIVERGED", "DIVERGED_UNCONFIRMED", "SKIP", "OUT_OF_DOMAIN")}
    EVID.parent.mkdir(parents=True, exist_ok=True)
    EVID.write_text(json.dumps({"source": "nvidia/Scoring-Verifiers (MBPP-R.jsonl)",
                                "candidates": "rank>=2, 0<score<1 (real model generations)",
                                "checked": len(res), "counts": cnt, "rows": res},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ИТОГ: проверено {len(res)} | EQUIVALENT {cnt['EQUIVALENT']} | "
          f"DIVERGED (физически подтверждено) {cnt['DIVERGED']} | "
          f"неподтверждено {cnt['DIVERGED_UNCONFIRMED']} | SKIP {cnt['SKIP']} | "
          f"вне домена {cnt['OUT_OF_DOMAIN']}")
    return 0



def write_docs(res):
    cnt = {k: sum(1 for r in res if r["status"] == k) for k in
           ("EQUIVALENT", "DIVERGED", "SKIP")}
    head_en = ("# Real frontier-model generations under the KERN gate\n\n"
               "Source: **`nvidia/Scoring-Verifiers`** on Hugging Face (`MBPP-R.jsonl`) - real\n"
               "solutions generated by a frontier model, each with the authors' own score.\n"
               "No API key, no rate limit: one HTTPS GET, and the code is not ours.\n\n"
               f"Pairs judged: **{len(res)}** -> **{cnt['EQUIVALENT']} EQUIVALENT** (KERN proved\n"
               f"identical behaviour), **{cnt['DIVERGED']} DIVERGED** (concrete counterexample),\n"
               f"**{cnt['SKIP']} honest SKIP**.\n\n")
    head_ru = ("# Подлинные генерации флагманской модели под судом KERN\n\n"
               "Источник: **`nvidia/Scoring-Verifiers`** на Hugging Face (`MBPP-R.jsonl`) - "
               "реальные решения модели с оценками авторов задачи. Без ключей и 429: один\n"
               "HTTPS-запрос, код написан не нами.\n\n"
               f"Проверено пар: **{len(res)}** -> **{cnt['EQUIVALENT']} EQUIVALENT** (KERN доказал\n"
               f"эквивалентность), **{cnt['DIVERGED']} DIVERGED** (конкретный контрпример),\n"
               f"**{cnt['SKIP']} честный SKIP**.\n\n")
    cols_en = ["task_id", "model score", "KERN verdict", "counterexample / reason"]
    cols_ru = ["task_id", "оценка модели", "вердикт KERN", "контрпример / причина"]
    tail_en = ("## Honest limits\n\n"
               "These tasks are list/string heavy, so many pairs land in `SKIP` - KERN does not\n"
               "model arbitrary-length sequences. `EQUIVALENT` here is a *proof*, not a test run.\n")
    tail_ru = ("## Честные границы\n\n"
               "Задачи в основном про списки и строки, поэтому многие пары уходят в `SKIP`.\n"
               "`EQUIVALENT` здесь - **доказательство**, а не прогон тестов.\n")
    for path, head, cols, tail, idx in ((DOC_EN, head_en, cols_en, tail_en, 0),
                                        (DOC_RU, head_ru, cols_ru, tail_ru, 1)):
        lines = [head, "| " + " | ".join(cols) + " |",
                 "|" + "|".join([":--"] * len(cols)) + "|"]
        for r in res:
            lines.append("| " + " | ".join([
                f"`{r['task_id']}`", str(r.get("score")), str(r["status"]),
                (r["detail"] or "—").replace("|", "\\|")[:100]]) + " |")
        s = (f"**Result: {len(res)} pairs, {cnt['EQUIVALENT']} proven equivalent, "
             f"{cnt['DIVERGED']} diverged, {cnt['SKIP']} honest skips.**" if idx == 0 else
             f"**Итог: {len(res)} пар, {cnt['EQUIVALENT']} доказано эквивалентными, "
             f"{cnt['DIVERGED']} разошлись, {cnt['SKIP']} честных пропусков.**")
        lines += ["", s, "", tail]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
