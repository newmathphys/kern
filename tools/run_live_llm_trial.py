#!/usr/bin/env python3
"""Испытание №1: живой обстрел ЛОКАЛЬНОЙ нейросети (Ollama) шлюзом KERN.

Никаких заготовленных ответов и никаких внешних ключей: модель отвечает в реальном
времени локально (`qwen2.5:3b`), ответы сохраняются в `docs/evidence/live_<model>.json`
вместе с сырым текстом.

Задание А: «оптимизируй/упрости без изменения поведения» — проверяем базовым unittest
(типичные входы) И шлюзом `--diff-equiv` против оригинала.
Задание Б: «напиши unit-тесты» — прогоняем тесты и `--anti-cheat`.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLLAMA = "http://127.0.0.1:11434/api/generate"
DOC_EN = ROOT / "docs" / "LIVE_LLM_TRIAL.md"
DOC_RU = ROOT / "docs" / "LIVE_LLM_TRIAL.ru.md"
EVID = ROOT / "docs" / "evidence"

CORPUS = [
    ("clamp", "def clamp(x, lo, hi):\n    if x < lo:\n        return lo\n    if x > hi:\n        return hi\n    return x\n",
     "from target import clamp\nassert clamp(5, 0, 10) == 5\nassert clamp(-3, 0, 10) == 0\nassert clamp(99, 0, 10) == 10\n",
     "clamp(3, 5, 5)"),
    ("paginate", "def paginate(total, per_page):\n    pages = (total + per_page - 1) // per_page\n    last = total - (pages - 1) * per_page\n    return pages, last\n",
     "from target import paginate\nassert paginate(10, 3) == (4, 1)\nassert paginate(9, 3) == (3, 3)\n",
     "paginate(0, 10)"),
    ("fee_cents", "def fee_cents(amount_cents, rate_bp):\n    raw = amount_cents * rate_bp\n    return (raw + 5000) // 10000\n",
     "from target import fee_cents\nassert fee_cents(10000, 250) == 250\nassert fee_cents(20000, 100) == 200\n",
     "fee_cents(1, 1)"),
    ("discount", "def discount(price_cents, pct):\n    off = price_cents * pct // 100\n    return price_cents - off\n",
     "from target import discount\nassert discount(1000, 10) == 900\nassert discount(500, 50) == 250\n",
     "discount(999, 100)"),
    ("bin_index", "def bin_index(value, lo, hi, n):\n    if value < lo or value >= hi:\n        return -1\n    step = (hi - lo) / n\n    return int((value - lo) / step)\n",
     "from target import bin_index\nassert bin_index(5, 0, 10, 5) == 2\nassert bin_index(0, 0, 10, 5) == 0\n",
     "bin_index(10, 0, 10, 5)"),
    ("safe_div", "def safe_div(a, b):\n    if b:\n        return a // b\n    return 0\n",
     "from target import safe_div\nassert safe_div(10, 2) == 5\nassert safe_div(9, 3) == 3\n",
     "safe_div(-1, 2)"),
    ("moving_sum", "def moving_sum(values, i, window):\n    start = i - window + 1\n    if start < 0:\n        start = 0\n    total = 0\n    for k in range(start, i + 1):\n        total += values[k]\n    return total\n",
     "from target import moving_sum\nassert moving_sum([1, 2, 3, 4], 3, 2) == 7\nassert moving_sum([5, 5, 5], 1, 2) == 10\n",
     "moving_sum([1], 0, 1)"),
    ("tier_price", "def tier_price(qty):\n    if qty <= 0:\n        return 0\n    if qty < 10:\n        return qty * 100\n    if qty < 100:\n        return 1000 + (qty - 10) * 90\n    return 9100 + (qty - 100) * 80\n",
     "from target import tier_price\nassert tier_price(5) == 500\nassert tier_price(50) == 4600\nassert tier_price(200) == 17100\n",
     "tier_price(10)"),
    ("percent_change", "def percent_change(old, new):\n    return (new - old) * 100 // old if old else None\n",
     "from target import percent_change\nassert percent_change(100, 120) == 20\nassert percent_change(200, 100) == -50\n",
     "percent_change(0, 5)"),
    ("allocate", "def allocate(total, weights):\n    s = sum(weights)\n    parts = [total * w // s for w in weights]\n    rest = total - sum(parts)\n    return parts, rest\n",
     "from target import allocate\nassert allocate(100, [1, 1]) == ([50, 50], 0)\nassert allocate(90, [2, 1]) == ([60, 30], 0)\n",
     "allocate(100, [3, 3, 3])"),
]

P_REF = ("Ты оптимизируешь рабочий код. Перепиши функцию ниже короче и проще, "
         "НЕ меняя её поведение ни на каких входах. Верни ТОЛЬКО код функции на Python, "
         "без пояснений и без markdown.\n\n{code}")
P_TESTS = ("Напиши unit-тесты (unittest) для функции ниже. Верни ТОЛЬКО код тестов на "
           "Python, без пояснений и без markdown. Импортируй функцию из модуля `target`.\n\n{code}")


def sh(cmd, cwd=None, timeout=300):
    p = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True,
                       text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def ollama(prompt: str, model: str, timeout=240) -> tuple[str, float]:
    """Живой вызов локальной модели. Возвращает (текст, секунды)."""
    body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0.2, "num_predict": 400}}).encode()
    req = urllib.request.Request(OLLAMA, data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()).get("response", ""), time.time() - t0
    except Exception as e:  # noqa: BLE001
        return f"__OLLAMA_ERROR__ {e}", time.time() - t0



def extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    code = m.group(1) if m else text
    lines = [ln for ln in code.splitlines() if not ln.strip().startswith((">>>", "..."))]
    return "\n".join(lines).strip() + "\n"


def run_tests(d: Path, test_code: str, mod_code: str) -> tuple[bool, str]:
    """Прогон тестов модели. unittest.main() дописываем, только если тесты классовые:
    иначе `-m unittest` печатает «NO TESTS RAN» (rc=5) на модульных assert-ах —
    и зелёный прогон ложно считался бы падением (поймано на первом прогоне)."""
    (d / "target.py").write_text(mod_code, encoding="utf-8")
    tf = d / "test_target.py"
    body = test_code
    if "unittest" in body and "unittest.main" not in body:
        body += "\n\nif __name__ == '__main__':\n    unittest.main()\n"
    tf.write_text(body, encoding="utf-8")
    rc, out = sh([sys.executable, str(tf)], cwd=str(d), timeout=180)
    if "NO TESTS RAN" in out:
        return False, out
    return rc == 0, out


def kern(*args: str, timeout=300) -> str:
    rc, out = sh([sys.executable, str(ROOT / "tools" / "kern_contracts.py"), *args],
                 timeout=timeout)
    return out


def kern_equivalent(old: Path, new: Path) -> tuple[bool, str]:
    """--diff-equiv: доказал ли KERN эквивалентность (нет контрпримеров)."""
    out = kern("--diff-equiv", str(old), str(new))
    # Разбор ТОЛЬКО сводной строки: подстрочный поиск слова «эквивалент» ловил
    # «НЕ эквивалентен» и давал ЛОЖНУЮ эквивалентность (поймано на clamp).
    m = re.search(r"эквивалентных\D+(\d+).*?разошедшихся\D+(\d+)", out, re.S)
    if not m:
        return None, out
    e, d = int(m.group(1)), int(m.group(2))
    return (e > 0 and d == 0), out


def kern_anticheat(d: Path) -> tuple[int, str]:
    out = kern("--anti-cheat", str(d))
    m = re.search(r"находок\D{0,12}(\d+)", out)
    n = int(m.group(1)) if m else (1 if "НАРУШ" in out.upper() else 0)
    return n, out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen2.5:3b")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    model = a.model
    corpus = CORPUS[:a.limit] if a.limit else CORPUS

    tmp = Path(tempfile.mkdtemp(prefix="kern-live-"))
    rows, t0 = [], time.time()
    print(f"[LIVE] модель {model}, функций {len(corpus)}", flush=True)

    for name, code, base_test, edge in corpus:
        d = tmp / name
        d.mkdir(parents=True, exist_ok=True)
        orig = d / "orig.py"
        orig.write_text(code, encoding="utf-8")
        row: dict = {"name": name, "edge": edge}

        raw, secs = ollama(P_REF.format(code=code), model)
        new_code = extract_code(raw)
        row.update(refactor_seconds=round(secs, 1), refactor_raw=raw[:4000],
                   refactor_valid=False, baseline_green=False,
                   kern_equivalent=None, kern_says="")
        if "__OLLAMA_ERROR__" not in raw and new_code.strip():
            (d / "model.py").write_text(new_code, encoding="utf-8")
            rc, _ = sh([sys.executable, "-c",
                        f"import ast;ast.parse(open({str(d / 'model.py')!r}).read())"])
            row["refactor_valid"] = rc == 0
            if rc == 0:
                green, _o = run_tests(d, base_test, new_code)
                row["baseline_green"] = green
                eq, out = kern_equivalent(orig, d / "model.py")
                row["kern_equivalent"] = eq
                cex = [ln.strip() for ln in out.splitlines()
                       if "контрпример" in ln.lower() or "counterexample" in ln.lower()]
                tail = out.strip().splitlines()[-1] if out.strip() else ""
                row["kern_says"] = (cex[0] if cex else tail)[:300]

        raw_t, secs_t = ollama(P_TESTS.format(code=code), model)
        tests = extract_code(raw_t)
        row.update(tests_seconds=round(secs_t, 1), tests_raw=raw_t[:4000],
                   tests_valid=False, tests_pass=False, anticheat_findings=None)
        td = d / "tdir"
        td.mkdir(exist_ok=True)
        (td / "target.py").write_text(code, encoding="utf-8")
        (td / "test_gen.py").write_text(tests, encoding="utf-8")
        rc, _ = sh([sys.executable, "-c",
                    f"import ast;ast.parse(open({str(td / 'test_gen.py')!r}).read())"])
        row["tests_valid"] = rc == 0
        if rc == 0:
            ok, _o = sh([sys.executable, str(td / "test_gen.py")], cwd=str(td), timeout=180)
            row["tests_pass"] = ok == 0 and "NO TESTS RAN" not in _o
        n, out = kern_anticheat(td)
        row["anticheat_findings"] = n
        row["anticheat_says"] = (out.strip().splitlines() or [""])[-1][:200]

        rows.append(row)
        print(f"  {name}: ref valid={row['refactor_valid']} green={row['baseline_green']} "
              f"equiv={row['kern_equivalent']} | tests valid={row['tests_valid']} "
              f"pass={row['tests_pass']} ac={row['anticheat_findings']}", flush=True)

    dt = time.time() - t0
    EVID.mkdir(parents=True, exist_ok=True)
    EVID.joinpath(f"live_{model.replace(':', '_').replace('.', '')}.json").write_text(
        json.dumps({"model": model, "seconds": round(dt, 1), "rows": rows},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    write_docs(rows, model, dt)
    reg = sum(1 for r in rows if r["refactor_valid"])
    green = sum(1 for r in rows if r["baseline_green"])
    eq = sum(1 for r in rows if r["kern_equivalent"] is True)
    tvalid = sum(1 for r in rows if r["tests_valid"])
    ac = sum(1 for r in rows if (r["anticheat_findings"] or 0) > 0)
    print(f"ИТОГ: функций {len(rows)} | рефакторинг валиден {reg} | unittest зелёный {green} | "
          f"KERN эквивалентен {eq} | тесты валидны {tvalid} | anti-cheat {ac} | {dt:.0f} с")
    return 0



def write_docs(rows, model, dt):
    tagf = model.replace(":", "_").replace(".", "")
    reg = sum(1 for r in rows if r["refactor_valid"])
    green = sum(1 for r in rows if r["baseline_green"])
    eq = sum(1 for r in rows if r["kern_equivalent"] is True)
    jumped = sum(1 for r in rows if r["baseline_green"] and r["kern_equivalent"] is False)
    tvalid = sum(1 for r in rows if r["tests_valid"])
    ac = sum(1 for r in rows if (r["anticheat_findings"] or 0) > 0)
    n = len(rows)
    head_en = (f"# Live trial: local `{model}` against the KERN gate\n\n"
               f"{n} small pure functions (limits, fees, pagination, clamps, discounts, array\n"
               "bounds) were handed to a **local** model through Ollama. No API keys, no network,\n"
               "no canned answers: the raw text of every response is in\n"
               f"`docs/evidence/live_{tagf}.json`.\n\n"
               "**Task A** \u2014 \"optimize without changing behaviour\": the model's code is checked\n"
               "by a baseline unittest on *typical* inputs and by the KERN gate `--diff-equiv`\n"
               "against the original.\n\n"
               "**Task B** \u2014 \"write unit tests\": generated tests are executed and scanned by\n"
               "`--anti-cheat`.\n\n")
    head_ru = (f"# Живой обстрел: локальная `{model}` против шлюза KERN\n\n"
               f"{n} компактных чистых функций (лимиты, комиссии, пагинация, клэмпинг, скидки,\n"
               "границы массивов) отданы **локальной** модели через Ollama. Никаких ключей, сети\n"
               "и заготовленных ответов: сырой текст каждого ответа лежит в\n"
               f"`docs/evidence/live_{tagf}.json`.\n\n"
               "**Задание А** \u2014 «оптимизируй без изменения поведения»: код модели проверяется\n"
               "базовым unittest на *типичных* входах и шлюзом KERN `--diff-equiv` против\n"
               "оригинала.\n\n"
               "**Задание Б** \u2014 «напиши unit-тесты»: сгенерированные тесты исполняются и\n"
               "сканируются `--anti-cheat`.\n\n")
    cols_en = ["Function", "Edge not covered by tests", "Refactor valid", "unittest green",
               "KERN equivalent", "KERN says", "Tests valid", "Tests pass", "anti-cheat findings"]
    cols_ru = ["Функция", "Непокрытый край", "Рефакторинг валиден", "unittest зелёный",
               "KERN: эквивалентно", "KERN говорит", "Тесты валидны", "Тесты проходят",
               "находки anti-cheat"]
    tail_en = ("## What this shows\n\n"
               "The column that matters is **unittest green \u2229 KERN not equivalent**: a\n"
               "typical-input test suite passes while the gate still finds an input where\n"
               "behaviour changed. Those are exactly the edits a green CI would have merged.\n")
    tail_ru = ("## Что это показывает\n\n"
               "Главная колонка \u2014 **unittest зелёный \u2229 KERN не эквивалентен**: набор тестов\n"
               "на типичных входах зелёный, а шлюз всё равно находит вход с изменённым\n"
               "поведением. Именно такие правки зелёный CI пропустил бы в main.\n")
    for path, head, cols, tail, idx in ((DOC_EN, head_en, cols_en, tail_en, 0),
                                        (DOC_RU, head_ru, cols_ru, tail_ru, 1)):
        def yn(v, i=idx):
            return ("yes" if v else "no") if i == 0 else ("да" if v else "нет")
        lines = [head, "| " + " | ".join(cols) + " |",
                 "|" + "|".join([":--"] * len(cols)) + "|"]
        for r in rows:
            lines.append("| " + " | ".join([
                f"`{r['name']}`", f"`{r['edge']}`", yn(r["refactor_valid"]),
                yn(r["baseline_green"]),
                "\u2014" if r["kern_equivalent"] is None else yn(r["kern_equivalent"]),
                (r["kern_says"] or "\u2014").replace("|", "\\|")[:80],
                yn(r["tests_valid"]), yn(r["tests_pass"]),
                str(r["anticheat_findings"])]) + " |")
        if idx == 0:
            s = (f"**Result: {reg}/{n} refactors valid, {green} passed the baseline unittest, "
                 f"{eq} proven equivalent by KERN, {jumped} passed the unittest while KERN found "
                 f"a behaviour change; {tvalid}/{n} generated test files valid, {ac} with "
                 f"anti-cheat findings**, {dt:.0f} s.")
        else:
            s = (f"**Итог: {reg}/{n} рефакторингов валидны, {green} прошли базовый unittest, "
                 f"{eq} доказаны эквивалентными KERN, {jumped} прошли unittest, но KERN нашёл "
                 f"изменение поведения; {tvalid}/{n} файлов тестов валидны, {ac} с находками "
                 f"anti-cheat**, {dt:.0f} с.")
        lines += ["", s, "", tail]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
