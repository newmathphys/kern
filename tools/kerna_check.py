#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""`kerna_check` — ГЕЙТ УПАКОВКИ (#494): собранный бинарь ведёт себя как dev.

ЗАЧЕМ. Спайк показал: собранный onefile-бинарь МОЛЧА деградировал (находок 0,
`unreadable 1`, rc=0) из-за четырёх ловушек путей. Без машинного гейта это
вернётся при первой же правке. Гейт собирает НАСТОЯЩИЙ бинарь и проверяет его
в изолированном каталоге.

ЧТО СТЕРЕЖЁТ:
  R1 сборка: бинарь создаётся (`tools/build_kerna.sh`);
  R2 изоляция: бинарь переносится в ПУСТОЙ каталог + `server.json` вшит;
  R3 паритет: на фикстурах находок СТОЛЬКО ЖЕ, сколько в dev-режиме, и
     `unreadable 0` (иначе «упаковано, но глухо»);
  R4 доктор: БЕЗ `z3` — rc=2 и НАЗВАННАЯ причина в stderr (не «находок 0»);
  R5 честный пропуск: без PyInstaller — печатается SKIP; при
     `KERNA_REQUIRE_BUILD=1` это ПРОВАЛ, а не тихое «зелено».

ЗАМЕР-ЭТАЛОН (спайк): 9.8 МБ, старт 253 мс, находок 5/5 на фикстурах.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
FIXTURE = ROOT / "tests" / "fixtures" / "precision_buggy"
EXPECTED_FINDINGS = 5          # столько же, сколько в dev-режиме
NAME = os.environ.get("KERNA_NAME", "kerna")


def _env() -> dict:
    e = dict(os.environ)
    e["PYTHONPATH"] = str(ROOT / "tools")
    return e


def _isolated_env() -> dict:
    """Окружение КАК У КЛИЕНТА: без PYTHONPATH на репозиторий (дефект #513).

    `_env()` подмешивает `ROOT/tools` в PYTHONPATH. Для упакованного бинаря это
    утечка: если собственный импорт из `_MEIPASS` не удался, Python подхватит
    ИСХОДНИКИ из чекаута, и гейт проверит не то, что уезжает клиенту. Именно
    поэтому R6 был зелёным, пока ОПУБЛИКОВАННЫЙ архив молчал (замер #513).
    У клиента репозитория нет — значит и в проверке его быть не должно.
    """
    e = _env()
    e["PYTHONPATH"] = ""
    return e


def _no_solver_env() -> dict:
    """Окружение, в котором решателя заведомо НЕТ (дефект #513, найдено canfail).

    R4/R8 доказывают, что БЕЗ решателя дистрибутив ОТКАЗЫВАЕТ, а не печатает
    «находок 0». Но доктор ищет `z3` по `$Z3 → .venv/bin/z3 → PATH`, и если
    локальный PATH содержит `.venv/bin` (там лежит `z3`), проверка молча теряет
    смысл: решатель находится, отказ не наступает. Поэтому PATH урезается до
    системного, а подсказки `$Z3`/`$KERN_Z3` снимаются.
    """
    e = _isolated_env()
    e["PATH"] = "/usr/bin:/bin"
    for k in ("Z3", "KERN_Z3"):
        e.pop(k, None)
    return e


def _dev_findings() -> int:
    """Эталон: сколько находок даёт НЕупакованный фронтенд."""
    p = subprocess.run([PY, str(ROOT / "tools" / "kern_contracts.py"),
                        "--xray", str(FIXTURE), "--xray-json"],
                       capture_output=True, text=True, timeout=900, cwd=str(ROOT))
    try:
        return int(json.loads(p.stdout)["summary"]["findings"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return -1


def _packaged_findings(bin_path: Path, extra_env: dict | None = None) -> tuple:
    env = dict(os.environ)
    env.pop("KERN_HOST_ROOT", None)
    env.pop("KERN_ROOT", None)
    if extra_env:
        env.update(extra_env)
    p = subprocess.run([str(bin_path), "--xray", str(FIXTURE), "--xray-json"],
                       capture_output=True, text=True, timeout=900,
                       cwd=str(bin_path.parent), env=env)
    try:
        doc = json.loads(p.stdout)
        return (p.returncode, int(doc["summary"]["findings"]),
                int(doc["summary"].get("unreadable", 0)))
    except (json.JSONDecodeError, KeyError, TypeError):
        return (p.returncode, -1, -1)


def main() -> int:
    bad = 0
    base = _dev_findings()
    print(f"[i] #494 эталон dev-режима: находок {base}")
    if base != EXPECTED_FINDINGS:
        print(f"[FAIL] R3: dev-эталон {base}, ожидали {EXPECTED_FINDINGS} — "
              f"сначала почините базовый анализ")
        return 1

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        # ДЕФЕКТ #514 (НАЙДЕНО CANFAIL В CI): здесь стоял `return 0`, то есть
        # гейт, который НЕ МОГ проверить упаковку, рапортовал УСПЕХ — и кейс
        # `kerna` (ломает доктора) не мог покраснеть в принципе: цель зелёная по
        # построению. Теперь это ОТКАЗ (rc=2) с названной причиной и командой
        # установки; осознанный пропуск — только по `KERNA_ALLOW_SKIP=1`.
        msg = ("[!] #514: PyInstaller не установлен — УПАКОВКА НЕ ПРОВЕРЕНА. "
               "Это НЕ «зелено»: без него `make kerna-check` не может отличить "
               "рабочий апплаенс от нерабочего (в CI из-за этого кейс `kerna` "
               "был ВАКУУМНЫМ). Установите: pip install pyinstaller "
               "(или осознанный пропуск: KERNA_ALLOW_SKIP=1).")
        print(msg, file=sys.stderr)
        if os.environ.get("KERNA_ALLOW_SKIP") == "1":
            print("[SKIP] #514: KERNA_ALLOW_SKIP=1 — пропуск ЯВНЫЙ и названный")
            return 0
        if os.environ.get("KERNA_REQUIRE_BUILD") == "1":
            print("[FAIL] R5: KERNA_REQUIRE_BUILD=1 требует сборку")
            return 1
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="kerna_check_"))
    try:
        # R1: сборка
        out = tmp / "dist"
        p = subprocess.run(["bash", str(ROOT / "tools" / "build_kerna.sh"), str(out)],
                           capture_output=True, text=True, timeout=1800,
                           cwd=str(ROOT), env=_env())
        print(p.stdout.strip().splitlines()[-1] if p.stdout.strip() else "")
        bin_path = out / NAME
        if p.returncode != 0 or not bin_path.is_file():
            print(f"[FAIL] R1: сборка не дала бинарь (rc={p.returncode})")
            print((p.stdout + p.stderr)[-400:])
            return 1
        size_mb = bin_path.stat().st_size / 1048576
        print(f"[OK] R1: бинарь собран ({size_mb:.1f} МБ)")

        # R2: изолированный каталог (пустой; server.json внутри упаковки)
        iso = tmp / "iso"
        iso.mkdir()
        iso_bin = iso / NAME
        shutil.copy2(bin_path, iso_bin)

        # R3: паритет БЕЗ kernc/z3 рядом -> доктор обязан назвать отказ
        rc, found, unreadable = _packaged_findings(iso_bin, extra_env=_no_solver_env())
        if rc != 2:
            print(f"[FAIL] R4: без z3 ожидали названный отказ rc=2, получили "
                  f"rc={rc} (находок {found}, unreadable {unreadable})")
            bad += 1
        else:
            print("[OK] R4: без z3 — названный отказ rc=2 (а не «находок 0»)")

        # R8 (#513, НАЙДЕНО CANFAIL). После #499a отказ «нет решателя» дают ДВЕ
        # независимые преграды: доктор (preflight) и ворота решателя ВНУТРИ
        # анализа. R4 требует лишь «rc=2 + названная причина», поэтому его
        # удовлетворяет ЛЮБАЯ из них — и кейс `kerna` (ломает только доктора)
        # стал ВАКУУМНЫМ: замер «поломка внесена, а цель осталась ЗЕЛЁНОЙ».
        # R8 закрепляет ПЕРВУЮ преграду: в пути АНАЛИЗА отказ обязан быть
        # докторским (`KERNA DOCTOR`), то есть до разбора кода. Иначе клиент
        # узнаёт о неполном дистрибутиве только внутри анализа.
        p8 = subprocess.run([str(iso_bin), "--xray", str(FIXTURE), "--xray-json"],
                            capture_output=True, text=True, timeout=900,
                            cwd=str(iso_bin.parent), env=_no_solver_env())
        out8 = (p8.stdout or "") + (p8.stderr or "")
        if p8.returncode == 2 and "KERNA DOCTOR" in out8:
            print("[OK] R8: доктор — ПЕРВАЯ преграда в пути анализа (`KERNA DOCTOR`, rc=2)")
        else:
            print(f"[FAIL] R8: без z3 путь анализа дал rc={p8.returncode}, сообщение "
                  f"доктора {'есть' if 'KERNA DOCTOR' in out8 else 'ОТСУТСТВУЕТ'} — "
                  f"первая преграда ослепла (R4 её маскирует)")
            bad += 1

        # R3 (продолжение): полный дистрибутив -> ПАРИТЕТ с dev
        (iso / "zig-out" / "bin").mkdir(parents=True)
        shutil.copy2(ROOT / "zig-out" / "bin" / "kernc",
                     iso / "zig-out" / "bin" / "kernc")
        (iso / ".venv" / "bin").mkdir(parents=True)
        solver = None
        try:
            sys.path.insert(0, str(ROOT / "tools"))
            import z3bin
            solver = z3bin.find_z3()
        except (ImportError, OSError) as e:                  # класс #198/#457
            # ОЖИДАЕМЫЕ: нет модуля `z3bin` или нет файла решателя. Программные
            # ошибки (NameError/AttributeError/TypeError) НЕ глушим: они обязаны
            # доходить до вызывающего — иначе «паритета нет» станет невидимым.
            print(f"  [i] решатель не найден для изолированной копии: {e}")
            solver = None
        if solver:
            shutil.copy2(solver, iso / ".venv" / "bin" / "z3")
        rc, found, unreadable = _packaged_findings(iso_bin)
        if rc != 0 or found != base or unreadable != 0:
            print(f"[FAIL] R3: упакованный даёт rc={rc}, находок {found} "
                  f"(dev {base}), unreadable {unreadable} — ПАРИТЕТА НЕТ")
            bad += 1
        else:
            print(f"[OK] R3: паритет с dev (находок {found}, unreadable 0)")
        # R6 (#511): `--delta` ВШИТ В БИНАРЬ. Клиент, скачавший только архив, обязан
        # уметь спросить «что стало хуже в этом изменении» БЕЗ чекаута репозитория.
        # Проверяем ПОВЕДЕНИЕ: поведение функции обязано разойтись, и бинарь обязан
        # это НАЗВАТЬ (DIVERGED). Решатель кладём рядом — как в настоящем дистрибутиве.
        d = Path(tempfile.mkdtemp(prefix="kerna_delta_"))
        try:
            solver = None
            try:
                import z3bin                                   # noqa: PLC0415
                solver = z3bin.find_z3()
            except (ImportError, OSError) as e:                 # класс #198/#457
                print(f"  [i] решатель для R6 не найден: {e}")
            if solver:
                (bin_path.parent / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
                shutil.copy2(solver, bin_path.parent / ".venv" / "bin" / "z3")
            # `kernc` ОБЯЗАТЕЛЕН и для дельты: без него SMT-слой честно отвечает
            # «не решено», и DIVERGED не появляется. В настоящем архиве он рядом.
            kernc_src = ROOT / "zig-out" / "bin" / "kernc"
            if kernc_src.is_file():
                (bin_path.parent / "zig-out" / "bin").mkdir(parents=True, exist_ok=True)
                shutil.copy2(kernc_src, bin_path.parent / "zig-out" / "bin" / "kernc")
            for name, body in (("base", "def f(a, b):\n    return a + b\n"),
                               ("head", "def f(a, b):\n    return a - b\n")):
                (d / name).mkdir(parents=True)
                (d / name / "logic.py").write_text(body, encoding="utf-8")
            r = subprocess.run([str(bin_path), "--delta", str(d / "base"), str(d / "head")],
                               capture_output=True, text=True, timeout=600,
                               env=_isolated_env())
            out = (r.stdout or "") + (r.stderr or "")
            if "DIVERGED" in out:
                print("[OK] R6: `--delta` вшит — расхождение поведения названо из бинаря")
            else:
                print(f"[FAIL] R6: `--delta` rc={r.returncode}, DIVERGED в выводе НЕТ")
                print("      " + " ".join(out.split())[:200])
                bad += 1

            # R9 (#516/T3): `--live` В АВТОНОМНОМ БИНАРЕ НЕДОСТУПЕН, И ЭТО ДОЛЖНО
            # БЫТЬ НАЗВАНО ИМЕННО ТОГДА, КОГДА ЕГО ПОПРОСИЛИ. Проверяем
            # ПОВЕДЕНИЕ: запрос `--live` обязан дать в выводе названное
            # «недоступно/НЕДОСТУПНО», а не молча отработать «как будто»
            # (класс #370: отчёт говорит не то, что произошло).
            r9 = subprocess.run([str(bin_path)] + ["--delta", str(d / "base"), str(d / "head"), "--live"],
                                capture_output=True, text=True, timeout=600,
                                env=_isolated_env())
            out9 = (r9.stdout or "") + (r9.stderr or "")
            # Требуем строку ПРО `--live` (иначе проверка засчиталась бы по общему
            # сообщению об импорте и ничего не доказывала — класс вакуумного теста).
            line9 = next((x.strip() for x in out9.splitlines()
                          if "--live" in x and "недоступн" in x.lower()), "")
            if line9:
                print(f"[OK] R9: `--live` в апплаенсе назван недоступным: {line9[:80]}")
            else:
                print(f"[FAIL] R9: `--live` запрошен, но недоступность НЕ НАЗВАНА "
                      f"ИМЕННО ПРО `--live` (rc={r9.returncode}) — живой слой молча "
                      f"подменён формулами")
                print("      " + " ".join(out9.split())[:200])
                bad += 1

            # R7 (#513): ОТКАЗ ИНСТРУМЕНТА НЕ СМЕЕТ ВЫГЛЯДЕТЬ КАК ЗЕЛЁНЫЙ ГЕЙТ.
            # Замер на ОПУБЛИКОВАННОМ v2.8.2: `kernc` из CI содержал 165
            # инструкций AVX-512 (zmm) → на CPU без AVX-512 SIGILL(132) →
            # `--diff-equiv` печатал `[TOOL_ERROR]`, а `--delta` отвечал
            # «поведение НЕ разошлось» с rc=0. Здесь это воспроизводится
            # детерминированно: подменяем `kernc` заглушкой с кодом 132.
            stub = bin_path.parent / "zig-out" / "bin" / "kernc"
            stub.write_text("#!/bin/sh\nexit 132\n", encoding="utf-8")
            stub.chmod(0o755)
            r2 = subprocess.run([str(bin_path), "--delta", str(d / "base"), str(d / "head")],
                                capture_output=True, text=True, timeout=600,
                                env=_isolated_env())
            out2 = (r2.stdout or "") + (r2.stderr or "")
            silent = r2.returncode == 0 or "НЕ разошлось" in out2
            if silent:
                print(f"[FAIL] R7: сломанный `kernc` дал rc={r2.returncode} и "
                      f"«НЕ разошлось» — ТИХИЙ ЗЕЛЁНЫЙ ГЕЙТ (класс #499)")
                print("      " + " ".join(out2.split())[:200])
                bad += 1
            else:
                line = next((x.strip() for x in out2.splitlines() if "[!]" in x), "нет [!]")
                print(f"[OK] R7: сломанный `kernc` → rc={r2.returncode}, названо: "
                      f"{line[:90]}")

            # R10 (#497 ЗАКРЫТ ДЕЛОМ): `--sarif` ОБЯЗАН создавать валидный SARIF 2.1.0
            # НА ДИСКЕ. Проверяем поведение упакованного бинаря: файл существует,
            # `version == "2.1.0"`, results совпадают с числом новых находок, у каждого
            # есть `ruleId` семейства KERN, `artifactLocation.uri` и `startLine >= 1`.
            stub.unlink(missing_ok=True)          # вернуть рабочий `kernc`
            sarif_out = d / "kern.sarif"
            r10 = subprocess.run([str(bin_path), "--delta", str(d / "base"), str(d / "head"),
                                  "--no-semantic", "--sarif", str(sarif_out), "--json"],
                                 capture_output=True, text=True, timeout=900,
                                 env=_isolated_env())
            probs: list[str] = []
            if not sarif_out.exists():
                probs.append("файл SARIF НЕ создан (обещание без артефакта)")
            else:
                try:
                    doc = json.loads(sarif_out.read_text(encoding="utf-8"))
                except json.JSONDecodeError as e:
                    probs.append(f"SARIF не JSON: {e}")
                    doc = None
                if doc is not None:
                    if doc.get("version") != "2.1.0":
                        probs.append(f"version={doc.get('version')!r} вместо '2.1.0'")
                    runs = doc.get("runs") or []
                    if not runs:
                        probs.append("нет runs[0]")
                    else:
                        res = runs[0].get("results") or []
                        try:
                            want = len(json.loads(r10.stdout or "{}").get("new_findings", []))
                        except json.JSONDecodeError:
                            want = -1
                        if want >= 0 and len(res) != want:
                            probs.append(f"results {len(res)} != новых находок {want}")
                        for r in res:
                            loc = (((r.get("locations") or [{}])[0]).get("physicalLocation") or {})
                            if not (loc.get("artifactLocation") or {}).get("uri"):
                                probs.append("нет artifactLocation.uri")
                            if int((loc.get("region") or {}).get("startLine") or 0) < 1:
                                probs.append("startLine < 1")
                            if not str(r.get("ruleId", "")).startswith("KERN"):
                                probs.append(f"ruleId {r.get('ruleId')!r} не из семейства KERN")
            if probs:
                print(f"[FAIL] R10: SARIF из апплаенса НЕВЕРЕН — {probs[0]} (rc={r10.returncode})")
                bad += 1
            else:
                print(f"[OK] R10: апплаенс пишет валидный SARIF 2.1.0 "
                      f"({sarif_out.stat().st_size} Б, results = новым находкам, startLine >= 1)")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"[{'FAIL' if bad else 'OK'}] #494 kerna: провалов {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
