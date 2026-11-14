#!/usr/bin/env python3
"""ТРЕК 2: аудит арифметики денег и системных типов (без ключей, без сети).

Каждый кейс — формула из практики (ERC-4626, AMM, вестинг, комиссии, C11 promotion,
midpoint). Воспроизведены «наивные» реализации, которые проходят собственные тесты
разработчика на типичных числах, но на границе теряют/рождают копейку или переполняются.
Независимый оракул считает эксплойт точными числами.

ЧЕСТНО о происхождении: это НЕ выгрузка ответов GPT-4/Claude (такое утверждение
требовало бы сырых логов API). Это канонические формулировки из аудитов и бенчмарков;
проверяется математика, а не авторство.

Запуск: python3 tools/run_giants_audit.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC_EN = ROOT / "docs" / "GIANTS_AUDIT.md"
DOC_RU = ROOT / "docs" / "GIANTS_AUDIT.ru.md"
EVID = ROOT / "docs" / "evidence" / "giants_audit.json"

U8 = lambda v: v & 0xFF          # noqa: E731  — эмуляция uint8_t
U32 = lambda v: v & 0xFFFFFFFF   # noqa: E731  — эмуляция uint32_t

CASES: list[dict] = []


def case(cid, title, naive, tests, probe, expect, law, sphere):
    CASES.append(dict(id=cid, title=title, naive=naive, tests=tests,
                      probe=probe, expect=expect, law=law, sphere=sphere))


case("erc4626_inflation", "ERC-4626: первая доля за 1 wei обесценивает вклад следующего",
     "def shares_for(assets, total_assets, total_supply):\n"
     "    return assets * total_supply // total_assets if total_assets else assets\n",
     "assert shares_for(1000, 1000, 1000) == 1000\n",
     "t = dict(total_assets=1, total_supply=1)\n"
     "me = shares_for(1, 1, 1)\n"
     "t['total_assets'] = 1 + 10**18\n"
     "victim = shares_for(10**18, 1 + 10**18, 1 + me)\n"
     "print('атакующий=%d, жертва=%d' % (me, victim))\n"
     "ok = victim > 0\n",
     "жертва получает 0 долей за 2e18 активов", "conserves_sum", "DeFi")
case("fee_split_odd", "Деление комиссии на две части: нечётный цент исчезает",
     "def split(fee):\n    a = fee // 2\n    b = fee // 2\n    return a, b\n",
     "assert split(100) == (50, 50)\n",
     "lost = [fee - sum(split(fee)) for fee in (1, 3, 101)]\n"
     "print('потеряно на 1,3,101 копейках:', lost)\n"
     "ok = all(x == 0 for x in lost)\n",
     "1 цент теряется на каждой нечётной комиссии", "conserves_sum", "FinTech")
case("pool_weights", "Распределение пула по весам: остаток не возвращается",
     "def distribute(total, w):\n    s = sum(w)\n    return [total * x // s for x in w]\n",
     "assert distribute(100, [1, 1]) == [50, 50]\n",
     "parts = distribute(100, [3, 3, 3])\n"
     "print('роздано', sum(parts), 'из 100')\n"
     "ok = sum(parts) == 100\n",
     "остаток висит в контракте", "conserves_sum", "FinTech")
case("vesting_cliff", "Вестинг: округление вниз запирает 1 единицу навсегда",
     "def unlocked(total, elapsed, duration):\n    return total * elapsed // duration\n",
     "assert unlocked(1000, 500, 1000) == 500\n",
     "left = 1000 - unlocked(1000, 999, 1000)\n"
     "print('после 99.9% срока заперто:', left)\n"
     "ok = unlocked(1000, 1000, 1000) == 1000 and left >= 0\n",
     "1 единица заперта навсегда", "no_arbitrage", "DeFi")
case("amm_fee_evasion", "AMM-комиссия 0.3%: мелкие сделки платят ноль",
     "def fee_amount(amount, bps=30):\n    return amount * bps // 10000\n",
     "assert fee_amount(10000) == 30\n",
     "zoom = [fee_amount(a) for a in (1, 10, 333, 400)]\n"
     "print('комиссия с 1,10,333,400:', zoom)\n"
     "ok = all(x > 0 for x in zoom)\n",
     "сделки до 333 ед. не платят комиссию вовсе", "monotonic", "DeFi")
case("liq_intermediate_trunc", "Ликвидация: промежуточное отсечение меняет вердикт",
     "def is_liquidatable(collateral, price8, debt, thr_pct):\n"
     "    return (collateral * price8 // 10**8) * thr_pct // 100 < debt\n",
     "assert is_liquidatable(10**8, 1, 90, 100) is False\n",
     "print('вердикт на coll=1e8+1:', is_liquidatable(10**8 + 1, 1, 100, 100))\n"
     "ok = is_liquidatable(10**8 + 1, 1, 100, 100) is True\n",
     "позиция с достаточным обеспечением считается неликвидной", "monotonic", "DeFi")

case("c11_promotion", "C11 integer promotion: (uint8_t)0 - 1 == -1, а не 255",
     "def c11_sub(b):\n    return (U8(b) & 0xFF) - 1\n",
     "assert c11_sub(5) == 4\n",
     "v = c11_sub(0)\nprint('c11_sub(0) =', v, '| == 255:', v == 255)\nok = v >= 0\n",
     "индекс -1 при обратном приведении в uint8_t даёт 255", "bounded(0,255)", "Systems")
case("u32_midpoint", "midpoint на u32: (lo + hi) >> 1 переполняется на границе",
     "def midpoint(lo, hi):\n    return U32(lo + hi) >> 1\n",
     "assert midpoint(0, 10) == 5\n",
     "got = midpoint(2**31, 2**31)\nprint('midpoint =', got, 'ожидалось', 2**31)\nok = got == 2**31\n",
     "переполнение u32 -> неверный mid, бесконечный цикл", "no_overflow", "Systems")
case("banker_rounding", "Банковское округление Python против коммерческого полувверх",
     "def fee_round(x):\n    return round(x)\n",
     "assert fee_round(2.4) == 2\n",
     "print('round 0.5/1.5/2.5 =', fee_round(0.5), fee_round(1.5), fee_round(2.5))\n"
     "ok = (fee_round(0.5), fee_round(2.5)) == (1, 3)\n",
     ".5 уходит к чётному: 0.5->0, 2.5->2 — расхождение с кассой", "monotonic", "FinTech")
case("compound_trunc", "Сложный процент: отсечение на каждом периоде теряет деньги",
     "def compound(principal, rate_bp, periods):\n"
     "    p = principal\n    for _ in range(periods):\n"
     "        p += p * rate_bp // 10000\n    return p\n",
     "assert compound(10000, 100, 2) == 10201\n",
     "approx = compound(10000, 100, 12)\n"
     "exact = 10000 * (1 + 100 / 10000) ** 12\n"
     "print('точный %.2f, реализация %d, потеря %.2f' % (exact, approx, exact - approx))\n"
     "ok = abs(exact - approx) < 0.5\n",
     "на 12 периодах теряется заметная доля процента", "conserves_sum", "FinTech")
case("coupon_first_user", "Купоны: остаток достаётся первому — систематическая привилегия",
     "def coupon_split(pool, n):\n    each = pool // n\n    return [each] * n\n",
     "assert coupon_split(100, 4) == [25, 25, 25, 25]\n",
     "parts = coupon_split(103, 4)\nprint('роздано', sum(parts), 'из 103')\nok = sum(parts) == 103\n",
     "3 купона остаются в системе", "conserves_sum", "FinTech")
case("negative_floor", "Отрицательные суммы: // округляет вниз, а не к нулю",
     "def refund(paid, used, price):\n    return paid - used * price // 100\n",
     "assert refund(100, 10, 100) == 90\n",
     "print('refund(0,1,100) =', refund(0, 1, 100))\nok = refund(0, 1, 100) >= 0\n",
     "отрицательное списание возвращает деньги из воздуха", "bounded(0,10**9)", "FinTech")



def run_python(code: str, snippet: str, timeout=60):
    """Физический запуск: реальный интерпретатор, отдельный процесс."""
    d = Path(tempfile.mkdtemp(prefix="ga-"))
    prelude = "U8 = lambda v: v & 0xFF\nU32 = lambda v: v & 0xFFFFFFFF\n\n"
    epilogue = "\nprint('VERDICT', ok)\n" if "ok =" in snippet else ""
    (d / "m.py").write_text(prelude + code + "\n\n" + snippet + epilogue,
                            encoding="utf-8")
    p = subprocess.run([sys.executable, str(d / "m.py")], capture_output=True,
                       text=True, timeout=timeout)
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def kern_xray(code: str) -> tuple[str, str]:
    """KERN на коде кейса в режиме --xray (безаннотационно)."""
    d = Path(tempfile.mkdtemp(prefix="gak-"))
    f = d / "k.py"
    f.write_text(code, encoding="utf-8")
    env = {"PATH": f"{ROOT}/.venv/bin:/usr/bin:/bin", "HOME": "/root"}
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"),
                        "--xray", str(f)], capture_output=True, text=True,
                       timeout=300, env=env)
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    if "CRASH PATH" in out:
        v = "CRASH PATH"
    elif "findings 0" in out or not out:
        v = "нет находок"
    else:
        v = "находки"
    return v, (out.splitlines() or [""])[-1][:130]


def main() -> int:
    rows = []
    for c in CASES:
        rc_t, out_t = run_python(c["naive"], c["tests"])
        tests_green = rc_t == 0 and "Traceback" not in out_t
        _rc, out_p = run_python(c["naive"], c["probe"])
        verdict = out_p.split("VERDICT")[-1].strip() if "VERDICT" in out_p else ""
        exploited = verdict.startswith("False")
        v, det = kern_xray(c["naive"])
        rows.append({**c, "tests_green": tests_green, "probe_out": out_p[-500:],
                     "exploited": exploited, "kern": v, "kern_detail": det})
        print(f"  {c['id']}: tests={'green' if tests_green else 'red'} "
              f"exploit={'YES' if exploited else 'no'} kern={v}", flush=True)

    EVID.parent.mkdir(parents=True, exist_ok=True)
    EVID.write_text(json.dumps({"rows": [{k: r[k] for k in
                     ("id", "title", "sphere", "law", "tests_green", "exploited",
                      "kern", "probe_out")} for r in rows]}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    write_docs(rows)
    tg = sum(r["tests_green"] for r in rows)
    ex = sum(r["exploited"] for r in rows)
    both = sum(1 for r in rows if r["tests_green"] and r["exploited"])
    print(f"ИТОГ: кейсов {len(rows)} | тесты автора зелёные {tg} | эксплойт подтверждён {ex} "
          f"| ЗЕЛЁНО + ЭКСПЛОЙТ {both}")
    return 0


def write_docs(rows):
    both = [r for r in rows if r["tests_green"] and r["exploited"]]
    head_en = ("# Giants audit: money rounding and systems arithmetic\n\n"
               "Twelve canonical formulas from practice (ERC-4626, AMM, vesting, fee splits,\n"
               "C11 integer promotion, u32 midpoint). Each ships with the developer's own tests\n"
               "on typical numbers; a physical oracle then runs the same code with real numbers\n"
               "and shows the loss, the created money or the overflow.\n\n"
               "**Provenance note.** This is *not* a dump of GPT-4/Claude answers (that would\n"
               "require raw API logs). These are canonical formulations from audits and\n"
               "benchmarks; what is verified here is the arithmetic, not the authorship.\n\n")
    head_ru = ("# Аудит гигантов: округление денег и системная арифметика\n\n"
               "Двенадцать канонических формул из практики (ERC-4626, AMM, вестинг, деление\n"
               "комиссий, C11 integer promotion, midpoint на u32). К каждой — собственные тесты\n"
               "разработчика на типичных числах; затем физический оракул запускает тот же код на\n"
               "реальных числах и показывает потерю, рождение денег или переполнение.\n\n"
               "**О происхождении.** Это *не* выгрузка ответов GPT-4/Claude (для такого\n"
               "утверждения нужны сырые логи API). Это канонические формулировки из аудитов и\n"
               "бенчмарков; проверяется арифметика, а не авторство.\n\n")
    cols_en = ["Case", "Domain", "The trap", "Author's tests", "Oracle verdict", "KERN"]
    cols_ru = ["Кейс", "Домен", "Ловушка", "Тесты автора", "Вердикт оракула", "KERN"]
    tail_en = ("## What this proves, and what it does not\n\n"
               "Every row with a proven exploit has **green author's tests**: the tests are not\n"
               "wrong, they are blind to the edge. The KERN column is reported as measured —\n"
               "where `--xray` finds nothing, it says nothing.\n")
    tail_ru = ("## Что это доказывает, а что нет\n\n"
               "У каждой строки с доказанным эксплойтом **зелёные тесты автора**: тесты не\n"
               "ошибочны — они слепы к краю. Колонка KERN приводится как измерено: где `--xray`\n"
               "ничего не нашёл, там так и написано.\n")
    for path, head, cols, tail, idx in ((DOC_EN, head_en, cols_en, tail_en, 0),
                                        (DOC_RU, head_ru, cols_ru, tail_ru, 1)):
        lines = [head, "| " + " | ".join(cols) + " |",
                 "|" + "|".join([":--"] * len(cols)) + "|"]
        for r in rows:
            verdict = ("**exploit**" if r["exploited"] else "clean") if idx == 0 else \
                      ("**эксплойт**" if r["exploited"] else "чисто")
            tests = ("green" if r["tests_green"] else "red") if idx == 0 else \
                    ("зелёные" if r["tests_green"] else "красные")
            lines.append("| " + " | ".join([
                f"`{r['id']}`", r["sphere"], r["title"][:70].replace("|", "\\|"),
                tests, verdict, str(r["kern"])]) + " |")
        if idx == 0:
            s = (f"**Result: {len(rows)} cases, {sum(r['tests_green'] for r in rows)} with green "
                 f"author's tests, {len(both)} where the oracle proves an exploit behind green "
                 f"tests.**")
        else:
            s = (f"**Итог: {len(rows)} кейсов, {sum(r['tests_green'] for r in rows)} с зелёными "
                 f"тестами автора, {len(both)} где оракул доказывает эксплойт за зелёными тестами.**")
        lines += ["", s, "", tail]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

