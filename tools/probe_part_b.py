#!/usr/bin/env python3
"""Part Б: поиск РЕАЛЬНЫХ пар коммитов целевого домена БЕЗ GitHub REST API.

Клон уже сделан обычным git (Smart HTTP, без лимита 60/час). Здесь только локальные
операции: git log по сообщениям-исправлениям, затем ЖЕЛЕЗНЫЙ критерий — находка
`--xray` в изолированной целевой функции есть на bug_commit и исчезает на fix_commit.
Печатает готовые записи cases.json только для подтверждённых пар.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/mrbritneyxxx/Рабочий стол/kern")
sys.path.insert(0, str(ROOT / "tools"))

KW = re.compile(r"fix|bug|incorrect|wrong|overflow|underflow|index|division|divide|"
                r"zero|bound|edge|off.by.one|panic|segfault", re.I)


def git(args, cwd, timeout=120):
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def candidates(repo: Path, limit=40):
    """Коммиты с «исправительными» сообщениями, у которых есть parent и один файл .c."""
    rc, out = git(["log", "--no-merges", "--pretty=%H|%P|%s", "-n", "400", "--", "."], repo)
    res = []
    for ln in out.splitlines():
        parts = ln.split("|", 2)
        if len(parts) != 3:
            continue
        sha, parents, subj = parts
        if not KW.search(subj) or not parents.strip():
            continue
        parent = parents.split()[0]
        rc, files = git(["show", "--pretty=", "--name-only", sha], repo)
        cs = [f for f in files.splitlines() if f.endswith(".c")]
        if len(cs) == 1:
            res.append((sha, parent, cs[0], subj))
        if len(res) >= limit:
            break
    return res


def main():
    from run_time_machine import iso_extract, xray_findings, at_commit
    import tempfile
    import shutil

    found = []
    for name in ("C", "Python"):
        repo = Path("/tmp/tm_part_b") / name
        if not (repo / ".git").exists():
            print(f"[{name}] клона нет — пропуск")
            continue
        pts = candidates(repo)
        print(f"[{name}] кандидатов с исправительными сообщениями: {len(pts)}")
        for sha, parent, path, subj in pts:
            try:
                at_commit(repo, parent)
                src = (repo / path).read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            fnames = re.findall(r"(?m)^[A-Za-z_][\w \*]*\b(\w+)\s*\([^;]*\)\s*\{", src)
            shown = 0
            for fn in dict.fromkeys(fnames):
                if fn in ("if", "for", "while", "switch", "main"):
                    continue
                body_bug = iso_extract(repo, path, fn, "c")
                if not body_bug:
                    continue
                tmp = Path(tempfile.mkdtemp(prefix="pb-"))
                pb = tmp / f"{fn}_bug.c"
                pb.write_text(body_bug, encoding="utf-8")
                fb, nb = xray_findings(pb)
                shutil.rmtree(tmp, ignore_errors=True)
                if not fb:
                    continue
                at_commit(repo, sha)
                body_fix = iso_extract(repo, path, fn, "c")
                if not body_fix:
                    continue
                tmp = Path(tempfile.mkdtemp(prefix="pb-"))
                pf = tmp / f"{fn}_fix.c"
                pf.write_text(body_fix, encoding="utf-8")
                ff, nf = xray_findings(pf)
                shutil.rmtree(tmp, ignore_errors=True)
                gone = fb - ff
                if gone:
                    found.append({"repo": name, "path": path, "func": fn, "bug_commit": parent,
                                  "fix_commit": sha, "subject": subj,
                                  "gone": sorted(gone)[:3], "bug_note": nb[:120]})
                    print(f"  CAUGHT {name}/{path}:{fn} {parent[:10]}->{sha[:10]} | {subj[:50]}")
                    print(f"        исчезло: {sorted(gone)[0][:110]}")
                    shown += 1
                if shown >= 2:
                    break
    Path("/tmp/part_b_found.json").write_text(
        json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ВСЕГО подтверждено железным критерием: {len(found)}")


if __name__ == "__main__":
    main()
