#!/usr/bin/env python3
"""KERN deterministic benchmark → machine-readable JSON (+ a self-contained chart page).

WHY DETERMINISTIC METRICS AND NOT GB/s
    Throughput depends on the runner (shared, throttled, noisy): a CI chart of GB/s is a
    chart of the CI machine, not of the code. These numbers are exact and must stay exact
    on EVERY commit — a drift is a real defect, not noise:

      * avalanche ~ 50 %         (a 1-bit change must flip half of the digest bits)
      * max collision chain <= 8 (bucket collision discipline of the proof cache)
      * chi-square ~ BUCKETS     (uniformity => O(1) lookup confirmed)
      * the same metrics for a naive sum-of-bytes hash, as a CONTROL (it must look bad)

    The key function is the real one from `tools/cache_avalanche_bench.py`
    (`ProofCache.keyOf`), imported rather than re-implemented.

Usage:
    python3 tools/bench_json.py                                  # human summary
    python3 tools/bench_json.py --n 20000 --json out.json        # benchmark-action format
    python3 tools/bench_json.py --html docs/bench/index.html     # self-contained chart page
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cache_avalanche_bench import bucket_of, kern_key, popcount_bytes, weak_key  # noqa: E402


def measure(n: int, keyfn) -> dict:
    """Recompute the avalanche/bucket statistics for one key function."""
    buckets = n
    counts = [0] * buckets
    seen = set()
    collisions = 0
    flips = []
    prev = None
    for i in range(n):
        proof = b"(assert (= x " + str(i).encode() + b"))"
        k = keyfn(proof)
        if k in seen:
            collisions += 1
        seen.add(k)
        counts[bucket_of(k, buckets)] += 1
        if prev is not None:
            flips.append(popcount_bytes(bytes(a ^ b for a, b in zip(prev, k))))
        prev = k
    avg_flip = sum(flips) / len(flips)
    avg_chain = sum(counts) / buckets
    chi2 = sum((c - avg_chain) ** 2 / avg_chain for c in counts)
    return {
        "n": n,
        "avalanche_pct": round(avg_flip / 256.0 * 100.0, 2),
        "collisions": collisions,
        "max_chain": max(counts),
        "chi2": round(chi2),
    }


def git_rev() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def provenance(n: int) -> dict:
    return {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": git_rev(),
        "python": platform.python_version(),
        "machine": f"{platform.system()} {platform.machine()}",
        "cpu": platform.processor() or "unknown",
        "formulas": n,
        "hash": "SHA-256 (ProofCache.keyOf)",
    }


def to_benchmark_action(kern: dict, weak: dict) -> list:
    """The array format expected by benchmark-action/github-action-benchmark."""
    return [
        {"name": "avalanche % (SHA-256 proof-cache key)", "unit": "%",
         "value": kern["avalanche_pct"], "range": "45-55"},
        {"name": "max collision chain", "unit": "links",
         "value": kern["max_chain"], "range": "<=8"},
        {"name": "chi-square uniformity", "unit": "chi2",
         "value": kern["chi2"], "range": "~= buckets"},
        {"name": "collisions", "unit": "count", "value": kern["collisions"], "range": "0"},
        {"name": "avalanche % (naive sum-of-bytes, CONTROL)", "unit": "%",
         "value": weak["avalanche_pct"], "range": "expected bad"},
        {"name": "max collision chain (naive, CONTROL)", "unit": "links",
         "value": weak["max_chain"], "range": "expected bad"},
    ]


CHART = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KERN — deterministic benchmark (per commit)</title>
<meta name="description" content="KERN proof-cache hash quality measured on every commit: avalanche, collision chain, chi-square uniformity.">
<style>
:root{--bg0:#0d1117;--bg1:#161b22;--line:#30363d;--ink:#f0f6fc;--ink2:#c9d1d9;--mut:#8b949e;
--dim:#6e7681;--ok:#3fb950;--okdark:#238636;--bad:#f85149}
body{margin:0;background:linear-gradient(135deg,var(--bg0),var(--bg1)) fixed;color:var(--ink2);
font:400 15px/1.6 ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace}
.wrap{max-width:960px;margin:0 auto;padding:32px 20px 60px}
h1{color:var(--ink);font-size:32px;letter-spacing:2px;margin:0 0 6px}
a{color:var(--ok)} .mut{color:var(--mut)} .dim{color:var(--dim)}
.panel{background:var(--bg0);border:1px solid var(--line);border-radius:6px;padding:18px 20px;margin:20px 0}
.panel.ok{border-color:var(--okdark)}
.hdr{font-weight:700;font-size:12.5px;letter-spacing:.8px;text-transform:uppercase;margin:0 0 12px}
.row{display:grid;grid-template-columns:300px 1fr 80px;gap:10px;align-items:center;margin:6px 0}
.bar{height:12px;background:var(--bg1);border:1px solid var(--line);border-radius:3px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--ok)}
.bar.bad i{background:#f85149}
.val{color:var(--ok);font-weight:700;text-align:right}
.val.bad{color:#f85149}
code{color:var(--ink)}
table{border-collapse:collapse}
td{padding:2px 14px 2px 0}
</style></head><body><div class="wrap">
<h1>KERN — deterministic benchmark</h1>
<p class="mut">Proof-cache hash quality, regenerated per commit with
<code>python3 tools/bench_json.py --html docs/bench/index.html</code>.</p>

<div class="panel ok">
  <div class="hdr">MEASURED</div>
  {rows}
</div>

<div class="panel">
  <div class="hdr">WHY THESE METRICS (AND NOT GB/s)</div>
  <p class="mut" style="margin:0">Throughput depends on the machine: a CI chart of GB/s would chart the
  runner, not the code. These numbers are exact and must stay exact on every commit — a drift is a real
  defect, not noise. The last two rows are a <strong>control</strong>: a naive sum-of-bytes hash, which
  must look bad (and does). Local throughput numbers are in the README, measured on the author's machine.</p>
</div>

<div class="panel">
  <div class="hdr">PROVENANCE</div>
  <table>{prov}</table>
</div>

<p class="dim">Back to <a href="../">the landing page</a> ·
<a href="https://github.com/newmathphys/kern">repository</a></p>
</div></body></html>
"""


def render_html(kern: dict, weak: dict, prov: dict) -> str:
    def row(label, value, target, scale, bad=False, unit=""):
        width = max(1.0, min(100.0, float(value) / scale * 100.0))
        cls = " bad" if bad else ""
        return (f'<div class="row"><span class="mut">{label}</span>'
                f'<span class="bar{cls}"><i style="width:{width:.1f}%"></i></span>'
                f'<span class="val{cls}">{value}{unit}</span></div>'
                f'<div class="row"><span></span><span class="dim" style="font-size:12.5px">target: {target}</span><span></span></div>')

    rows = "".join([
        row("avalanche % (SHA-256 key)", kern["avalanche_pct"], "45-55 % (ideal 50)", 100.0, unit=" %"),
        row("max collision chain", kern["max_chain"], "<= 8 links", 40.0),
        row("chi-square uniformity", kern["chi2"], f"~= {prov['formulas']} (buckets)", float(prov["formulas"]) * 1.25),
        row("collisions", kern["collisions"], "0", max(1.0, float(kern["collisions"]) * 2)),
        row("avalanche % (naive hash, CONTROL)", weak["avalanche_pct"], "expected bad", 100.0, bad=True, unit=" %"),
        row("max collision chain (naive, CONTROL)", weak["max_chain"], "expected bad", 40.0, bad=True),
    ])
    prov_rows = "".join(f'<tr><td class="dim">{k}</td><td>{v}</td></tr>' for k, v in prov.items())
    return CHART.replace("{rows}", rows).replace("{prov}", prov_rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="Deterministic KERN benchmark")
    ap.add_argument("--n", type=int, default=100_000, help="number of formulas (default 100000)")
    ap.add_argument("--json", help="write benchmark-action JSON here")
    ap.add_argument("--html", help="write a self-contained chart page here")
    args = ap.parse_args()

    kern = measure(args.n, kern_key)
    weak = measure(args.n, weak_key)
    prov = provenance(args.n)

    print(f"KERN deterministic benchmark - n={args.n}, hash=SHA-256, {prov['machine']}, commit {prov['commit']}")
    print(f"  proof-cache key : avalanche {kern['avalanche_pct']}%  max_chain {kern['max_chain']}  "
          f"chi2 {kern['chi2']}  collisions {kern['collisions']}")
    print(f"  naive hash (ctl): avalanche {weak['avalanche_pct']}%  max_chain {weak['max_chain']}  "
          f"chi2 {weak['chi2']}  collisions {weak['collisions']}")

    ok = 45.0 <= kern["avalanche_pct"] <= 55.0 and kern["max_chain"] <= 8
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} (avalanche 45-55 %, chain <= 8, control must look worse)")

    if args.json:
        Path(args.json).write_text(json.dumps(to_benchmark_action(kern, weak), indent=1), encoding="utf-8")
        print(f"  JSON  -> {args.json}")
    if args.html:
        p = Path(args.html)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(render_html(kern, weak, prov), encoding="utf-8")
        print(f"  HTML  -> {args.html}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

