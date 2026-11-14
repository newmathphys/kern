#!/usr/bin/env python3
"""ТРЕК 1: двух-агентная «эхо-камера» флагманских LLM под судом KERN.

Схема очной ставки:
  Ход 1 (Модель A, «Автор»):   пишет реализацию по ТЗ.
  Ход 2 (Модель B, «Ревьюер»): независимый промпт, выносит VERDICT: LGTM или BUG.
  Ход 3 (Суд KERN):            unittest + закон KERN (@kern:monotonic / conserves_sum /
                               non_negative / idempotent) или --diff-equiv против эталона.

Главная метрика: сколько раз ОБЕ модели согласились («LGTM» + зелёный unittest),
а KERN всё равно предъявил контрпример.

Ключ читается ТОЛЬКО из окружения или .env.local и НИКОГДА не печатается.
Без ключа стенд автоматически падает на локальный Ollama (честно помечая это в отчёте).

Запуск:
  set -a; . ./.env.local; set +a
  python3 tools/run_frontier_llm_trial.py \
      --model-a deepseek/deepseek-chat-v3-0324:free \
      --model-b meta-llama/llama-3.3-70b-instruct:free
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC_EN = ROOT / "docs" / "FRONTIER_PROOF.md"
DOC_RU = ROOT / "docs" / "FRONTIER_PROOF.ru.md"
EVID = ROOT / "docs" / "evidence" / "frontier_llm_raw.json"
sys.path.insert(0, str(ROOT / "tools"))

TASKS = [
    ("fee_split", "Распредели комиссию fee между двумя контрагентами так, чтобы ни один цент не терялся.",
     "def split_fee(fee):", "conserves_sum", "fee"),
    ("tier_ladder", "Сделай цену за количество неубывающей: больше штук не может стоить дешевле.",
     "def price(qty):", "monotonic", ""),
    ("tick_round", "Округли цену до шага тика так, чтобы повторное округление ничего не меняло.",
     "def to_tick(price):", "idempotent", ""),
    ("refund_parts", "Раздели возврат между двумя позициями; отрицательных сумм быть не может.",
     "def split_refund(paid, used):", "non_negative", ""),
]

P_A = ("Ты пишешь продакшн-код. Реализуй функцию по ТЗ. Верни ТОЛЬКО код на Python, "
       "без пояснений и без markdown.\n\nТЗ: {spec}\n\nНачни с этой строки: {sig}")
P_B = ("Ты ревьюер. Проверь код на математические ошибки, потерю денег и краевые случаи. "
       "Ответь ровно одной строкой: 'VERDICT: LGTM' или 'VERDICT: BUG' и кратко почему.\n\n"
       "ТЗ: {spec}\n\nКод:\n{code}")


def load_key() -> tuple[str, str]:
    """(provider, key) из окружения или .env.local. Ничего не печатаем."""
    envf = ROOT / ".env.local"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                name, val = line.split("=", 1)
                os.environ.setdefault(name.strip(), val.strip().strip("\"'"))
    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter", os.environ["OPENROUTER_API_KEY"]
    if os.environ.get("GROQ_API_KEY"):
        return "groq", os.environ["GROQ_API_KEY"]
    return "ollama", ""


def ask(prompt: str, model: str, provider: str, key: str, timeout=180) -> tuple[str, float]:
    """Запрос с ретраями и экспоненциальным backoff (бесплатный тир даёт 429)."""
    t0 = time.time()
    last = ""
    for attempt in range(4):
        try:
            if provider == "ollama":
                body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                                   "options": {"temperature": 0.2, "num_predict": 500}}).encode()
                req = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=body,
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.loads(r.read()).get("response", ""), time.time() - t0
            url = ("https://openrouter.ai/api/v1/chat/completions" if provider == "openrouter"
                   else "https://api.groq.com/openai/v1/chat/completions")
            body = json.dumps({"model": model, "temperature": 0.2,
                               "messages": [{"role": "user", "content": prompt}]}).encode()
            req = urllib.request.Request(url, data=body,
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": f"Bearer {key}",
                                                  "HTTP-Referer": "https://github.com/newmathphys/kern",
                                                  "X-Title": "KERN echo chamber"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                js = json.loads(r.read())
            return js["choices"][0]["message"]["content"], time.time() - t0
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (429, 502, 503, 504):
                time.sleep(min(2 ** attempt * 3, 25))     # backoff: 3, 6, 12, 24 с
                continue
            return f"__ERROR__ {last}", time.time() - t0
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            time.sleep(2)
    return f"__ERROR__ {last}", time.time() - t0


def extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip() + "\n"



def kern_law(code: str, law: str, param: str) -> dict:
    """Суд KERN через ГЛАВНЫЙ CLI: макрос-закон на коде Модели A."""
    import ast as _ast
    import kern_tuple as KT
    t = _ast.parse(code)
    fn = next((n for n in t.body if hasattr(n, "name")), None)
    if fn is None:
        return {"status": "SKIP", "detail": "нет функции в ответе модели"}
    return KT.check_macro(code, fn.name, law, param)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-a", default="qwen2.5:3b")
    ap.add_argument("--model-b", default="qwen2.5:3b")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    provider, key = load_key()
    tasks = TASKS[:a.limit] if a.limit else TASKS
    print(f"[FRONTIER] провайдер={provider} | A={a.model_a} | B={a.model_b} | задач {len(tasks)}")
    rows, t0 = [], time.time()
    for name, spec, sig, law, param in tasks:
        raw_a, s_a = ask(P_A.format(spec=spec, sig=sig), a.model_a, provider, key)
        code = extract_code(raw_a)
        row = {"task": name, "law": law, "model_a_raw": raw_a[:3000],
               "code": code[:3000], "a_seconds": round(s_a, 1)}
        try:
            compile(code, "<model-a>", "exec")
            row["code_valid"] = True
        except SyntaxError:
            row["code_valid"] = False
        raw_b, s_b = ask(P_B.format(spec=spec, code=code), a.model_b, provider, key)
        row.update(model_b_raw=raw_b[:2000], b_seconds=round(s_b, 1),
                   b_lgtm=("VERDICT: LGTM" in raw_b.upper().replace("  ", " ")))
        verd = (kern_law(code, law, param) if row["code_valid"]
                else {"status": "SKIP", "detail": "код не компилируется"})
        row["kern"] = verd.get("status")
        row["kern_detail"] = verd.get("detail", "")
        row["echo_chamber"] = bool(row["b_lgtm"] and verd.get("status") == "CAUGHT")
        rows.append(row)
        print(f"  {name}: valid={row['code_valid']} B={'LGTM' if row['b_lgtm'] else 'BUG'} "
              f"KERN={row['kern']} echo={row['echo_chamber']}", flush=True)

    dt = time.time() - t0
    EVID.parent.mkdir(parents=True, exist_ok=True)
    EVID.write_text(json.dumps({"provider": provider, "model_a": a.model_a,
                                "model_b": a.model_b, "seconds": round(dt, 1),
                                "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    write_docs(rows, provider, a.model_a, a.model_b, dt)
    echo = sum(r["echo_chamber"] for r in rows)
    print(f"ИТОГ: задач {len(rows)} | код валиден {sum(r['code_valid'] for r in rows)} | "
          f"LGTM {sum(r['b_lgtm'] for r in rows)} | KERN поймал "
          f"{sum(r['kern'] == 'CAUGHT' for r in rows)} | ЭХО-КАМЕРА {echo}")
    return 0



def write_docs(rows, provider, ma, mb, dt):
    echo = [r for r in rows if r["echo_chamber"]]
    prov = ("локальный Ollama (ключ не задан — прогон НЕ про флагманов)" if provider == "ollama"
            else f"живой API: {provider}")
    head_en = ("# Frontier echo chamber: two LLMs vs the KERN gate\n\n"
               f"Provider: **{prov}**. Model A (author): `{ma}`. Model B (reviewer): `{mb}`.\n\n"
               "Loop: A writes the implementation, B reviews it and prints `VERDICT: LGTM` or\n"
               "`VERDICT: BUG`, then KERN judges the same code with a one-line law.\n\n"
               "**Headline metric — echo chamber: B said LGTM while KERN produced a counterexample.**\n\n")
    head_ru = ("# Эхо-камера флагманов: две LLM против шлюза KERN\n\n"
               f"Провайдер: **{prov}**. Модель A (автор): `{ma}`. Модель B (ревьюер): `{mb}`.\n\n"
               "Цикл: A пишет реализацию, B делает ревью и печатает `VERDICT: LGTM` или `BUG`,\n"
               "затем KERN судит тот же код законом одной строкой.\n\n"
               "**Главная метрика — эхо-камера: B сказала LGTM, а KERN предъявил контрпример.**\n\n")
    cols_en = ["Task", "Law", "A: code valid", "B: verdict", "KERN", "Echo chamber", "KERN says"]
    cols_ru = ["Задача", "Закон", "A: код валиден", "B: вердикт", "KERN", "Эхо-камера", "KERN говорит"]
    tail_en = ("## Honest limits\n\n"
               "LGTM from a reviewer is not proof of correctness, and a KERN `SKIP` is not an\n"
               "acquittal: it means the law could not be decided for that code.\n")
    tail_ru = ("## Честные границы\n\n"
               "LGTM ревьюера не является доказательством корректности, а `SKIP` от KERN — не\n"
               "оправдание: значит, закон для этого кода не решён.\n")
    for path, head, cols, tail, idx in ((DOC_EN, head_en, cols_en, tail_en, 0),
                                        (DOC_RU, head_ru, cols_ru, tail_ru, 1)):
        lines = [head, "| " + " | ".join(cols) + " |",
                 "|" + "|".join([":--"] * len(cols)) + "|"]
        for r in rows:
            yes = (lambda v: "yes" if v else "no") if idx == 0 else \
                  (lambda v: "да" if v else "нет")
            lines.append("| " + " | ".join([
                f"`{r['task']}`", f"`{r['law']}`", yes(r["code_valid"]),
                "LGTM" if r["b_lgtm"] else "BUG", str(r["kern"]), yes(r["echo_chamber"]),
                (r["kern_detail"] or "—").replace("|", "\\|")[:90]]) + " |")
        s = (f"**Result: {len(rows)} tasks, {len(echo)} echo-chamber agreements**, {dt:.0f} s."
             if idx == 0 else
             f"**Итог: {len(rows)} задач, {len(echo)} согласий эхо-камеры**, {dt:.0f} с.")
        lines += ["", s, "", tail]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
