#!/usr/bin/env python3
"""ЗОЛОТОЙ КОРПУС АУДИТОВ: реальные функции чужих проектов -> таблица + .kimg.

ЗАЧЕМ. Проверять «5000 функций, переведённых нейросетью» — путь к самообману
(дефект #77: скрипт на случайных входах объявил 83.7% ПРАВИЛЬНЫХ решений багованными).
Здесь всё наоборот и проверяемо:

 1. Источник — только РЕАЛЬНЫЙ код с указанием проекта, файла и строки (в комментарии
    рядом с моделью). Никакой генерации «по мотивам».
 2. Перевод в SMT — ДЕТЕРМИНИРОВАННЫЙ (`tools/kern_contracts.py`), а не LLM. Каждая
    формула, которую проверило ядро, выгружается файлом (`--emit-smt2`) — её можно
    перепроверить вручную `kernc prove`.
 3. Каждый контрпример подтверждается конкретным вычислителем (`[RUNTIME CONFIRMED]`).
 4. Корпус запечатывается в один контейнер `.kimg` (`--deflate`): L0 заголовок +
    Merkle BLAKE3, L1 дайджесты, L2 KERNFS-объекты, L4 доказательства Z3.

Выход: markdown-таблица (её печатает ЭТОТ скрипт, а не человек) + отчёт о .kimg.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACTOR = ROOT / "tools" / "kern_contracts.py"
KERNC = ROOT / "zig-out" / "bin" / "kernc"
AUDITS = ROOT / "audits"
SOURCE_SUFFIX = (".zig", ".c", ".h", ".rs")

RE_BV = re.compile(r"\[BV\] (\w+) \(стр\. (\d+)\): теория битовых векторов \(([^,]+), ([^)]+)\)")
RE_VERDICT = re.compile(r"\[(PASS|FAIL|SKIP)\] (\w+):\s*(.*)")
RE_CE = re.compile(r"\[КОНТРПРИМЕР\] (.+)")
RE_RT = re.compile(r"\[RUNTIME CONFIRMED\] (.+)")


def run(cmd: list[str], timeout: int = 900) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def collect(smt_dir: Path) -> list[dict]:
    """Прогнать экстрактор по корпусу и собрать вердикты структурой.

    ПАРАЛЛЕЛЬНО (рубеж 1 приёмки Эшелона 1): каждый файл — НЕЗАВИСИМЫЙ запуск
    экстрактора, поэтому пул не меняет ни одного вердикта. Порядок вывода
    восстанавливается сортировкой по (файл, функция) — детерминизм сохранён.
    """
    srcs = sorted(p for p in AUDITS.rglob("*") if p.suffix in SOURCE_SUFFIX)

    def one(src: Path) -> tuple[str, str, dict[str, str]]:
        rel = src.relative_to(ROOT).as_posix()
        _, out = run([sys.executable, str(EXTRACTOR), rel, "--emit-smt2", str(smt_dir)])
        theory: dict[str, str] = {}
        for m in RE_BV.finditer(out):
            theory[m.group(1)] = f"QF_BV {m.group(3).strip()} {m.group(4)}"
        return rel, out, theory

    workers = int(os.environ.get("KERN_AUDIT_WORKERS", min(6, os.cpu_count() or 1)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        outs = list(ex.map(one, srcs))

    rows: list[dict] = []
    for rel, out, theory in outs:
        cur: dict | None = None
        for line in out.splitlines():
            m = RE_VERDICT.search(line)
            if m:
                cur = {"file": rel, "fn": m.group(2), "verdict": m.group(1),
                       "what": m.group(3).strip(), "theory": theory.get(m.group(2), "QF_LIA (Int)"),
                       "ce": "", "rt": ""}
                rows.append(cur)
                continue
            m = RE_CE.search(line)
            if m and cur is not None:
                cur["ce"] = m.group(1).strip()
                continue
            m = RE_RT.search(line)
            if m and cur is not None:
                cur["rt"] = m.group(1).strip()
    return rows


def write_corpus_kern(smt_files: list[Path], kimg_kern: Path,
                      measured: dict[str, str]) -> None:
    """Сгенерировать .kern-проект: формулы объявляются артефактами, утверждения — claims.

    Утверждение БЕЗ контракта остаётся текстом и получает e=0 (N) — поэтому каждая
    формула объявлена артефактом с kind "contract" и привязана через `context`.

    ЗАЯВЛЕННЫЙ СТАТУС = ИЗМЕРЕННЫЙ вердикт решателя на ЭТОЙ формуле (см. main):
    никаких эвристик по имени функции или тексту причины. `kernc verify`
    переустанавливает вердикт по БАЙТАМ контейнера, поэтому любое расхождение
    (порча формулы, регрессия решателя) -> rc != 0.
    """
    def status_of(f: Path) -> str:
        return measured.get(f.name, "unknown")

    lines = ['// СГЕНЕРИРОВАНО tools/audits_run.py — не редактировать вручную.',
             '// Золотой корпус: формулы реальных функций, выгруженные детерминированным фронтендом.',
             'project "kern-open-source-audits" {', '  version "1.0"', '  root "."', '}', '']
    for f in sorted(smt_files):
        rel = f.relative_to(ROOT).as_posix()
        lines += [f'artifact "{rel}" {{', '  kind "contract"',
                  '  hash "sha256:0000000000000000000000000000000000000000000000000000000000000000"',
                  '}', '']
    for f in sorted(smt_files):
        rel = f.relative_to(ROOT).as_posix()
        lines += [f'claim "audit:{f.stem}" {{', f'  status {status_of(f)}',
                  f'  evidence "contract:{rel}"', f'  context "{rel}"', '}', '']
    kimg_kern.write_text("\n".join(lines), encoding="utf-8")


def cert_section() -> int:
    """Проверить СЕРТИФИКАТЫ реальных уязвимостей: `*_guard` -> PROVEN,
    `*_unguarded` / `*_control` -> REFUTED.

    ЗАЧЕМ: файлы `audits/*/*.smt2` лежали в репозитории и НИЧЕМ не проверялись.
    При регрессии решателя/фронтенда они молча разошлись бы с реальностью, а
    витрина продолжала бы утверждать «до фикса — контрпример, после — доказано».
    """
    certs = sorted(p for p in AUDITS.rglob("*.smt2") if p.parent.name != "smt2")
    bad = 0
    checked = 0
    print("-" * 78)
    print("СЕРТИФИКАТЫ РЕАЛЬНЫХ УЯЗВИМОСТЕЙ (контрпример ДО фикса / доказательство ПОСЛЕ)")
    for f in certs:
        stem = f.stem
        if stem.endswith("_guard") or stem.endswith("isAligned"):
            want = "proven"
        elif stem.endswith("_unguarded") or stem.endswith("_control"):
            want = "refuted"
        else:
            continue
        checked += 1
        _rc, out = run([str(KERNC), "prove", str(f)], timeout=300)
        got = ("proven" if "ДОКАЗАНО" in out
               else "refuted" if "КОНТРПРИМЕР" in out else "unknown")
        m = re.search(r"ДОВЕРЕННЫХ (\d+)", out)
        tcnt = m.group(1) if m else "—"
        ok = got == want
        if not ok:
            bad += 1
        rel = f.relative_to(ROOT).as_posix()
        print(f"  {'OK  ' if ok else 'FAIL'} {rel:44s} ожидали {want:7s} "
              f"получили {got:7s} trusted {tcnt}")
    print(f"  сертификатов проверено: {checked} | расхождений: {bad}")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Золотой корпус аудитов реального кода")
    ap.add_argument("--keep", action="store_true", help="не удалять временный каталог формул")
    ap.add_argument("--emit-md", default=None, metavar="OUT.md",
                    help="записать markdown-таблицу в файл")
    ap.add_argument("--no-kimg", action="store_true", help="не собирать контейнер .kimg")
    args = ap.parse_args()

    if not KERNC.exists():
        print(f"[!] нет {KERNC} — соберите: zig build")
        return 1

    smt_dir = ROOT / "audits" / "smt2"
    if smt_dir.exists():
        shutil.rmtree(smt_dir)
    smt_dir.mkdir(parents=True)

    rows = collect(smt_dir)
    smt_files = sorted(smt_dir.glob("*.smt2"))

    # ИЗМЕРЕННЫЙ СТАТУС КАЖДОЙ ФОРМУЛЫ (без эвристик по имени/причине).
    # ЗАЧЕМ: экстрактор сообщает ПЕРВОЕ проваленное обязательство функции, а
    # выгруженный файл — её ОСНОВНОЕ обязательство. ИЗМЕРЕНО: у `divCeilBuggy`
    # первым провалилось переполнение, но и основная формула опровергнута (SAT);
    # у `alignForwardAdd` — наоборот (основная доказана). Поэтому статус в
    # контейнере объявляется по ФАКТИЧЕСКОМУ вердикту решателя на этой формуле,
    # а `kernc verify` переустанавливает его по БАЙТАМ образа: расхождение
    # (порча формулы, регрессия решателя) -> rc != 0.
    def measure(f: Path) -> str:
        _rc, out = run([str(KERNC), "prove", str(f)], timeout=300)
        if "ДОКАЗАНО" in out:
            return "proven"
        if "КОНТРПРИМЕР" in out:
            return "refuted"
        return "unknown"

    with ThreadPoolExecutor(max_workers=int(os.environ.get("KERN_AUDIT_WORKERS",
                                                           min(6, os.cpu_count() or 1)))) as ex:
        measured = dict(zip([f.name for f in smt_files], ex.map(measure, smt_files)))

    n_proven = sum(1 for v in measured.values() if v == "proven")
    n_refuted = sum(1 for v in measured.values() if v == "refuted")
    print(f"[i] измерено формул: {len(measured)} | proven {n_proven} | refuted {n_refuted}")
    # АНТИ-ВАКУУМ: корпус обязан содержать ОБА класса — иначе проверка
    # выродилась бы (все proven или все refuted = сломанный экстрактор/решатель).
    if n_proven == 0 or n_refuted == 0:
        print("[!] корпус односторонний (нет proven или нет refuted) — проверка вырождена")
        return 1

    proven = sum(1 for r in rows if r["verdict"] == "PASS")
    refuted = sum(1 for r in rows if r["verdict"] == "FAIL")
    skipped = sum(1 for r in rows if r["verdict"] == "SKIP")
    runtime = sum(1 for r in rows if r["rt"])

    md = ["| Project / file | Function | Theory | Verdict | Counterexample | Runtime |",
          "|:--|:--|:--|:--|:--|:--|"]
    for r in rows:
        v = {"PASS": "**PROVEN**", "FAIL": "**REFUTED**", "SKIP": "SKIP"}[r["verdict"]]
        if r["verdict"] == "FAIL" and r["what"] and "КОНТРАКТ НАРУШЕН" not in r["what"]:
            v += f" — {r['what']}"
        ce = f"`{r['ce']}`" if r["ce"] else "—"
        rt = "yes" if r["rt"] else "—"
        md.append(f"| `{r['file']}` | `{r['fn']}` | {r['theory']} | {v} | {ce} | {rt} |")
    table = "\n".join(md)

    print("=" * 78)
    print("KERN: ЗОЛОТОЙ КОРПУС АУДИТОВ РЕАЛЬНОГО КОДА")
    print("=" * 78)
    print(table)
    print("-" * 78)
    print(f"функций: {len(rows)} | ДОКАЗАНО {proven} | ОПРОВЕРГНУТО {refuted} | "
          f"SKIP {skipped} | с рантайм-подтверждением {runtime} | формул выгружено {len(smt_files)}")

    rc_cert = cert_section()

    if args.emit_md:
        Path(args.emit_md).write_text(table + "\n", encoding="utf-8")
        print(f"[i] таблица записана: {args.emit_md}")

    rc = rc_cert
    if not args.no_kimg:
        kimg_kern = ROOT / "audits" / "real_code_corpus.kern"
        kimg = ROOT / "audits" / "real_code_corpus.kimg"
        srcs = sorted(p for p in AUDITS.rglob("*") if p.suffix in SOURCE_SUFFIX)
        write_corpus_kern(smt_files, kimg_kern, measured)
        rc_b, _ = run([str(KERNC), "build", "audits/real_code_corpus.kern",
                       "-o", "audits/real_code_corpus.kimg", "--deflate"])
        rc_i, _ = run([str(KERNC), "check-integrity", "audits/real_code_corpus.kimg"])
        rc_v, out_v = run([str(KERNC), "verify", "audits/real_code_corpus.kimg"])
        size = kimg.stat().st_size if kimg.exists() else 0
        print("-" * 78)
        print(f"L0 .kimg:   {'собран' if rc_b == 0 else 'ОШИБКА'} ({size} байт, --deflate)")
        print(f"L0 Merkle:  {'целостность OK' if rc_i == 0 else 'ОШИБКА'}")
        print(f"L4 verify:  {'утверждения проверены' if rc_v == 0 else 'ОШИБКА'}")
        for ln in out_v.splitlines():
            if any(k in ln for k in ("claim", "ИТОГ", "e =", "e=")):
                print("   " + ln.strip()[:110])
        rc = rc_cert or rc_b or rc_i or rc_v
    return rc


if __name__ == "__main__":
    sys.exit(main())
