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
    if len(short) == 40:
        return short          # полный SHA уже в кейсе: API не нужен (лимит 60/час)
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


C_PRELUDE = (
    "typedef struct cJSON {\n"
    "    struct cJSON *next;\n    struct cJSON *prev;\n    struct cJSON *child;\n"
    "    int type;\n    char *valuestring;\n    int valueint;\n    double valuedouble;\n"
    "    char *string;\n} cJSON;\n"
    "#define CJSON_NESTING_LIMIT 1000\n"
)


def iso_extract(workdir: Path, file_rel: str, func: str, lang: str) -> str | None:
    """Текст ОДНОЙ целевой функции из файла этого коммита (фон большого файла исключён)."""
    src = (workdir / file_rel).read_text(encoding="utf-8", errors="replace")
    if lang == "python":
        import ast
        tree = ast.parse(src)
        for n in ast.walk(tree):
            if isinstance(n, ast.FunctionDef) and n.name == func:
                opened = [k for k in ast.walk(n) if isinstance(k, (ast.Slice,))]
                _ = opened
                return "\n".join(src.splitlines()[n.lineno - 1:n.end_lineno]) + "\n"
        return None
    m = re.search(rf"(?m)^[^\n;]*\b{re.escape(func)}\s*\(", src)
    if not m:
        return None
    i = src.index("{", m.end())
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    start = src.rfind("\n", 0, m.start()) + 1
    body = src[start:j + 1]
    body = re.sub(r"CJSON_PUBLIC\(\s*([\w ]+?)\s*\)", r"\1", body)
    body = re.sub(r"CJSON_PUBLIC\(\s*(\w+)\s*\*\s*\)", r"\1 *", body)
    return C_PRELUDE + "\n" + body + "\n"


def xray_findings(path: Path) -> tuple[set[str], str]:
    """Находки --xray для ОДНОГО изолированного файла + сводка/причина пропуска."""
    env = dict(os.environ, PATH=f"{ROOT}/.venv/bin:" + os.environ.get("PATH", ""))
    rc, out = sh([PY, str(ROOT / "tools" / "kern_contracts.py"), "--xray", str(path)],
                 timeout=300, env=env)
    if "Traceback" in out:
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        return set(), f"CRASH: {last[:150]}"
    finds = {ln.strip() for ln in out.splitlines()
             if ln.strip().startswith("[") and re.search(r"\[(PATH|BRANCH|GUARD|LOOP|TAINT|OOB|NULL)\]", ln)}
    summ = next((ln.strip() for ln in out.splitlines() if "XRAY SUMMARY" in ln), "")
    skip = next((ln.strip() for ln in out.splitlines() if ln.strip().startswith("skip:")), "")
    if not finds and skip:
        return set(), f"{summ} | {skip}"[:200]
    return finds, summ[:160]


def kern_strict(case: dict, workdir: Path, bug: str, fix: str) -> tuple[str, str, dict]:
    """ЖЕЛЕЗНЫЙ критерий: находка есть в целевой функции на баге и ИСЧЕЗАЕТ на фиксе."""
    fn = case.get("func", "")
    lang = case["lang"]
    res: dict[str, set[str]] = {}
    info: dict[str, str] = {}
    for tag, sha in (("bug", bug), ("fix", fix)):
        at_commit(workdir, sha)
        body = iso_extract(workdir, case["path"], fn, lang)
        if body is None:
            return "NOT_CONFIRMED", f"функция {fn} не найдена в {case['path']}", {}
        ext = ".py" if lang == "python" else ".c"
        iso = Path(tempfile.mkdtemp(prefix="kern-iso-")) / f"{fn}_{tag}{ext}"
        iso.write_text(body, encoding="utf-8")
        f, note = xray_findings(iso)
        shutil.rmtree(iso.parent, ignore_errors=True)
        res[tag], info[tag] = f, note
        if note.startswith("CRASH"):
            return "CRASH", note, {"bug": sorted(res.get("bug", ())), "fix": sorted(res.get("fix", ()))}
    gone = res["bug"] - res["fix"]
    detail = (f"находок баг={len(res['bug'])} фикс={len(res['fix'])}; исчезло {len(gone)}"
              f" | {info.get('bug','')[:120]}")
    payload = {"bug": sorted(res["bug"]), "fix": sorted(res["fix"]), "gone": sorted(gone)}
    if gone:
        return "CAUGHT", detail, payload
    if not res["bug"] and "skip:" in info.get("bug", ""):
        return "SKIP", info["bug"], payload
    return "NOT_CONFIRMED", detail, payload



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
                for rel, content in c.get("setup_files", []):
                    sp = wd / rel
                    sp.parent.mkdir(parents=True, exist_ok=True)
                    sp.write_text(content, encoding="utf-8")
                if c["lang"] == "python":
                    ok, det = run_python_oracle(wd, c["module"], c["oracle_py"])
                    oracle[tag] = "OK" if ok else "FAIL"
                else:
                    inc = "cJSON.c" if "cjson" in c["repo"].lower() else "jsmn.h"
                    st, det = run_c_oracle(wd, inc, c["oracle_c"], "")
                    oracle[tag] = st
                oracle[f"{tag}_detail"] = det
            def _macth(actual, want):
                a, w = str(actual).lower(), str(want).lower()
                return w in a or a in w
            exp = c.get("expect_oracle")
            if exp:
                reproduced = _macth(oracle["bug"], exp["bug"]) and _macth(oracle["fix"], exp["fix"])
            else:
                reproduced = (oracle["bug"] in ("FAIL", "SEGV")
                              and oracle["fix"] in ("OK", "clean"))
            at_commit(wd, bug)
            if c.get("dropped"):
                rows.append({**c, "status": "DROPPED", "oracle": oracle,
                             "kern_status": "—", "kern_detail": c["dropped"],
                             "findings": {}})
                print("   DROPPED:", c["dropped"][:110], flush=True)
                continue
            if c["kern"].get("mode") == "skip":
                kstat, kdet, kpay = "SKIP", c["kern"].get("why", "вне модели kernc"), {}
            else:
                kstat, kdet, kpay = kern_strict(c, wd, bug, fix)
            # Приоритет: сбой загрузки > наш невоспроизведённый оракул > вердикт KERN.
            # Иначе невоспроизведённый оракул маскировался бы под «честный пропуск».
            if not reproduced:
                st = "ORACLE_UNVERIFIED"
            elif kstat in ("CAUGHT", "SKIP", "CRASH", "NOT_CONFIRMED"):
                st = kstat
            else:
                st = "NOT_CONFIRMED"
            rows.append({**c, "status": st, "oracle": oracle, "kern_status": kstat,
                         "kern_detail": kdet, "findings": kpay, "reproduced": reproduced})
            print(f"   оракул bug={oracle['bug']} fix={oracle['fix']} | KERN={kstat} -> {st}", flush=True)
    finally:
        if not a.keep:
            shutil.rmtree(tmp, ignore_errors=True)

    dt = time.time() - t0
    cnt = {k: sum(r["status"] == k for r in rows) for k in
           ("CAUGHT", "SKIP", "NOT_CONFIRMED", "CRASH", "ORACLE_UNVERIFIED", "FETCH_FAIL", "DROPPED")}
    write_docs(rows, cnt, dt)
    print(f"ИТОГ: мишеней {len(rows)} | поймано {cnt['CAUGHT']} | пропуск(вне модели) {cnt['SKIP']} | "
          f"не подтверждено {cnt['NOT_CONFIRMED']} | СБОЙ KERN {cnt['CRASH']} | "
          f"оракул не подтвердил {cnt['ORACLE_UNVERIFIED']} | "
          f"сбой загрузки {cnt['FETCH_FAIL']} | исключено {cnt['DROPPED']} | {dt:.1f} с")
    (ROOT / "docs" / "time_machine_result.json").write_text(
        json.dumps({"counts": cnt, "total": len(rows), "seconds": round(dt, 1),
                    "rows": [{k: r.get(k) for k in ("id", "repo", "bug_commit", "fix_commit",
                                                    "status", "kern_status", "kern_detail", "findings")}
                             for r in rows]}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0

def write_docs(rows, cnt, dt):
    def cell(r, idx):
        f = r.get("findings") or {}
        gone = f.get("gone") or []
        if r["status"] == "CAUGHT" and gone:
            return ("finding disappears after fix: " if idx == 0
                    else "находка исчезает после фикса: ") + gone[0][:70]
        return (r.get("kern_detail") or "—")[:95]

    head_en = (
        "# Time Machine: KERN vs. real historical bugs in other people's repositories\n\n"
        "Every target is a **real public commit pair**: `bug_commit` is the parent of the\n"
        "maintainers' own fix (`fix_commit`). Both the defective code and the fix were\n"
        "written by the project authors, not by us.\n\n"
        "**Iron criterion for a win (added after review).** A win counts only if the same\n"
        "finding appears in the *target function in isolation* on `bug_commit` and\n"
        "**disappears** on `fix_commit`. Scanning the whole 3,000-line file was rejected:\n"
        "a background hint elsewhere in the file would have been miscounted as a catch.\n"
        "This criterion invalidated both of our earlier C \"wins\".\n\n"
        "Statuses: caught (iron criterion met), honest skip (outside KERN's model, with\n"
        "the engine's own stated reason), not confirmed (function scanned, no difference),\n"
        "KERN CRASH (a defect in KERN itself), oracle unverified (our reproduction failed,\n"
        "so nothing is claimed).\n\n")
    head_ru = (
        "# Машина времени: KERN против реальных исторических багов чужих репозиториев\n\n"
        "Каждая мишень — **реальная публичная пара коммитов**: `bug_commit` это parent\n"
        "коммита-исправления самих мейнтейнеров (`fix_commit`). И дефектный код, и фикс\n"
        "написали авторы проекта, а не мы.\n\n"
        "**Железный критерий победы (добавлен после ревью).** Победа засчитывается только\n"
        "если одна и та же находка присутствует в *изолированной целевой функции* на\n"
        "`bug_commit` и **исчезает** на `fix_commit`. Сканирование всего файла на 3000\n"
        "строк отвергнуто: фоновый хинт в другом конце файла был бы посчитан как победа.\n"
        "Этот критерий отменил обе наши прежние C-победы.\n\n"
        "Статусы: поймано (критерий выполнен), честный пропуск (вне модели KERN, с\n"
        "собственной формулировкой движка), не подтверждено (функция просканирована,\n"
        "разницы нет), СБОЙ KERN (дефект в самом KERN), оракул не подтвердил (наше\n"
        "воспроизведение не удалось — ничего не заявляем).\n\n")
    cols_en = ["Case", "Repository", "Bug commit", "Fix commit", "Oracle: bug",
               "Oracle: fix", "KERN (strict)", "Result"]
    cols_ru = ["Кейс", "Репозиторий", "Коммит с багом", "Коммит-фикс", "Оракул: баг",
               "Оракул: фикс", "KERN (строго)", "Итог"]
    lbl = {"CAUGHT": ("**caught**", "**поймано**"),
           "SKIP": ("honest skip", "честный пропуск"),
           "NOT_CONFIRMED": ("not confirmed", "не подтверждено"),
           "CRASH": ("**KERN CRASH**", "**СБОЙ KERN**"),
           "ORACLE_UNVERIFIED": ("oracle unverified", "оракул не подтвердил"),
           "DROPPED": ("dropped (our fault)", "исключено (наш брак)"),
           "FETCH_FAIL": ("fetch failed", "сбой загрузки")}
    tail_en = (
        "## What this measures, and what it does not\n\n"
        "A low hit rate here is the honest measurement of KERN in **zero-annotation mode**\n"
        "on code it has never seen: recursion, floating-point arithmetic and iterator\n"
        "laziness fall outside the model and are reported as skips by the engine itself,\n"
        "not hidden by us. No case is counted as caught unless the finding disappears\n"
        "exactly at the maintainers' fix.\n")
    tail_ru = (
        "## Что это измеряет, а что нет\n\n"
        "Низкий hit-rate здесь — честное измерение KERN в **режиме без аннотаций** на коде,\n"
        "которого он никогда не видел: рекурсия, вещественная арифметика и ленивость\n"
        "итераторов лежат вне модели и помечены самим движком как пропуск, а не спрятаны\n"
        "нами. Ни один случай не засчитан как пойманный, если находка не исчезает ровно\n"
        "на исправлении мейнтейнеров.\n")
    for path, head, cols, tail, idx in ((DOC_EN, head_en, cols_en, tail_en, 0),
                                        (DOC_RU, head_ru, cols_ru, tail_ru, 1)):
        lines = [head, "| " + " | ".join(cols) + " |",
                 "|" + "|".join([":--"] * len(cols)) + "|"]
        for r in rows:
            o = r.get("oracle") or {}
            lines.append("| " + " | ".join([
                f"`{r['id']}`",
                f"`{r['repo'].split('github.com/')[-1]}`",
                f"`{r['bug_commit']}`", f"`{r['fix_commit']}`",
                str(o.get("bug", "—")), str(o.get("fix", "—")),
                cell(r, idx).replace("|", "\\|"),
                lbl.get(r["status"], ("—", "—"))[idx]]) + " |")
        if idx == 0:
            summary = (f"**Result: {cnt['CAUGHT']} caught / {cnt['SKIP']} honest skip / "
                       f"{cnt['NOT_CONFIRMED']} not confirmed / {cnt['CRASH']} KERN crash / "
                       f"{cnt['ORACLE_UNVERIFIED']} oracle unverified / "
                       f"{cnt['FETCH_FAIL']} fetch failed out of {len(rows)} real historical "
                       f"fixes**, {dt:.1f} s. **False claims: 0.**")
        else:
            summary = (f"**Итог: поймано {cnt['CAUGHT']} / честный пропуск {cnt['SKIP']} / "
                       f"не подтверждено {cnt['NOT_CONFIRMED']} / СБОЙ KERN {cnt['CRASH']} / "
                       f"оракул не подтвердил {cnt['ORACLE_UNVERIFIED']} / сбой загрузки "
                       f"{cnt['FETCH_FAIL']} из {len(rows)} реальных исторических "
                       f"исправлений**, {dt:.1f} с. **Ложных заявлений: 0.**")
        lines += ["", summary, "", tail]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())


