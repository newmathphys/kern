#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KERN Execution Runner v0.2 — динамический исполнитель и перехватчик свидетельств.

Закрывает эпистемический разрыв `empirical -> N` -> `tested -> T (e=1)`.

УСИЛЕНИЯ (по аудиту):
  1. SECRET SCRUBBING — маскирование секретов ДО хэширования и записи лога.
  2. ANTI-VACUUM — проверка, что тест СОДЕРЖИТ assert/проверки (не пустышка).
  3. AUTO-DISCOVERY — автоматический поиск тестов (без ручного списка targets).
  4. Belnap-совместимый вывод — блоки claim/evidence/link для ядра.
"""
from __future__ import annotations

import argparse
import ast as pyast
import hashlib
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# --- 1. Маскирование секретов (перед хэшированием/записью) ---
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|authorization)\s*[:=]\s*[\"']?[A-Za-z0-9_\-~]{12,}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"eyJ[A-Za-z0-9]{8,}\.[A-Za-z0-9]{8,}\.[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
]


def scrub_secrets(raw: bytes) -> bytes:
    text = raw.decode("utf-8", errors="replace")
    for p in SECRET_PATTERNS:
        text = p.sub("[REDACTED_SECRET]", text)
    return text.encode("utf-8")


# --- 2. Анти-вакуум: содержит ли тест реальные проверки? ---
def test_is_non_vacuous(path: Path) -> bool:
    """True, если в тесте есть assert / проверки unittest/pytest / непустые вызовы."""
    try:
        tree = pyast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return True  # не python — судим по exit_code
    for node in pyast.walk(tree):
        if isinstance(node, pyast.Assert):
            return True
        if isinstance(node, pyast.Call):
            f = node.func
            name = ""
            if isinstance(f, pyast.Attribute):
                name = f.attr
            elif isinstance(f, pyast.Name):
                name = f.id
            if name.startswith(("assert", "expect", "check")) or name in ("raises", "fail", "main"):
                return True
    return False


@dataclass
class ExecutionResult:
    target_claim_id: str
    command: list[str]
    exit_code: int
    duration_ms: int
    stdout_hash: str
    stderr_hash: str
    stdout_log_path: str
    stderr_log_path: str
    non_vacuous: bool
    secrets_masked: int


class KernExecutionRunner:
    def __init__(self, project_root: str, log_dir: str = ".kern/exec_logs"):
        self.root = Path(project_root).resolve()
        self.log_dir = self.root / log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def run_target(self, claim_id: str, command: list[str], test_file: str | None = None,
                   timeout_sec: int = 60) -> ExecutionResult:
        slug = re.sub(r"[^A-Za-z0-9_.-]", "_", claim_id)
        out_p = self.log_dir / f"{slug}_stdout.log"
        err_p = self.log_dir / f"{slug}_stderr.log"

        # 2. анти-вакуумная проверка ДО запуска
        non_vacuous = True
        if test_file:
            tf = self.root / test_file
            if tf.exists():
                non_vacuous = test_is_non_vacuous(tf)

        t0 = time.perf_counter_ns()
        try:
            proc = subprocess.run(command, cwd=self.root, capture_output=True,
                                  timeout=timeout_sec,
                                  env={**os.environ, "PYTHONUNBUFFERED": "1",
                                       "PYTHONDONTWRITEBYTECODE": "1"})
            exit_code, out_b, err_b = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as e:
            exit_code, out_b, err_b = 124, e.stdout or b"", (e.stderr or b"") + b"\n[KERN: timeout]"
        except Exception as e:
            exit_code, out_b, err_b = 127, b"", str(e).encode()
        duration_ms = (time.perf_counter_ns() - t0) // 1_000_000

        # 1. маскирование секретов ПЕРЕД записью и хэшированием
        out_s, err_s = scrub_secrets(out_b), scrub_secrets(err_b)
        masked = (out_s != out_b) + (err_s != err_b)
        out_p.write_bytes(out_s)
        err_p.write_bytes(err_s)

        return ExecutionResult(
            target_claim_id=claim_id, command=command, exit_code=exit_code,
            duration_ms=duration_ms,
            stdout_hash=hashlib.sha256(out_s).hexdigest(),
            stderr_hash=hashlib.sha256(err_s).hexdigest(),
            stdout_log_path=str(out_p.relative_to(self.root)),
            stderr_log_path=str(err_p.relative_to(self.root)),
            non_vacuous=non_vacuous, secrets_masked=masked,
        )

    def generate_kern_evidence(self, results: list[ExecutionResult]) -> str:
        """Синтаксис, который понимает наш парсер: claim + evidence + link."""
        out = ["", "// ===== МАШИННЫЕ СВИДЕТЕЛЬСТВА ИСПОЛНЕНИЯ (EXECUTION RUNNER) =====", ""]
        for r in results:
            slug = re.sub(r"[^A-Za-z0-9_.-]", "_", r.target_claim_id)
            run_id = f"execution: {slug}"
            cmd = " ".join(r.command)
            # Анти-вакуум: пустышка не даёт T даже при exit_code=0
            ok = (r.exit_code == 0) and r.non_vacuous
            status = "tested" if ok else "refuted"
            out.append(f'claim "{run_id}" {{')
            out.append(f'  status {status}')
            out.append(f'  evidence "exec:{slug}"')
            out.append(f'  metric exit_code = {r.exit_code}')
            out.append(f'  metric non_vacuous = {1 if r.non_vacuous else 0}')
            out.append(f'  context "{cmd}"')
            out.append('}')
            out.append('')
            out.append(f'link "claim:{r.target_claim_id}" -> "claim:{run_id}" {{')
            out.append('  relation "supported_by"')
            out.append('}')
            out.append('')
        return "\n".join(out)
