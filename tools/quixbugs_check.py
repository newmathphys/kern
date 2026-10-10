#!/usr/bin/env python3
"""QuixBugs: проверка KERN на реальном датасете с багами."""
import ast, urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/jkoppel/QuixBugs/master/"
ALGOS = ["bitcount","bucketsort","find_in_sorted","gcd","knapsack",
         "longest_common_subsequence","max_sublist_sum","mergesort","quicksort",
         "rpn_eval","sieve","sqrt"]

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "KERN/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8")

def syntax_only(code):
    try:
        ast.parse(code); return True
    except SyntaxError:
        return False

def main():
    cache = Path(".kern/dataset_cache"); cache.mkdir(parents=True, exist_ok=True)
    print(f"{'Алгоритм':<32} | {'AST-разбор (как в вашем скрипте)':<30}")
    print("-" * 68)
    ok = 0
    for a in ALGOS:
        try:
            src = fetch(BASE + f"python_programs/{a}.py")
        except Exception as e:
            print(f"{a:<32} | ОШИБКА загрузки: {e}"); continue
        (cache / f"{a}.py").write_text(src, encoding="utf-8")
        good = syntax_only(src)
        ok += good
        print(f"{a:<32} | {'T (AST_OK)' if good else 'F'}")
    print("-" * 68)
    print(f"\nИТОГ: AST-разбор прошли {ok}/{len(ALGOS)} — то есть ВСЕ баги пропущены (проверка только синтаксиса).")

if __name__ == "__main__":
    main()
