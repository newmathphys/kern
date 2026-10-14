#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генерация сэмплов для ОФИЦИАЛЬНОГО EvalPlus через внешний API (OpenAI-совместимый).

Формат сэмпла: {"task_id": "HumanEval/N", "completion": "<продолжение>"}.
Полная программа = problem["prompt"] + completion.
"""
import argparse
import json
import os
import sys
import time
import urllib.request

BASE = os.environ.get("API_BASE", "")  # задайте API_BASE=<endpoint>/v1
KEY = os.environ.get("API_KEY", "")

SYS = ("You are an expert Python programmer. Complete the given function. "
       "Output ONLY the Python code (no markdown fences, no explanation).")


def _strip_leading_docstring(code: str) -> str:
    lines = code.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines):
        s = lines[i].lstrip()
        if s.startswith(chr(34)*3) or s.startswith(chr(39)*3):
            q = s[:3]
            if s.count(q) >= 2 and len(s) > 3:
                i += 1
            else:
                i += 1
                while i < len(lines) and q not in lines[i]:
                    i += 1
                i += 1
    return "\n".join(lines[i:])


def _extract_body(txt: str, entry: str, keep_def: bool = False) -> str:
    """Модель выдаёт размышления + код в markdown.

    HumanEval: промпт УЖЕ содержит `def f(...):` → нужен только ТЕЛО.
    MBPP:      промпт — только docstring → нужна ПОЛНАЯ функция с `def`.

    БАГ (найденный прогоном): без `keep_def` для MBPP срезалась сигнатура,
    сэмпл становился невалидным кодом и pass@1 падал в 0.000.
    """
    import re as _re
    blocks = _re.findall(r"```(?:python|py)?\s*(.*?)```", txt, _re.S)
    code = None
    for b in blocks:
        if entry in b:
            code = b
            break
    if code is None and blocks:
        code = max(blocks, key=len)
    if code is None:
        code = txt
    m = _re.search(r"^[ \t]*def\s+" + _re.escape(entry) + r"\s*\(", code, _re.M)
    if m and keep_def:
        # Оставляем функцию целиком, снимаем общий отступ.
        code = code[m.start():]
        lines = code.split("\n")
        indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
        base = min(indents) if indents else 0
        code = "\n".join(l[base:] if len(l) >= base else l for l in lines)
    elif m:
        code = code[m.end():]
        nl = code.find("\n")
        if nl != -1:
            code = code[nl + 1:]
        code = _strip_leading_docstring(code)
    return code.rstrip() + "\n"


def gen(model: str, prompt: str, entry: str, max_tokens: int,
        temperature: float, keep_def: bool = False) -> str:
    instr = ("# Верни ПОЛНУЮ функцию (с `def {e}(...)`) и её телом, без пояснений."
             .format(e=entry)) if keep_def else \
            "# Заверши функцию. Верни ТОЛЬКО тело функции (строки с отступом), без def и docstring."
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": prompt + "\n\n" + instr},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": 0.95,
        # ДЕФЕКТ #51 (найден при прогоне MBPP+): модели с РАССУЖДЕНИЕМ
        # (`nemotron-3.5-lightning`, reasoning-режим) тратят ВЕСЬ бюджет
        # max_tokens на поле `reasoning_content`, а `content` возвращают
        # `null` (finish_reason="length"). Инструмент падал с
        # `TypeError: 'NoneType' object is not subscriptable` -> все сэмплы
        # помечались ошибкой -> pass@1 = 0.000 (дефект ИНСТРУМЕНТА).
        # Отключаем «размышления» — модель отвечает кодом сразу.
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode("utf-8")
    req = urllib.request.Request(BASE + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read().decode("utf-8"))
    msg = d["choices"][0]["message"]
    txt = msg.get("content")
    if not txt:
        # Резерв: если провайдер всё равно ушёл в reasoning-режим, берём
        # `reasoning_content` (лучше частичный код, чем потерянный сэмпл),
        # и сообщаем об этом явно — молча терять сэмплы НЕЛЬЗЯ.
        txt = msg.get("reasoning_content") or ""
        if txt:
            print(f"[i] {entry}: content=null -> взят reasoning_content "
                  f"({len(txt)} б, finish={d['choices'][0].get('finish_reason')})",
                  file=sys.stderr, flush=True)
    if not txt:
        raise RuntimeError(
            f"пустой ответ модели (finish={d['choices'][0].get('finish_reason')}); "
            f"вероятно, весь бюджет ушёл в reasoning")
    return _extract_body(txt, entry, keep_def)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get("MODEL_NAME", ""))
    ap.add_argument("--dataset", default="humaneval", choices=["humaneval", "mbpp"])
    ap.add_argument("--out", default="samples_api.jsonl")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    from evalplus.data import get_human_eval_plus, get_mbpp_plus
    problems = get_human_eval_plus() if args.dataset == "humaneval" else get_mbpp_plus()
    ids = sorted(problems.keys())
    if args.limit:
        ids = ids[:args.limit]

    done = set()
    if os.path.exists(args.out):
        for line in open(args.out, encoding="utf-8"):
            try:
                done.add(json.loads(line)["task_id"])
            except Exception:
                pass

    print(f"[i] задач: {len(ids)}; готово: {len(done)}; модель: {args.model}; потоков: {args.workers}", flush=True)
    t0 = time.time()
    todo = [t for t in ids if t not in done]
    from concurrent.futures import ThreadPoolExecutor, as_completed
    ok = err = 0

    # MBPP: промпт — только docstring, нужна ПОЛНАЯ функция (иначе 0.000).
    keep_def = args.dataset == "mbpp"

    def work(tid):
        for attempt in range(4):  # РЕТРАИ (rate-limit 429 и сетевые сбои)
            try:
                return tid, gen(args.model, problems[tid]["prompt"], problems[tid].get("entry_point", ""),
                                args.max_tokens, args.temperature, keep_def)
            except Exception:
                time.sleep(2 * (attempt + 1))
        return tid, None

    with open(args.out, "a", encoding="utf-8") as f:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(work, t): t for t in todo}
            for i, fut in enumerate(as_completed(futs), 1):
                tid, comp = fut.result()
                if comp is None:
                    comp = ""
                    err += 1
                else:
                    ok += 1
                f.write(json.dumps({"task_id": tid, "completion": comp}) + "\n")
                f.flush()
                if i % 10 == 0:
                    print(f"  [{i}/{len(todo)}] ok={ok} err={err} t={time.time()-t0:.0f}s", flush=True)
    print(f"[OK] сэмплы в {args.out} (ok={ok}, err={err})", flush=True)


if __name__ == "__main__":
    main()
