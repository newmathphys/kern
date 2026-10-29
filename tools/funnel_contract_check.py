#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the KERN Source License (see LICENSE).
"""ГЕЙТ: инварианты воронки `--xray` доказаны САМИМ KERN — и доказательство НЕ вакуумно.

ЧТО ПРОВЕРЯЕТСЯ (четыре свойства)
  1. ДОКАЗАНО. `tools/funnel_accounting.py` целиком проходит через
     `tools/kern_contracts.py` (Z3): все спецификации доказаны, ни одной
     нарушенной, ни одной НЕ РЕШЁННОЙ, ни одной ВАКУУМНОЙ, ни одной вне подмножества.
  2. НЕВАКУУМНОСТЬ. Ослабленный двойник ОБЯЗАН быть опровергнут — иначе
     «доказано» ничего не значит:
       (а) снята предпосылка `named <= skipped` → KERN обязан дать контрпример
           (это ровно та ошибка, из которой печаталось `-6`, дефект #407.2);
       (б) забыт `checked_arith_only` в `funnel_total` → KERN обязан дать
           контрпример (это ровно дефект #405: проверки без `if` спрятаны).
  3. ИНВАРИАНТЫ НА ИЗМЕРЕННЫХ ЧИСЛАХ. Корпуса пришпилены по SHA; на их
     измеренных числах остаток `unaccounted == 0`, `unexplained == 0`, а
     знаменатель равен `total - без_ветвлений`.
  4. ЗАМОК. `tools/funnel_accounting.py` запечатан в `docs/contracts.lock.json`
     И не изменён: ослабление контракта агентом ловит сам замок (`rc=2`).

ОТКАЗ ВМЕСТО ЛОЖНОЙ ЗЕЛЕНИ (дефект #407, класс #277). Если решателя нет, гейт
возвращает rc=3 и НИЧЕГО не объявляет зелёным: «инструмент не запущен» — это
N (нет данных), а не T (проверено). Каталог `.venv/bin` подхватывается рядом с
`sys.executable`, чтобы ручной прогон не зависел от PATH оболочки.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
KERNC = ROOT / "zig-out" / "bin" / "kernc"
SPEC = TOOLS / "funnel_accounting.py"
LOCK = ROOT / "docs" / "contracts.lock.json"
SPEC_REL = "tools/funnel_accounting.py"

# ИЗМЕРЕНО на `d98953c` (корпуса пришпилены по SHA: cmark-gfm 27d942c8,
# actions/toolkit 0c3a9c33). `checked_arith_only` и `trivial` пока НУЛЕВЫЕ:
# их разделение — шаг 2 плана (#405), и именно поэтому инвариант заперт ДО него.
CORPORA = (
    ("cmark-gfm/src", {"total": 308, "without_if": 126, "checked_branches": 76,
                       "checked_arith_only": 0, "trivial": 0, "skipped": 232,
                       "named": 232}),
    ("toolkit/packages", {"total": 458, "without_if": 337, "checked_branches": 58,
                          "checked_arith_only": 0, "trivial": 0, "skipped": 400,
                          "named": 400}),
)

# РОВНО ТО СОСТОЯНИЕ, КОТОРОЕ НАПЕЧАТАЛО `-6`: 9 функций, 15 «причин».
MIXED_UNITS = (9, 15)

# Настоящая строка ИТОГО — ДОСЛОВНО скопирована из вывода `kern_contracts.py`
# (а не переписана руками: переписанный образец повторил бы ошибку шаблона и
# самопроверка стала бы вакуумной).
REAL_ITOGO = ("ИТОГО: доказано 4 | T_advisory 0 | нарушено 0 (из них безопасность: 0) | "
              "НЕ РЕШЕНО 0 | ЛОЖНЫХ ТРЕВОГ 0 | ВАКУУМНЫХ 0 | вне подмножества 0 | всего 4")

ITOGO = {
    "proven": re.compile(r"доказано (\d+)"),
    "violated": re.compile(r"нарушено (\d+)"),
    "unknown": re.compile(r"НЕ РЕШЕНО (\d+)"),
    # ХВОСТ «МНЫХ», А НЕ ПОЛНОЕ СЛОВО — намеренно. Удвоенная «У» в слове
    # ВАКУУМНЫХ один раз была прочитана как одна и дала ложный FAIL: шаблон не
    # разбирал ключ, и ДОКАЗАННАЯ спецификация объявлялась недоказанной.
    # Собственный образец (REAL_ITOGO) содержал ту же ошибку, поэтому
    # самопроверка её не увидела — образец обязан быть ДОСЛОВНЫМ выводом.
    "vacuous": re.compile(r"МНЫХ (\d+)"),
    "outside": re.compile(r"вне подмножества (\d+)"),
    "total": re.compile(r"всего (\d+)"),
}


def _env() -> dict:
    """PATH с каталогом решателя, найденным РЯДОМ с sys.executable (дефект #407).

    Без этого ручной прогон в оболочке без `.venv/bin` даёт «находок 0» —
    то есть инструмент, который не запустился, выглядит как чистый код.
    """
    env = dict(os.environ)
    cands = [Path(sys.executable).resolve().parent, ROOT / ".venv" / "bin"]
    have = [str(p) for p in cands if (p / "z3").exists()]
    if have:
        env["PATH"] = os.pathsep.join(have + [env.get("PATH", "")])
    return env


def _run(args: list) -> tuple:
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                       check=False, env=_env())
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def solver_unavailable() -> bool:
    """Решатель есть? Тривиальный запрос: ответ «z3 недоступен» = N, не T."""
    smt = ROOT / "zig-out" / "bin"
    probe = "(set-logic ALL)\n(declare-const x Int)\n(assert (= x 0))\n(check-sat)\n"
    tmp = Path(tempfile.mkdtemp()) / "probe.smt2"
    tmp.write_text(probe, encoding="utf-8")
    _rc, out = _run([str(KERNC), "prove", str(tmp)])
    _ = smt
    low = out.lower()
    return "z3 недоступен" in low or "z3 is not" in low


def verdicts(out: str) -> dict:
    """Разобрать строку ИТОГО в ЧИСЛА (или пустой словарь, если строки нет)."""
    line = ""
    for ln in out.splitlines():
        if ln.startswith("ИТОГО:"):
            line = ln
    if not line:
        return {}
    got = {}
    for key, rx in ITOGO.items():
        m = rx.search(line)
        if m:
            got[key] = int(m.group(1))
    return got


def clean(v: dict, want_proven: int) -> bool:
    """Доказательство ЧИСТОЕ: ничего нарушенного, нерешённого, вакуумного, лишнего."""
    if not v:
        return False
    return (v.get("proven") == want_proven and v.get("violated") == 0
            and v.get("unknown") == 0 and v.get("vacuous") == 0
            and v.get("outside") == 0)


# ШАБЛОНЫ-ДВОЙНИКИ собираются из ЧАСТИ строки намеренно: критерий замка —
# аннотация в НАЧАЛЕ строки (CONTRACT_LINE, дефект #382), и шаблон, лишь
# выглядящий аннотацией внутри литерала, был бы объявлен незапечатанным
# контрактом. Двойник — ДАННЫЕ для проверки, а не контракт проекта.
_K = "# @kern:"

TWIN_NO_PRECONDITION = (
    "\n"
    + _K + "requires skipped >= 0 and named >= 0\n"
    + _K + "ensures result == skipped - named and result >= 0\n"
    + "def unexplained_skips(skipped: int, named: int) -> int:\n"
    + "    return skipped - named\n"
)

TWIN_FORGOTTEN_BUCKET = (
    "\n"
    + _K + "requires checked_branches >= 0 and checked_arith_only >= 0 and trivial >= 0 and skipped >= 0\n"
    + _K + "ensures result == checked_branches + checked_arith_only + trivial + skipped\n"
    + "def funnel_total(checked_branches: int, checked_arith_only: int, trivial: int,\n"
    + "                 skipped: int) -> int:\n"
    + "    return checked_branches + trivial + skipped\n"
)


def check() -> int:
    bad = 0
    if not KERNC.exists():
        print(f"[FAIL] нет {KERNC} — соберите: zig build")
        return 1
    if solver_unavailable():
        print("[!] решатель Z3 НЕДОСТУПЕН — это N (нет данных), а не зелёный результат (#407).")
        print("    Добавьте `.venv/bin` в PATH (uv pip install z3-solver) и повторите.")
        return 3

    # 1. ДОКАЗАНО
    n_specs = len(re.findall(r"^# @kern:ensures", SPEC.read_text(encoding="utf-8"), re.M))
    rc, out = _run([sys.executable, str(TOOLS / "kern_contracts.py"), str(SPEC)])
    v = verdicts(out)
    missing = [k for k in ITOGO if k not in v]
    if missing:
        # Ключ не разобран = шаблон разошёлся с выводом инструмента. Это НЕ
        # «ноль»: молча подставить 0 значило бы принять неизвестное за чистое.
        print(f"[FAIL] строка ИТОГО не разобрана: нет ключей {missing} (шаблон разошёлся с выводом)")
        bad += 1
    if rc != 0 or not clean(v, n_specs):
        print(f"[FAIL] спецификация воронки НЕ доказана (rc={rc}): {v}")
        for ln in out.splitlines():
            if "FAIL" in ln or "SKIP" in ln or "[PASS]" in ln:
                print("    " + ln.strip()[:150])
        bad += 1
    else:
        print(f"[OK] спецификация воронки ДОКАЗАНА: {v['proven']} функций, "
              f"нарушено 0, нерешённых 0, вакуумных 0, вне подмножества 0")

    # 2. НЕВАКУУМНОСТЬ: ослабленные двойники ОБЯЗАНЫ быть опровергнуты
    with tempfile.TemporaryDirectory() as td:
        for name, src in (("снята предпосылка `named <= skipped`", TWIN_NO_PRECONDITION),
                          ("забыт `checked_arith_only`", TWIN_FORGOTTEN_BUCKET)):
            t = Path(td) / "twin.py"
            t.write_text(src, encoding="utf-8")
            rc2, out2 = _run([sys.executable, str(TOOLS / "kern_contracts.py"), str(t)])
            v2 = verdicts(out2)
            if rc2 == 0 or v2.get("violated", 0) < 1 or "КОНТРПРИМЕР" not in out2:
                print(f"[FAIL] двойник НЕ опровергнут ({name}) — доказательство ВАКУУМНО (rc={rc2}, {v2})")
                bad += 1
            else:
                ce = next((ln.strip() for ln in out2.splitlines() if "КОНТРПРИМЕР" in ln), "")
                print(f"[OK] двойник опровергнут ({name}): {ce[:110]}")

    # 3. ИНВАРИАНТЫ НА ИЗМЕРЕННЫХ ЧИСЛАХ
    sys.path.insert(0, str(TOOLS))
    import funnel_accounting as F  # noqa: E402

    for name, c in CORPORA:
        den = F.branches_denominator(c["total"], c["without_if"])
        tot = F.funnel_total(c["checked_branches"], c["checked_arith_only"],
                             c["trivial"], c["skipped"])
        left = F.unaccounted(c["total"], c["checked_branches"],
                             c["checked_arith_only"], c["trivial"], c["skipped"])
        unexp = F.unexplained_skips(c["skipped"], c["named"])
        if tot != c["total"] or left != 0 or unexp != 0 or den != c["total"] - c["without_if"]:
            print(f"[FAIL] инвариант воронки нарушен на {name}: "
                  f"total={tot}/{c['total']}, остаток={left}, без причины={unexp}, знаменатель={den}")
            bad += 1
        else:
            print(f"[OK] {name}: знаменатель с ветвлениями {den}, корзины сходятся "
                  f"({c['checked_branches']}+{c['checked_arith_only']}+{c['trivial']}+{c['skipped']}={tot}), "
                  f"без причины {unexp}")

    # РОВНО ТО СОСТОЯНИЕ, ЧТО НАПЕЧАТАЛО `-6`: спецификация ОБЯЗАНА его отвергнуть.
    try:
        F.unexplained_skips(*MIXED_UNITS)
        print(f"[FAIL] спецификация ПРИНЯЛА смешанные единицы {MIXED_UNITS} — "
              f"именно так печаталось `-6` (#407.2)")
        bad += 1
    except ValueError as e:
        print(f"[OK] смешанные единицы {MIXED_UNITS} отвергнуты спецификацией: {str(e)[:80]}")

    # 4. ЗАМОК
    try:
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"[FAIL] замок не читается: {e}")
        return 1
    if SPEC_REL not in lock:
        print(f"[FAIL] {SPEC_REL} НЕ запечатан в {LOCK.name} — запустите `make contracts-lock`")
        bad += 1
    else:
        rc3, out3 = _run([sys.executable, str(TOOLS / "kern_contracts.py"),
                          "--verify-lock", str(LOCK), str(SPEC)])
        if rc3 != 0:
            print(f"[FAIL] замок контрактов нарушен (rc={rc3}):\n{out3.strip()[:400]}")
            bad += 1
        else:
            print(f"[OK] замок цел: {len(lock[SPEC_REL])} отпечатков контрактов "
                  f"{SPEC_REL} не изменены")

    if bad:
        print(f"\n[FAIL] воронка не защищена: расхождений {bad}")
        return 1
    print("\n[OK] ВОРОНКА ПОД КОНТРАКТОМ: доказана своим же движком, двойники опровергнуты, "
          "инварианты сходятся на измеренных числах, контракты запечатаны")
    return 0


def selftest() -> int:
    """Мета-тест: гейт обязан отвергать ПОДДЕЛКУ вердикта, а не только принимать свою."""
    bad = 0
    good = {"proven": 4, "violated": 0, "unknown": 0, "vacuous": 0, "outside": 0}
    if not clean(good, 4):
        print("[FAIL] мета-тест: чистый вердикт отвергнут")
        bad += 1
    for name, forgery in (("нарушено 1", {**good, "violated": 1}),
                          ("НЕ РЕШЕНО 1", {**good, "unknown": 1}),
                          ("ВАКУУМНЫХ 1", {**good, "vacuous": 1}),
                          ("вне подмножества 1", {**good, "outside": 1}),
                          ("доказано 3 из 4", {**good, "proven": 3})):
        if clean(forgery, 4):
            print(f"[FAIL] мета-тест: подделка «{name}» ПРИНЯТА за доказательство")
            bad += 1
    if verdicts("мусор без строки ИТОГО") != {}:
        print("[FAIL] мета-тест: парсер вердиктов выдумывает числа")
        bad += 1
    if not verdicts("ИТОГО: доказано 4 | нарушено 0 | НЕ РЕШЕНО 0 | ВАКУМНЫХ 0 | вне подмножества 0"):
        print("[FAIL] мета-тест: настоящая строка ИТОГО не разобрана")
        bad += 1
    # САМОПРОВЕРКА ШАБЛОНОВ: опечатка в ЛЮБОМ шаблоне обязана ронять мета-тест.
    # Именно так была найдена потерянная буква в слове «ВАКУМНЫХ»: гейт объявлял
    # доказанную спецификацию недоказанной, потому что ключ не разбирался.
    real = verdicts(REAL_ITOGO)
    missing = [k for k in ITOGO if k not in real]
    if missing:
        print(f"[FAIL] мета-тест: шаблон не разбирает настоящую строку ИТОГО — нет {missing}")
        bad += 1
    print(f"[{'OK' if bad == 0 else 'FAIL'}] funnel-contract selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    return check()


if __name__ == "__main__":
    sys.exit(main())
