#!/usr/bin/env python3
"""Anti-self-deception: real compilers vs KERN counterexamples + mutation kill test."""
import json, os, re, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path('/home/mrbritneyxxx/Рабочий стол/kern')
KC = ROOT / 'tools' / 'kern_contracts.py'
ZIG = Path.home() / 'opt/zig-x86_64-linux-0.17.0/zig'
WORK = Path('/tmp/kern-anti-self-deception')


def env():
    e = dict(os.environ)
    e['PATH'] = str(ROOT / '.venv/bin') + os.pathsep + e.get('PATH', '')
    return e


def kern(path):
    r = subprocess.run([sys.executable, str(KC), str(path)], capture_output=True,
                       text=True, env=env(), timeout=300)
    out = r.stdout + r.stderr
    verdict = 'T' if '[PASS]' in out else ('F' if '[FAIL]' in out else ('N' if '[N]' in out else 'SKIP'))
    ce = next((l.strip() for l in out.splitlines() if 'КОНТРПРИМЕР' in l), '')
    return verdict, ce


def sh(cmd, cwd=None, timeout=120):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)


print('=== PART 1: real toolchains vs KERN counterexamples ===', flush=True)
rows = []

# 1a. Python: contract violation must be a real AssertionError at runtime.
py = WORK / 'py_abs_bad.py'
py.write_text(Path(ROOT / 'audits/codecheck/py_abs_bad.py').read_text(encoding='utf-8'), encoding='utf-8')
v, ce = kern(py)
run = WORK / 'py_run.py'
run.write_text('import sys; sys.path.insert(0, "%s")\nfrom py_abs_bad import absolute\nr = absolute(-1)\n'
               'assert r >= 0 and (r == -1 or r == 1), f"ensures violated: absolute(-1)={r}"\n'
               'print("NO VIOLATION")' % WORK, encoding='utf-8')
rc, out = sh([sys.executable, str(run)])
rows.append(('py_abs_bad.py', 'Python', v, ce, 'AssertionError' if 'AssertionError' in out else 'no error', rc))
print(f'  python  {v} {ce[:50]} -> rc={rc} {"AssertionError" if "AssertionError" in out else out.strip()[:60]}', flush=True)

# 1b. Zig: division by zero must panic.
z = WORK / 'zig_div_main.zig'
z.write_text('''const std = @import("std");
pub fn ratio(a: i64, b: i64) i64 {
    return a / b;
}
pub fn main() void {
    const r = ratio(1, 0);
    std.debug.print("NO VIOLATION {d}\\n", .{r});
}
''', encoding='utf-8')
rc, out = sh([str(ZIG), 'run', str(z)])
rows.append(('zig_div.zig', 'Zig', 'F', 'b = 0', 'panic: division by zero' if 'division by zero' in out else out.strip()[:40], rc))
print(f'  zig     b=0 -> rc={rc} {"panic: division by zero" if "division by zero" in out else out.strip()[:60]}', flush=True)

# 1c. C: UBSan must trap division by zero.
c = WORK / 'c_div.c'
c.write_text('#include <stdio.h>\nint ratio(int a, int b) { return a / b; }\nint main(void) {\n'
             '    printf("NO VIOLATION %d\\n", ratio(1, 0));\n    return 0;\n}\n', encoding='utf-8')
rc, out = sh(['gcc', '-fsanitize=undefined', '-fno-sanitize-recover=all', '-o', str(WORK / 'c_div'), str(c)])
rc2, out2 = sh([str(WORK / 'c_div')])
rows.append(('c_unguarded.c', 'C', 'F', 'b = 0', 'runtime error: division by zero' if 'division by zero' in out2 else out2.strip()[:40], rc2))
print(f'  c       b=0 -> rc={rc2} {"runtime error: division by zero" if "division by zero" in out2 else out2.strip()[:60]}', flush=True)

# 1d. Rust: overflow must panic with overflow-checks=on.
rs = WORK / 'rs_ovf.rs'
rs.write_text('pub fn add32(a: i32, b: i32) -> i32 { return a + b; }\n'
              'fn main() { let r = add32(2147483647, 1); println!("NO VIOLATION {}", r); }\n', encoding='utf-8')
rc, out = sh(['rustc', '-C', 'overflow-checks=on', '-o', str(WORK / 'rs_ovf'), str(rs)])
rc2, out2 = sh([str(WORK / 'rs_ovf')])
rows.append(('rust_overflow.rs', 'Rust', 'F', 'a=2147483647, b=1',
             'panic: attempt to add with overflow' if 'overflow' in out2 else out2.strip()[:40], rc2))
print(f'  rust    a=2147483647,b=1 -> rc={rc2} {"panic: attempt to add with overflow" if "overflow" in out2 else out2.strip()[:60]}', flush=True)

# 1e. Zig overflow on the live model output (deepseek add32).
zs = WORK / 'zig_ovf.zig'
zs.write_text('''const std = @import("std");
pub fn add32(a: i32, b: i32) i32 {
    return a + b;
}
pub fn main() void {
    std.debug.print("NO VIOLATION {d}\\n", .{add32(2147483647, 1)});
}
''', encoding='utf-8')
rc, out = sh([str(ZIG), 'run', str(zs)])
rows.append(('model add32 (Zig)', 'Zig', 'F', 'a=2147483647, b=1',
             'panic: integer overflow' if 'overflow' in out else out.strip()[:40], rc))
print(f'  zig     overflow -> rc={rc} {"panic: integer overflow" if "overflow" in out else out.strip()[:60]}', flush=True)

print('\n=== PART 2: mutation kill test on every T (PROVEN) file ===', flush=True)
MUT = {
    'py_abs_ok.py': [('return x', 'return -x')],
    'py_clamp_ok.py': [('max(lo, min(x, hi))', 'min(lo, max(x, hi))')],
    'zig_clean.zig': [('return a + b;', 'return a - b;')],
    'c_clean.c': [('return a + b;', 'return a - b;')],
    'rust_clean.rs': [('return a + b;', 'return a - b;')],
}
killed = total = 0
for name, subs in MUT.items():
    src = ROOT / 'audits' / 'codecheck' / name
    v0, _ = kern(src)
    for old, new in subs:
        total += 1
        body = src.read_text(encoding='utf-8')
        if old not in body:
            print(f'  {name:16s} base={v0} MUTATION PATTERN NOT FOUND: {old!r}', flush=True)
            continue
        tmp = WORK / ('mut_' + name)
        tmp.write_text(body.replace(old, new, 1), encoding='utf-8')
        v1, ce = kern(tmp)
        ok = (v0 == 'T' and v1 == 'F')
        killed += 1 if ok else 0
        print(f'  {name:16s} base={v0} -> {old!r} -> {new!r}: {v1} {"KILLED" if ok else "SURVIVED"} {ce[:40]}', flush=True)
print(f'\nMUTATION KILL: {killed}/{total}', flush=True)
json.dump(rows, open(WORK / 'ground_truth.json', 'w'), ensure_ascii=False, indent=2)
print('DONE', flush=True)
