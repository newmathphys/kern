#!/usr/bin/env python3
"""Двусторонний гейт `tuple-macros-check`: Tuple + 4 макрос-закона через ГЛАВНЫЙ CLI.

Проверяется именно `tools/kern_contracts.py` (то, чем пользуется человек и внешний
раннер), а не внутренний модуль. Все фикстуры материализуются в tempfile, а текст
директив склеивается как "# @" + "kern:..." — иначе `contracts-lock-check` принял бы
строки внутри tools/ за незапечатанные контракты репозитория.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "tools" / "kern_contracts.py"
AT = "# @" + "kern:"
fails = []


def run(cmd, timeout=300):
    p = subprocess.run([sys.executable, str(CLI), *cmd], capture_output=True,
                       text=True, timeout=timeout)
    return p.returncode, ((p.stdout or "") + (p.stderr or ""))


def write(d: Path, name: str, body: str) -> Path:
    f = d / name
    f.write_text(body, encoding="utf-8")
    return f


def expect(label: str, ok: bool, detail: str = ""):
    print(("  [OK] " if ok else "  [ПРОВАЛ] ") + label + (f" | {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="tmc-") as tmp:
        d = Path(tmp)
        # --- monotonic: реальный баг магазина (99 шт дороже 100)
        bad = write(d, "mono_bad.py",
                    f"{AT}monotonic\ndef price(qty):\n    if qty >= 100:\n        return qty * 80\n"
                    "    return qty * 100\n")
        good = write(d, "mono_good.py",
                     f"{AT}monotonic\ndef price_ok(qty):\n    if qty >= 100:\n"
                     "        return 10000 + (qty - 100) * 90\n    return qty * 100\n")
        rc, out = run([str(bad)])
        expect("monotonic: сломанная лестница -> CAUGHT + rc!=0",
               rc != 0 and "ОПРОВЕРГНУТО" in out and "КОНТРПРИМЕР" in out, out[-160:])
        expect("monotonic: контрпример подтверждён рантаймом",
               "runtime-confirmed" in out or "RUNTIME CONFIRMED" in out, out[-160:])
        rc, out = run([str(good)])
        expect("monotonic: честная лестница -> PROVEN + rc==0",
               rc == 0 and "ДОКАЗАНО" in out, out[-160:])

        # --- idempotent
        ib = write(d, "idem_bad.py", f"{AT}idempotent\ndef f(x):\n    return x + 1\n")
        ig = write(d, "idem_good.py",
                   f"{AT}idempotent\ndef g(x):\n    return x if x >= 0 else 0\n")
        rc, out = run([str(ib)])
        expect("idempotent: f(f(x))!=f(x) -> CAUGHT", rc != 0 and "ОПРОВЕРГНУТО" in out, out[-160:])
        rc, out = run([str(ig)])
        expect("idempotent: clamp -> PROVEN", rc == 0 and "ДОКАЗАНО" in out, out[-160:])

        # --- conserves_sum на кортеже
        cb = write(d, "cs_bad.py",
                   f"{AT}conserves_sum(fee)\ndef split_fee(fee):\n    return fee // 2, fee // 2\n")
        cg = write(d, "cs_good.py",
                   f"{AT}conserves_sum(fee)\ndef split_ok(fee):\n"
                   "    return fee // 2, fee - fee // 2\n")
        rc, out = run([str(cb)])
        expect("conserves_sum: нечётный цент -> CAUGHT", rc != 0 and "ОПРОВЕРГНУТО" in out, out[-160:])
        rc, out = run([str(cg)])
        expect("conserves_sum: честное деление -> PROVEN", rc == 0 and "ДОКАЗАНО" in out, out[-160:])

        # --- non_negative на кортеже
        nb = write(d, "nn_bad.py",
                   f"{AT}non_negative\ndef split_neg(paid, used):\n"
                   "    return paid - used, paid - used - 1\n")
        rc, out = run([str(nb)])
        expect("non_negative: компонента уходит в минус -> CAUGHT",
               rc != 0 and "ОПРОВЕРГНУТО" in out, out[-160:])

        # --- кортежный --diff-equiv
        a = write(d, "de_a.py", "def cmp(x):\n    return x // 2, x // 2\n")
        b = write(d, "de_b.py", "def cmp(x):\n    return x // 2, x - x // 2\n")
        c = write(d, "de_c.py", "def cmp(x):\n    half = x // 2\n    return half, x - half\n")
        rc, out = run(["--diff-equiv", str(a), str(b)])
        expect("--diff-equiv кортежей: расхождение -> DIVERGED + rc!=0",
               rc != 0 and "DIVERGED" in out, out[-160:])
        rc, out = run(["--diff-equiv", str(b), str(c)])
        expect("--diff-equiv кортежей: перестановка -> EQUIVALENT + rc==0",
               rc == 0 and "EQUIVALENT" in out, out[-160:])

        # --- смешанный файл: макро-функция и обычная скалярная проверяются обе
        mix = write(d, "mix.py",
                    f"{AT}monotonic\ndef price_ok(qty):\n    if qty >= 100:\n"
                    "        return 10000 + (qty - 100) * 90\n    return qty * 100\n\n"
                    f"{AT}ensures result == a + b\ndef add(a, b):\n    return a + b\n")
        rc, out = run([str(mix)])
        expect("смешанный файл: макро проверено И обычная функция тоже",
               "ДОКАЗАНО" in out and "add" in out and rc == 0, out[-220:])

    print(f"tuple-macros-check: провалов {len(fails)}" + ("" if not fails else f" -> {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
