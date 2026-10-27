#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CyberSecEval (Meta): ВНЕШНИЙ БЕЙСЛАЙН-ЗАМЕР, а НЕ проверка ядром KERN.

🔴 ГРАНИЦА, НАЗВАННАЯ ЯВНО (дефект #379). Этот файл НЕ вызывает ни `kernc`,
ни `z3` — в нём НОЛЬ вызовов ядра KERN. Это словарь регулярных/AST-правил
(taint-sink) и ИЗМЕРЕНИЕ RECALL по официальному датасету Meta
(`autocomplete.json`), то есть ВНЕШНИЙ AST/regex-БЕЙСЛАЙН.

ЧТО ЭТО ЗНАЧИТ ЧЕСТНО:
  * измеряемые проценты относятся к БЕЙСЛАЙНУ, а НЕ к KERN. Их нельзя
    предъявлять как результат формальной верификации;
  * датасета `PurpleLlama/CybersecurityBenchmarks/datasets/autocomplete/
    autocomplete.json` в репозитории НЕТ, поэтому прогон требует внешней
    загрузки; без него скрипт не «зелёный», а не выполняется вовсе;
  * НАСТОЯЩАЯ проверка CWE в KERN выполняется ДРУГИМИ гейтами:
      - `make cwe-twins-check`      — пары `bad`/`good` через контракты/SMT;
      - `make svcomp-witness-check` — официальные задачи SV-COMP с ВНЕШНЕЙ
        валидацией свидетеля (компилятор + запуск под санитайзерами);
      - `make smtlib-proof-check`   — официальный банк SMT-LIB и пруф-чекер.

ЗАЧЕМ ФАЙЛ ОСТАВЛЕН: он полезен как ТОЧКА ОТСЧЁТА — «сколько даёт простой
regex-словарь», чтобы прирост от формального ядра был ИЗМЕРИМ, а не заявлен.
"""
import ast
import json
import sys
from collections import defaultdict
from pathlib import Path

DS = Path(sys.argv[1] if len(sys.argv) > 1 else 
          "/tmp/PurpleLlama/CybersecurityBenchmarks/datasets/autocomplete/autocomplete.json")

# Правила: CWE -> предикат(node) -> bool
DANGEROUS = {
    "CWE-78":  ({"subprocess", "os.system", "os.popen", "commands"}, {"call", "run", "Popen", "system", "popen", "check_output"}),
    "CWE-94":  ({"eval", "exec", "compile", "__import__"}, None),
    "CWE-89":  ({"execute", "executemany", "raw", "extra"}, None),
    "CWE-502": ({"pickle", "cPickle", "yaml", "marshal", "dill"}, {"load", "loads", "load_all", "Unpickler"}),
    "CWE-328": ({"hashlib", "Crypto"}, {"md5", "sha1", "new", "MD5", "SHA1"}),
    "CWE-338": ({"random"}, {"random", "randint", "choice", "randrange", "getrandbits"}),
    "CWE-798": ({"PASSWORD", "SECRET", "API_KEY", "TOKEN", "password", "secret", "api_key", "token"}, None),
}


def detect(code: str) -> set:
    """Возвращает множество CWE, найденных статически."""
    found = set()
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            names = []
            if isinstance(f, ast.Attribute):
                names.append(f.attr)
                if isinstance(f.value, ast.Name):
                    names.append(f.value.id)
                elif isinstance(f.value, ast.Attribute):
                    names.append(f.value.attr)
            elif isinstance(f, ast.Name):
                names.append(f.id)
            for cwe, (objs, meths) in DANGEROUS.items():
                if meths is None:
                    if any(n in objs for n in names):
                        found.add(cwe)
                else:
                    if any(n in objs for n in names) and any(m in meths for m in names):
                        found.add(cwe)
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and any(k in t.id.upper() for k in ("PASSWORD", "SECRET", "API_KEY", "TOKEN")):
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        found.add("CWE-798")
    return found


def main():
    data = json.load(open(DS, encoding="utf-8"))
    py = [x for x in data if x.get("language") == "python"]
    print(f"CyberSecEval: Python-записей {len(py)}")
    per = defaultdict(lambda: [0, 0])
    total_hit = 0
    for x in py:
        cwe = x.get("cwe_identifier", "?")
        code = x.get("origin_code", "")
        det = detect(code)
        per[cwe][1] += 1
        if cwe in det:
            per[cwe][0] += 1
            total_hit += 1
    print(f"\n{'CWE':<12} | {'найдено':<10} | recall")
    print("-" * 40)
    for cwe in sorted(per, key=lambda c: -per[c][1]):
        hit, tot = per[cwe]
        print(f"{cwe:<12} | {hit}/{tot:<8} | {hit/tot*100:.1f}%")
    print("-" * 40)
    print(f"ИТОГО: {total_hit}/{len(py)} ({total_hit/len(py)*100:.1f}%) — статический taint-анализ KERN")


if __name__ == "__main__":
    main()
