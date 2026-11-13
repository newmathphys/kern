#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: Apache-2.0
"""`run_showcase_100.py` — витрина практической пользы KERN на живых задачах.

ЗАМОРОЖЕНО (правило полигона): ядро и анализатор (`src/`, `tools/kern_contracts.py`)
НЕ меняются. Здесь только каталог `benchmarks/showcase_100/*.json` и этот раннер.

ФОРМАТ: json-файл на «десяток» — {"dozen": "...", "cards": [{...}]}, где карточка:
  id, sphere, trick, kind ("diff-equiv" | "anti-cheat"), files {name: body},
  run [файлы для KERN], expect (подстрока вердикта), oracle {kind, ...}.

Оракулы независимы от KERN: `diff` реально вызывает old()/new() и сравнивает
результаты; `unittest` прогоняет тест и требует rc=0 (то есть показывает, что
честный инструмент СЛЕП, а KERN ловит).

Выход: docs/SHOWCASE_100.ru.md + rc=0 только если ВСЕ карточки подтверждены.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / "benchmarks" / "showcase_100"
KC = ROOT / "tools" / "kern_contracts.py"
DOC_RU = ROOT / "docs" / "SHOWCASE_100.ru.md"
PY = sys.executable


def _run(args: list[str], cwd: Path | None = None, timeout: int = 300) -> tuple[int, str]:
    try:
        p = subprocess.run(args, cwd=str(cwd or ROOT), capture_output=True,
                           text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "[TIMEOUT]"


def _parse_cex(out_k: str) -> dict[str, int]:
    """Достать значения переменных из строки контрпримера KERN.

    Учитываются ВСЕ три формы, которые печатает решатель: десятичная
    (`x = -2147483648`), шестнадцатеричная (`#x80000000` / `0x80000000`) и
    двоичная (`#b1000...`). Без этого битовые карточки (QF_BV) не проверить:
    перебор до `limit` не попадает в узкие маски вроде `0xc0000001`.
    """
    vals: dict[str, int] = {}
    m = re.search(r"КОНТРПРИМЕР[^\n]*", out_k or "")
    # БЕЗ строки КОНТРПРИМЕР чисел нет: иначе `#x` из шапки/баннера давал бы
    # ложное «контрпример есть» на ДОКАЗАННЫХ карточках.
    if not m:
        return {}
    line = m.group(0)
    for nm, raw in re.findall(r"([A-Za-z_]\w*)\s*[=:]\s*(#x[0-9a-fA-F]+|#b[01]+|0x[0-9a-fA-F]+|-?\d+)",
                              line):
        try:
            if raw.startswith("#x"):
                vals[nm] = int(raw[2:], 16)
            elif raw.startswith("#b"):
                vals[nm] = int(raw[2:], 2)
            elif raw.startswith("0x"):
                vals[nm] = int(raw, 16)
            else:
                vals[nm] = int(raw)
        except ValueError:
            continue
    return vals


def _oracle(card: dict, d: Path, out_k: str = "") -> tuple[bool, str]:
    """Независимая проверка карточки — без KERN."""
    spec = card.get("oracle") or {}
    kind = spec.get("kind")
    if kind == "diff":
        old_p, new_p = d / spec["old"], d / spec["new"]
        fn = spec.get("fn", "f")
        args = spec.get("args", "0, 10")
        script = (f"import importlib.util as u\n"
                  f"def load(p,n):\n"
                  f"    s=u.spec_from_file_location(n,p); m=u.module_from_spec(s);\n"
                  f"    s.loader.exec_module(m); return m\n"
                  f"o=load(r'{old_p}','o'); n2=load(r'{new_p}','n2')\n"
                  f"ro=o.{fn}({args}); rn=n2.{fn}({args})\n"
                  f"print('OLD',ro); print('NEW',rn); print('SAME',ro==rn)\n")
        rc, out = _run([PY, "-c", script])
        ok = rc == 0 and "SAME False" in out
        ce = " / ".join(ln for ln in out.splitlines() if ln.startswith(("OLD", "NEW")))
        return ok, (ce[:90] if ce else out.strip()[:90])
    if kind == "unittest":
        rc, out = _run([PY, "-m", "unittest", "discover", "-s", str(d),
                        "-p", spec.get("pattern", "test_*.py")], cwd=d)
        return rc == 0, (f"unittest rc={rc} (слеп)" if rc == 0 else f"unittest rc={rc}")
    if kind == "belnap":
        # ЖИВОЙ механизм проекта: `_belnap_state` из пример-сервера (не копия!).
        script = (
            "import importlib.util as u, pathlib, json\n"
            f"p=pathlib.Path(r'{ROOT}/examples/kern_mcp_server.py')\n"
            "s=u.spec_from_file_location('m',p); m=u.module_from_spec(s)\n"
            "s.loader.exec_module(m)\n"
            "j=m._belnap_state\n"
            "t=j(1,0); f=j(0,1); b=j(1,1)\n"
            "def deny_wins(a,b_):\n"
            "    return 'deny' if b_ else ('allow' if a else 'none')\n"
            "print('T',t); print('F',f); print('JOIN',b); print('BOOL',deny_wins(1,1))\n")
        rc, out = _run([PY, "-c", script])
        ok = rc == 0 and "JOIN B" in out and "BOOL deny" in out
        got = [ln for ln in out.splitlines() if ln.startswith(("JOIN", "BOOL"))]
        return ok, (" / ".join(got)[:90] if got else out.strip()[:90])
    if kind == "bruteforce":
        # Независимый перебор: ищем пару (a1, a2), где бизнес-функция ТЕРЯЕТ деньги.
        mod = d / spec["module"]
        fn = spec.get("fn", "loss")
        limit = int(spec.get("limit", 200))
        script = (
            "import importlib.util as u\n"
            f"s=u.spec_from_file_location('biz',r'{mod}'); m=u.module_from_spec(s)\n"
            f"s.loader.exec_module(m)\n"
            f"hit=None\n"
            f"for a1 in range(1,{limit}):\n"
            f"    for a2 in range(1,{limit}):\n"
            f"        if m.{fn}(a1,a2) < 0:\n"
            f"            hit=(a1,a2,m.{fn}(a1,a2)); break\n"
            f"    if hit: break\n"
            f"print('HIT',hit)\n")
        rc, out = _run([PY, "-c", script])
        ok = rc == 0 and "HIT (" in out
        line = [ln for ln in out.splitlines() if ln.startswith("HIT")]
        return ok, (line[0][:90] if line else out.strip()[:90])
    if kind == "no_cex":
        # ЭТАЛОН (PROVEN): контрпримера быть не должно — это и есть проверка.
        return (not _parse_cex(out_k)), "контрпримеров нет (эталон доказан)"

    if kind == "two_run":
        # ДВУСТОРОННОСТЬ 2-Safety: ОДИН pub, ДВА разных секрета -> разные
        # публичные ответы = реальная утечка (оракул не верит KERN).
        mod = d / spec["module"]
        script = ("import importlib.util as u\n"
                  f"s=u.spec_from_file_location('m',r'{mod}'); m=u.module_from_spec(s)\n"
                  f"s.loader.exec_module(m)\n"
                  f"a=m.{spec['fn']}({spec['pub']}, {spec['sec1']})\n"
                  f"b=m.{spec['fn']}({spec['pub']}, {spec['sec2']})\n"
                  f"print('A',a); print('B',b); print('LEAK',a!=b)\n")
        rc, out = _run([PY, "-c", script])
        ok = rc == 0 and "LEAK True" in out
        got = " / ".join(ln for ln in out.splitlines() if ln.startswith(("A", "B")))
        return ok, (got[:90] if got else out.strip()[:90])
    if kind == "cex":
        # ПОДТВЕРЖДЕНИЕ КОНТРПРИМЕРА (Десяток 07): берём ЧИСЛА ИЗ ВЫВОДА KERN
        # (`#x...`/`#b...`/десятичные), подставляем в реальную арифметику Python
        # с маской 32 бита и проверяем, что инвариант действительно нарушен.
        # Перебор тут бесполезен: узкие маски (0xc0000001) в него не попадают.
        vals = _parse_cex(out_k)
        if not vals:
            return False, "KERN не выдал чисел контрпримера"
        expr = spec["expr"]
        env = {"M": 0xFFFFFFFF, "S32": 0x80000000}
        env.update({k: (v & 0xFFFFFFFF) for k, v in vals.items()})
        try:
            ok = bool(eval(expr, {"__builtins__": {}}, env))  # noqa: S307 — числа карточки
        except Exception as exc:  # noqa: BLE001 — выражение карточки невычислимо
            return False, f"expr не вычислилась: {exc}"
        shown = ", ".join(f"{k}={v:#x}" for k, v in list(vals.items())[:3])
        return ok, f"cex {shown} -> expr={ok}"

    if kind == "json":
        # Наивный конкурент для MCP-карточек: `json.loads` видит ВАЛИДНЫЙ JSON
        # (схема формально корректна) и говорит OK — а KERN блокирует отраву.
        f = d / spec["file"]
        script = (f"import json\n"
                  f"try:\n"
                  f"    json.load(open(r'{f}', encoding='utf-8'))\n"
                  f"    print('OK valid json')\n"
                  f"except Exception as e:\n"
                  f"    print('ERR', e)\n")
        rc, out = _run([PY, "-c", script])
        ok = rc == 0 and "OK valid json" in out
        return ok, ("json.loads: валиден (слеп)" if ok else out.strip()[:90])
    if kind == "proof":
        # ПЕРЕПРОВЕРКА СЕРТИФИКАТА в браузерном ядре (kernc.wasm, без сисколлов).
        # Стороны: «наивный» чекер верит слову unsat в тексте, ядро — нет.
        smt = d / spec["smt"]
        proof = d / spec["proof"]
        wasm = ROOT / "docs" / "playground" / "kernc.wasm"
        node = shutil.which("node")
        if not node or not wasm.exists():
            return False, "node/kernc.wasm недоступны (оракул недоступен)"
        # ПУТИ — ТОЛЬКО ЧЕРЕЗ process.argv (ревью, верно): интерполяция путей внутрь
        # JS-кода ломается на пробеле в «Рабочий стол». Здесь argv[1..3].
        script = (
            "const fs=require('fs');\n"
            "const [wasmP,smtP,proofP]=process.argv.slice(1);\n"
            "const smt=fs.readFileSync(smtP); const proof=fs.readFileSync(proofP);\n"
            "WebAssembly.instantiate(fs.readFileSync(wasmP),{}).then(({instance:{exports:e}})=>{\n"
            "  const view=()=>new Uint8Array(e.memory.buffer);\n"
            "  const ptr=e.kern_wasm_input_ptr(), cap=e.kern_wasm_input_cap();\n"
            "  if (smt.length+proof.length>cap){console.log('V',0,'overflow');return;}\n"
            "  view().set(smt,ptr); view().set(proof,ptr+smt.length);\n"
            "  const v=e.kern_wasm_verify_proof(ptr,smt.length,ptr+smt.length,proof.length);\n"
            "  console.log('V',v,'');\n"
            "}).catch(err=>console.log('V',0,'err:'+err.message));\n")
        rc, out = _run([node, "-e", script, str(wasm), str(smt), str(proof)],
                    timeout=120)
        verified = "V 1" in out
        naive = "unsat" in proof.read_text(encoding="utf-8", errors="replace")
        want = bool(spec.get("expect_verified", False))
        # Наивный чекер описывается ИНФОРМАЦИОННО: он смотрит на слово unsat,
        # которого в эталонном сертификате нет, поэтому «зелёный» он не по
        # тексту, а по слепому доверию к шапке. Условие — только вердикт ядра.
        # ДВУСТОРОННОСТЬ (ревью, верно): `0` на подделке ничего не доказывает,
        # если сломан путь, пуст буфер или упал загрузчик — «ОТКЛОНЁН» придёт и
        # без диверсии. Поэтому в ТОМ ЖЕ прогоне проверяем эталон: он обязан
        # быть ПРИНЯТ (1). Пути — через argv, эталон берём из docs/playground.
        if spec.get("honest"):
            hs = ROOT / "docs" / "playground" / "sample.smt2"
            hp = ROOT / "docs" / "playground" / "sample.proof"
            _rc_h, out_h = _run([node, "-e", script, str(wasm), str(hs), str(hp)],
                                timeout=120)
            if "V 1" not in out_h:
                return False, ("эталон НЕ принят — вердикт подделки "
                               f"недостоверен ({out_h.strip()[:60]})")
        # на подделке ожидаем отказ, на эталоне — приём (want).
        ok = (verified == want)
        tag = "принят" if verified else "ОТКЛОНЁН"
        return ok, f"kernc.wasm: {tag}; наивный чекер: {'верит unsat' if naive else 'нет unsat'}"
    if kind == "gcc":
        # ФИЗИЧЕСКИЙ оракул: компилируем карточку с main() под санитайзерами и
        # запускаем. Баг-карточка обязана УПАСТЬ (UB/ASan), защищённый близнец —
        # завершиться rc=0. Это проверка, не зависящая от KERN.
        src = d / spec["file"]
        exe = d / "a.out"
        cc = shutil.which("gcc")
        if not cc:
            return False, "gcc не найден (оракул недоступен)"
        rc_c, out_c = _run([cc, "-O1", "-g", "-fsanitize=address,undefined",
                            "-fno-sanitize-recover=all",
                            str(src), "-o", str(exe)], timeout=180)
        if rc_c != 0:
            return False, f"не компилируется: {out_c.strip()[:60]}"
        rc_r, out_r = _run([str(exe)], timeout=60)
        want_crash = bool(spec.get("expect_crash", True))
        crashed = rc_r != 0 or "runtime error" in out_r.lower() or "AddressSanitizer" in out_r
        ok = crashed if want_crash else (rc_r == 0 and "runtime error" not in out_r.lower()
                                         and "AddressSanitizer" not in out_r)
        tag = "UB/ASan" if crashed else "чисто"
        return ok, f"gcc: {tag} (rc={rc_r})"
    return False, "оракул не задан"



def main(argv: list[str]) -> int:
    parts = sorted(CASES_DIR.glob("*.json")) if CASES_DIR.exists() else []
    if not parts:
        print(f"[!] нет карточек в {CASES_DIR.relative_to(ROOT)}")
        return 1
    rows: list[tuple[str, str, str, str, str, str]] = []
    total = confirmed = 0
    t_all = time.time()
    for part in parts:
        data = json.loads(part.read_text(encoding="utf-8"))
        dozen = data.get("dozen", part.stem)
        print(f"\n=== {dozen} ===")
        for card in data.get("cards", []):
            total += 1
            with tempfile.TemporaryDirectory() as td:
                d = Path(td)
                for fname, body in (card.get("files") or {}).items():
                    (d / fname).write_text(body, encoding="utf-8")
                if card.get("kind") == "diff-equiv":
                    args = [PY, str(KC), "--diff-equiv",
                            *[str(d / x) for x in card["run"]]]
                elif card.get("kind") == "contract":
                    # Десяток 01: обычный путь контрактов НА ФАЙЛЕ ВРЕМЕННОГО КАТАЛОГА.
                    # Литералов `@kern:` в отслеживаемых файлах нет — замок контрактов
                    # репозитория не затрагивается (правило полигона).
                    args = [PY, str(KC), str(d / card["run"][0])]
                elif card.get("kind") == "noninterference":
                    # Блок 10А: 2-Safety (штатный тракт --noninterference).
                    args = [PY, str(KC), "--noninterference",
                            str(d / card["run"][0])]
                elif card.get("kind") == "bitvec":
                    # Десяток 07: битовый тракт — нативный чекер на .smt2 (QF_BV).
                    # ИЗМЕРЕНО: `kernc prove audits/smt2/bv_overflow_mul_bv.smt2`
                    # печатает `[КОНТРПРИМЕР] a = #x2b6270ab, ...` — отсюда и
                    # работает _parse_cex (hex/bin/dec).
                    _kc = ROOT / "zig-out" / "bin" / "kernc"
                    args = [str(_kc), "prove", str(d / card["run"][0])]
                elif card.get("kind") == "mcp":
                    # Десяток 09Б: отравленный MCP-манифест.
                    args = [PY, str(KC), "--audit-mcp", str(d / card["run"][0])]
                elif card.get("kind") == "xray":
                    # Десяток 04: рентген C-файла; ожидание — класс находки
                    # ("BOUNDS PATH"/"OVERFLOW PATH") или "находок 0" у близнеца.
                    args = [PY, str(KC), "--xray", str(d / card["run"][0])]
                elif card.get("kind") in ("belnap", "proof"):
                    # Вердикт даёт САМО ЯДРО: для belnap — живой JOIN_K;
                    # для proof — kernc.wasm в Node (тот же бинарь, что в браузере).
                    args = None
                else:
                    args = [PY, str(KC), "--anti-cheat", str(d / card["run"][0])]
                if args is None:
                    orc_ok, orc_txt = _oracle(card, d, "")
                    if card.get("kind") == "proof":
                        kern_ok = orc_ok and "ОТКЛОНЁН" in orc_txt
                    else:
                        kern_ok = orc_ok and "JOIN B" in orc_txt
                    out_k = orc_txt
                else:
                    _rc_k, out_k = _run(args)
                    if card.get("expect_absent"):
                        # БЛИЗНЕЦ: находок быть НЕ ДОЛЖНО (негативное ожидание).
                        kern_ok = card["expect_absent"] not in out_k
                    else:
                        kern_ok = card["expect"] in out_k
                    orc_ok, orc_txt = _oracle(card, d, out_k)
            confirmed += 1 if (kern_ok and orc_ok) else 0
            mark = "OK " if (kern_ok and orc_ok) else "FAIL"
            print(f"  [{mark}] {card['id']:22s} KERN={kern_ok} oracle={orc_txt[:55]}")
            ce = ""
            for ln in out_k.splitlines():
                if "КОНТРПРИМЕР" in ln:
                    ce = ln.strip()[:80]
                    break
            rows.append((dozen, card["id"], card.get("sphere", ""),
                         card.get("trick", ""),
                         "ПОЙМАЛ" if kern_ok else "пропустил",
                         ce or orc_txt[:60]))
    dt = time.time() - t_all
    print(f"\nИТОГ: карточек {total} | подтверждено KERN+оракулом {confirmed} | {dt:.1f} с")
    lines = ["# Витрина практической пользы KERN", "",
             f"Сгенерировано `tools/run_showcase_100.py` за {dt:.1f} с. Каждая строка —",
             "**реальный** запуск KERN и независимого оракула (вызов функции или unittest).",
             "", "| Десяток | Задача | Сфера | В чём подвох | KERN | Контрпример |",
             "|:--|:--|:--|:--|:--|:--|"]
    for r in rows:
        lines.append("| " + " | ".join(str(x).replace("|", "\\|") for x in r) + " |")
    lines += ["", f"**Подтверждено: {confirmed} / {total}.**", ""]
    DOC_RU.write_text("\n".join(lines), encoding="utf-8")
    print(f"витрина: {DOC_RU.relative_to(ROOT)}")
    return 0 if confirmed == total else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
