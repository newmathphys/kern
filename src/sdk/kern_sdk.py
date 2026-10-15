#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KERN Python SDK — тонкая обёртка над CLI `kernc`/`kernx`.

СТАТУС (честно): рабочий скелет. Он вызывает РЕАЛЬНЫЕ бинарники через
subprocess и разбирает их вывод. Чего НЕТ: HTTP-демона, LLM-оркестратора,
RLAIF-цикла — см. docs/CAPABILITY_STATUS.md.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


class KernError(RuntimeError):
    pass


def _which(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise KernError(f"{name} не найден в PATH (соберите: zig build)")
    return path


@dataclass
class Result:
    ok: bool
    output: str


class KERN:
    """Клиент ядра KERN."""

    def __init__(self, kernc: str = "kernc", kernx: str = "kernx") -> None:
        self.kernc = _which(kernc)
        self.kernx = _which(kernx)

    @staticmethod
    def _run(exe: str, args: list[str]) -> Result:
        proc = subprocess.run([exe, *args], capture_output=True, text=True)
        out = (proc.stdout or "") + (proc.stderr or "")
        return Result(ok=proc.returncode == 0, output=out)

    # --- ядро образа (.kimg) ---
    def build(self, kern_file: str, out: str = "release.kimg", bytecode: str | None = None) -> Result:
        args = ["build", kern_file, "-o", out]
        if bytecode:
            args += ["--bytecode", bytecode]
        return self._run(self.kernc, args)

    def check_integrity(self, image: str) -> Result:
        return self._run(self.kernc, ["check-integrity", image])

    def ls(self, image: str) -> Result:
        return self._run(self.kernc, ["ls", image])

    def cat(self, image: str, path: str) -> Result:
        return self._run(self.kernc, ["cat", image, path])

    def verify(self, image: str) -> Result:
        return self._run(self.kernc, ["verify", image])

    def unify(self, human_max: int, ai_min: int) -> Result:
        return self._run(self.kernc, ["unify", str(human_max), str(ai_min)])

    def handoff(self, image: str) -> Result:
        return self._run(self.kernc, ["handoff", image])

    # --- проект (.kern, KERN-Next) ---
    def next_build(self, kern_file: str, out: str = ".kernnext", scope: str = "default") -> Result:
        return self._run(self.kernx, ["build", kern_file, "--out", out, "--scope", scope])

    def next_status(self, kern_file: str) -> Result:
        return self._run(self.kernx, ["status", kern_file])


def generate_safe_code(prompt: str, limits: dict | None = None) -> str:
    """Заготовка SwarmOrchestrator из спецификации.

    Здесь НЕТ вызова LLM — поэтому честно поднимаем NotImplementedError,
    а не возвращаем фальшивый «безопасный код».
    """
    raise NotImplementedError(
        "SwarmOrchestrator требует LLM-бэкенд; в этом репозитории его нет."
    )


if __name__ == "__main__":
    import sys

    try:
        k = KERN()
    except KernError as exc:
        print(f"[SDK] {exc}")
        sys.exit(1)
    print("[SDK] kernc найден:", k.kernc)
    r = k.check_integrity("tests/fixtures/valid_v1_3.kimg")
    print(r.output.strip())
