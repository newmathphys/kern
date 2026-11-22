"""Облачный пробник Zed: живой `cargo test -p gpui` на реальном крейте.

Клонирует zed, вставляет тест на `Pixels` + `RenderGlyphParams`, гоняет его и
пишет в отчёт только строки паники/итога плюс SHA. Ничего не публикует.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

# Интеграционный тест внутри родного workspace Zed: `--test` компилирует
# библиотеку gpui БЕЗ её `#[cfg(test)]`-кода (там сейчас не собирается
# `HitboxId::placeholder`), но сохраняет все `[patch.crates-io]` и
# `[workspace.dependencies]` корневого Cargo.toml.
PROBE_TEST = '''
use std::collections::HashMap;

use gpui::{point, px, FontId, GlyphId, RenderGlyphParams};

#[test]
fn pixels_and_glyph_params_eq_hash_minus_zero() {
    let a = px(0.0);
    let b = -px(0.0);
    assert!(a == b, "Pixels PartialEq is numeric");
    let mut m: HashMap<_, u32> = HashMap::new();
    m.insert(a, 1);
    assert_eq!(m.get(&b).copied(), Some(1), "Pixels Eq/Hash broken on -0.0");

    let ga = RenderGlyphParams {
        font_id: FontId(0),
        glyph_id: GlyphId(0),
        font_size: px(0.0),
        subpixel_variant: point(0u8, 0u8),
        scale_factor: 0.0,
        is_emoji: false,
        subpixel_rendering: false,
        dilation: 0,
    };
    let gb = RenderGlyphParams { font_size: px(-0.0), scale_factor: -0.0, ..ga.clone() };
    assert!(ga == gb, "RenderGlyphParams PartialEq is numeric");
    let mut cache: HashMap<_, u32> = HashMap::new();
    cache.insert(ga, 1);
    assert_eq!(cache.get(&gb).copied(), Some(1),
               "RenderGlyphParams Eq/Hash broken on -0.0");
}
'''

REPORT_KEYS = ("panicked", "test result", "contract broken", "error[E", "Compiling gpui",
               "warning: unused")


def run(cmd, cwd, timeout):
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"
    except FileNotFoundError as exc:
        return 127, str(exc)


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "zed-probe-report.md")
    work = Path(tempfile.mkdtemp(prefix="zed-probe-"))
    dest = work / "zed"
    lines = ["# Zed gpui probe", ""]
    try:
        rc, log = run(["git", "clone", "--depth", "1", "--filter=blob:none",
                       "https://github.com/zed-industries/zed.git", str(dest)],
                      work, timeout=1800)
        if rc != 0:
            lines += ["## clone failed", "", "```text", log[-800:], "```"]
            out.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return 0
        rc, sha = run(["git", "rev-parse", "--short=12", "HEAD"], dest, timeout=60)
        lines.append(f"HEAD: `{sha.strip()}`")

        probe_dir = dest / "crates" / "gpui" / "tests"
        if not (dest / "crates/gpui").is_dir():
            lines += ["", "crates/gpui не найден — структура репозитория изменилась"]
        else:
            probe_dir.mkdir(parents=True, exist_ok=True)
            (probe_dir / "eq_hash_probe.rs").write_text(PROBE_TEST, encoding="utf-8")
            env_rc, log = run(["cargo", "test", "-p", "gpui", "--test", "eq_hash_probe"],
                              dest, timeout=5400)
            keep = [ln for ln in log.splitlines() if any(k in ln for k in REPORT_KEYS)]
            verdict = ("FAILED" if "test result: FAILED" in log
                       else "PASSED" if "test result: ok" in log else "UNKNOWN")
            lines += [f"verdict: **{verdict}** (cargo rc={env_rc})", "", "```text"]
            lines += (keep[:20] or log.strip().splitlines()[-20:])
            lines += ["```"]
    finally:
        shutil.rmtree(work, ignore_errors=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[-12:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
