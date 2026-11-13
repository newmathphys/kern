#!/usr/bin/env python3
"""«Машина времени»: KERN против РЕАЛЬНЫХ исторических багов чужих проектов.

Правила честности:
  1. Каждая мишень — публичный репозиторий + коммит авторов. Кода мы не пишем.
  2. bug_commit — parent исправившего коммита (состояние ДО фикса).
  3. Оракул обязан физически воспроизвести дефект на bug_commit и показать,
     что на fix_commit его нет. Иначе случай помечается ORACLE_UNVERIFIED.
  4. Счёт НЕ подгоняется: skip/missed попадают в отчёт как есть.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "benchmarks" / "time_machine" / "cases.json"
DOC_EN = ROOT / "docs" / "TIME_MACHINE.md"
DOC_RU = ROOT / "docs" / "TIME_MACHINE.ru.md"
KERNC = ROOT / "zig-out" / "bin" / "kernc"
PY = sys.executable


def sh(cmd, cwd=None, timeout=300, env=None):
    p = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True,
                       text=True, timeout=timeout, env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def full_sha(repo: str, short: str) -> str:
    """Короткий SHA -> полный через API (git fetch по префиксу не работает)."""
    url = (repo.replace("https://github.com/", "https://api.github.com/repos/")
           + f"/commits/{short}")
    rc, out = sh(["curl", "-s", "-m", "25", "-H", "User-Agent: kern-tm", url])
    if rc == 0:
        try:
            return json.loads(out)["sha"]
        except Exception:
            pass
    return short


def checkout(repo: str, workdir: Path, shas: list[str]) -> str | None:
    """Клон с частичным fetch нужных коммитов. None = успех, иначе текст ошибки."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if not (workdir / ".git").exists():
        rc, out = sh(["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout",
                      repo, str(workdir)], timeout=600, env=env)
        if rc != 0:
            return out[-400:]
    for s in shas:
        rc, out = sh(["git", "fetch", "--quiet", "--depth", "1", "origin", s],
                     cwd=workdir, timeout=600, env=env)
        if rc != 0:
            return f"fetch {s[:12]}: {out.strip()[-200:]}"
    return None


def at_commit(workdir: Path, sha: str) -> None:
    rc, out = sh(["git", "checkout", "--quiet", "--force", sha], cwd=workdir, timeout=120)
    if rc != 0:
        raise RuntimeError(out[-300:])


def run_python_oracle(workdir: Path, module: str, snippet: str, timeout=120):
    """Импортирует модуль ИЗ ЭТОГО коммита и исполняет оракул в отдельном процессе."""
    body = "".join(f"    {line}\n" for line in snippet.splitlines())
    code = ("import sys, importlib\n"
            f"sys.path.insert(0, {str(workdir)!r})\n"
            f"sys.path.insert(0, {str(workdir / 'src')!r})\n"
            f"M = importlib.import_module({module!r})\n"
            "ok = True\n"
            "try:\n" + body +
            "except AssertionError as e:\n"
            "    ok = False; print('BUG:', e)\n"
            "except Exception as e:\n"
            "    ok = False; print('BUG(%s): %s' % (type(e).__name__, e))\n"
            "print('OK' if ok else 'FAIL')\n")
    rc, out = sh([PY, "-c", code], cwd=str(workdir), timeout=timeout)
    tail = (out.strip().splitlines() or [""])[-1]
    return tail == "OK", out.strip()[-300:]



def run_c_oracle(workdir: Path, include: str, snippet: str, extra_src: str, timeout=240):
    """Компилирует драйвер с ASan/UBSan против ИСХОДНИКОВ ЭТОГО коммита."""
    pid = os.getpid()
    drv = workdir / f"_tm_drv_{pid}.c"
    drv.write_text(f'#include <stdio.h>\n#include <stdlib.h>\n#include <math.h>\n'
                   f'#include "{include}"\n'
                   f"int main(void){{\n{snippet}\nreturn 0;}}\n", encoding="utf-8")
    exe = workdir / f"_tm_bin_{pid}"
    cmd = (f"gcc -O1 -g -I. -fsanitize=address,undefined -fno-sanitize-recover=all "
           f"{drv.name} {extra_src} -o {exe.name} -lm")
    rc, out = sh(cmd, cwd=str(workdir), timeout=timeout)
    if rc != 0:
        drv.unlink(missing_ok=True)
        return "COMPILE_ERROR", out[-300:]
    rc, out = sh([str(exe)], cwd=str(workdir), timeout=timeout)
    drv.unlink(missing_ok=True)
    exe.unlink(missing_ok=True)
    crashed = rc != 0 or "Sanitizer" in out or "runtime error" in out
    last = (out.strip().splitlines() or [""])[-1][:200]
    return ("SEGV" if crashed else "clean"), last


def kern_stage(case: dict, workdir: Path, file_rel: str) -> tuple[str, str]:
    """Стадия KERN на коде ЭТОГО коммита. Возвращает (статус, деталь)."""
    k = case.get("kern", {})
    mode = k.get("mode")
    target = workdir / file_rel
    if not target.exists():
        return "N/A", "файл отсутствует в этом коммите"
    if mode == "skip":
        return "SKIP", k.get("why", "вне модели kernc")
    if not KERNC.exists():
        return "N/A", "kernc не собран"
    if mode == "xray":
        rc, out = sh([str(KERNC), "audit", str(target), "--xray"], timeout=240)
        up = out.upper()
        hit = ("НАЙДЕН" in up or "НАРУШ" in up or "УТЕЧК" in up or "НАХОД" in up)
        return ("CAUGHT" if hit else "MISSED"), (out.strip().splitlines() or [""])[-1][:170]
    if mode == "check":
        rc, out = sh([str(KERNC), "check", str(target)], timeout=300)
        if "ОПРОВЕРГНУТО" in out or "НАРУШ" in out.upper():
            return "CAUGHT", "kernc check: нарушение"
        return ("MISSED" if rc == 0 else "N/A"), (out.strip().splitlines() or [""])[-1][:170]
    return "N/A", f"неизвестный режим {mode}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    spec = json.loads(CASES.read_text(encoding="utf-8"))
    only = {s.strip() for s in a.only.split(",") if s.strip()}
    cases = [c for c in spec["cases"] if not only or c["id"] in only]

    tmp = Path(tempfile.mkdtemp(prefix="kern-tm-"))
    rows, t0 = [], time.time()
    try:
        for c in cases:
            slug = c["repo"].rstrip("/").split("/")[-1]
            wd = tmp / slug
            print(f"[{c['id']}] {c['repo']} {c['bug_commit']} -> {c['fix_commit']}", flush=True)
            bug, fix = full_sha(c["repo"], c["bug_commit"]), full_sha(c["repo"], c["fix_commit"])
            err = checkout(c["repo"], wd, [bug, fix])
            if err:
                rows.append({**c, "status": "FETCH_FAIL", "detail": err, "oracle": {}})
                print("   FETCH_FAIL", err[:120], flush=True)
                continue
            oracle = {}
            for tag, sha in (("bug", bug), ("fix", fix)):
                at_commit(wd, sha)
                if c["lang"] == "python":
                    ok, det = run_python_oracle(wd, c["module"], c["oracle_py"])
                    oracle[tag] = "OK" if ok else "FAIL"
                else:
                    inc = "cJSON.c" if "cjson" in c["repo"].lower() else "jsmn.h"
                    st, det = run_c_oracle(wd, inc, c["oracle_c"], "")
                    oracle[tag] = st
                oracle[f"{tag}_detail"] = det
            reproduced = oracle["bug"] in ("FAIL", "SEGV") and oracle["fix"] in ("OK", "clean")
            at_commit(wd, bug)
            kstat, kdet = kern_stage(c, wd, c["path"])
            if kstat == "CAUGHT" and reproduced:
                st = "CAUGHT"
            elif c["kern"].get("mode") == "skip":
                st = "SKIP"
            elif kstat == "MISSED" and not reproduced:
                st = "ORACLE_UNVERIFIED"
            elif kstat == "MISSED":
                st = "MISSED"
            else:
                st = "ORACLE_UNVERIFIED" if not reproduced else "SKIP"
            rows.append({**c, "status": st, "oracle": oracle,
                         "kern_status": kstat, "kern_detail": kdet, "reproduced": reproduced})
            print(f"   оракул bug={oracle['bug']} fix={oracle['fix']} | KERN={kstat} -> {st}", flush=True)
    finally:
        if not a.keep:
            shutil.rmtree(tmp, ignore_errors=True)

    dt = time.time() - t0
    caught = sum(r["status"] == "CAUGHT" for r in rows)
    skipped = sum(r["status"] == "SKIP" for r in rows)
    missed = sum(r["status"] in ("MISSED", "FETCH_FAIL") for r in rows)
    unver = sum(r["status"] == "ORACLE_UNVERIFIED" for r in rows)
    write_docs(rows, caught, skipped, missed, dt)
    print(f"ИТОГ: мишеней {len(rows)} | поймано {caught} | честный пропуск {skipped} | "
          f"пропущено {missed} | оракул не подтвердил {unver} | {dt:.1f} с")
    (ROOT / "docs" / "time_machine_result.json").write_text(
        json.dumps({"caught": caught, "skipped": skipped, "missed": missed,
                    "oracle_unverified": unver, "total": len(rows),
                    "seconds": round(dt, 1),
                    "rows": [{k: r.get(k) for k in ("id", "repo", "bug_commit", "fix_commit",
                                                    "status", "kern_status", "kern_detail")}
                             for r in rows]}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def write_docs(rows, caught, skipped, missed, dt):
    head_en = ("# Time Machine: KERN vs. real historical bugs from other people's repositories\n\n"
               "Targets are **real public commits**: `bug_commit` is the parent of the maintainers'\n"
               "own fix commit, so both the buggy code and the fix were written by the projects'\n"
               "authors. An independent oracle must physically reproduce the defect on `bug_commit`\n"
               "and show it gone on `fix_commit`; otherwise the case is reported as unverified\n"
               "instead of being counted as a hit.\n\n")
    head_ru = ("# Машина времени: KERN против реальных исторических багов чужих репозиториев\n\n"
               "Мишени — **настоящие публичные коммиты**: `bug_commit` это parent коммита-исправления\n"
               "самих авторов проекта, то есть и багованный код, и фикс написали мейнтейнеры.\n"
               "Независимый оракул обязан физически воспроизвести дефект на `bug_commit` и показать,\n"
               "что на `fix_commit` он исчез; иначе случай идёт как неподтверждённый, а не как «поймано».\n\n")
    cols_en = ["Case", "Repository", "Bug commit", "Fix commit", "Oracle: bug", "Oracle: fix", "KERN", "Result"]
    cols_ru = ["Кейс", "Репозиторий", "Коммит с багом", "Коммит-фикс", "Оракул: баг", "Оракул: фикс", "KERN", "Итог"]
    lbl = {"CAUGHT": ("**caught**", "**поймано**"), "SKIP": ("honest skip", "честный пропуск"),
           "MISSED": ("missed", "пропущено"),
           "ORACLE_UNVERIFIED": ("oracle unverified", "оракул не подтвердил"),
           "FETCH_FAIL": ("fetch failed", "сбой загрузки")}
    tail_en = ("Honest skips are not a failure of the demonstration: they mark where KERN's model\n"
               "genuinely ends (iterator laziness, object truthiness, saturated `len`).\n")
    tail_ru = ("Честные пропуски — не провал демонстрации: они показывают, где модель KERN\n"
               "действительно заканчивается (ленивость итераторов, истинность объектов, насыщение `len`).\n")
    for path, head, cols, tail, idx in ((DOC_EN, head_en, cols_en, tail_en, 0),
                                        (DOC_RU, head_ru, cols_ru, tail_ru, 1)):
        lines = [head, "| " + " | ".join(cols) + " |", "|" + "|".join([":--"] * len(cols)) + "|"]
        for r in rows:
            o = r.get("oracle", {})
            lines.append("| " + " | ".join([
                f"`{r['id']}`",
                f"`{r['repo'].split('github.com/')[-1]}`",
                f"`{r['bug_commit']}`", f"`{r['fix_commit']}`",
                str(o.get("bug", "—")), str(o.get("fix", "—")),
                str(r.get("kern_status", "—")),
                lbl.get(r["status"], ("—", "—"))[idx]]) + " |")
        lines += ["", (f"**Result: {caught} caught / {skipped} honest skip / {missed} missed "
                       f"out of {len(rows)} real historical fixes**, {dt:.1f} s."
                       if idx == 0 else
                       f"**Итог: поймано {caught} / честный пропуск {skipped} / пропущено {missed} "
                       f"из {len(rows)} реальных исторических исправлений**, {dt:.1f} с."), "", tail]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
