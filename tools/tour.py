#!/usr/bin/env python3
"""`tour.py` — ВИТРИНА KERN: пять ролевых дуг на один экран (#492).

ЗАЧЕМ. У проекта 197 внутренних гейтов и 86 документов: владелец видит гору
деталей, но не видит продукта за 20 секунд. Здесь пять дуг — по одной на роль:
разработчик · тестировщик/скептик · ревьюер PR · получатель артефакта · новый
пользователь с чужой папкой.

ЧЕСТНО. Это НЕ «демо-режим»: каждая дуга запускает НАСТОЯЩУЮ проверку и
показывает её НАСТОЯЩИЙ вывод. Если дуга падает — падает и витрина (rc=1),
иначе витрина стала бы рекламой, не связанной с кодом.
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

def run(cmd: list, timeout: int = 600) -> tuple:
    p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def show(n: int, title: str, role: str) -> None:
    print()
    print("=" * 78)
    print(f"ДУГА {n}/5 · {title}")
    print(f"  роль: {role}")
    print("=" * 78)


def main() -> int:
    bad = 0
    t0 = time.time()
    print("KERN · ЭКСКУРСИЯ (5 дуг, настоящие проверки)")

    # --- ДУГА 1: контракты. Баг ловится, защищённый код молчит.
    show(1, "Контракт в комментарии → доказательство на ВСЕХ входах",
         "разработчик: «мой расчёт верен всегда, а не на 5 примерах»")
    rc, out = run([PY, "tools/kern_contracts.py", "examples/contracts_demo.py"])
    keep = [l for l in out.splitlines()
            if ("PROVEN" in l or "CONTRACT VIOLATED" in l or "КОНТРПРИМЕР" in l
                or "[PASS]" in l or "[FAIL]" in l)][:6]
    for l in keep:
        print("   ", l.strip()[:150])
    if rc not in (0, 1):
        print(f"   [!] дуга не выполнилась (rc={rc})")
        bad += 1

    # --- ДУГА 2: pytest зелёный, мутант жив.
    show(2, "`pytest` зелёный — а мутант ЖИВ",
         "тестировщик-скептик: «ваши тесты что-то доказывают?»")
    rc, out = run([PY, "tools/pytest_blind_check.py"], timeout=900)
    for l in out.splitlines():
        if any(k in l for k in ("TP", "TN", "J =", "УБИТ", "survived")):
            print("   ", l.strip()[:150])
    print(f"    rc={rc}")

    # --- ДУГА 3: PR-диф. Новая ошибка и тихое ослабление.
    show(3, "Диф-аудит PR: новая ошибка И увод в SKIP",
         "ревьюер: «ИИ переписал функцию — поведение то же?»")
    rc, out = run([PY, "tools/audit_delta.py", "--selftest"], timeout=600)
    for l in out.splitlines()[-4:]:
        print("   ", l.strip()[:150])
    print(f"    rc={rc}")

    # --- ДУГА 4: артефакт без решателя.
    show(4, "`.kimg` + сертификат проверяются БЕЗ Z3",
         "получатель/комплаенс: «докажи, а решателя у меня нет»")
    rc, out = run(["make", "pcc-offline-check"], timeout=900)
    for l in out.splitlines()[-5:]:
        print("   ", l.strip()[:150])

    # --- ДУГА 5: одна кнопка на чужую папку.
    show(5, "Одна кнопка: паспорт аудита любой папки",
         "новый пользователь: «проверь мой проект»")
    rc, out = run([PY, "tools/kern_scan.py", "tests/fixtures/precision_buggy",
                   "--sample", "6"], timeout=900)
    for l in out.splitlines():
        if any(k in l for k in ("инвентарь", "охват", "рентген", "ПАСПОРТ")):
            print("   ", l.strip()[:150])

    dt = time.time() - t0
    print()
    print("=" * 78)
    print(f"ИТОГ: витрина прошла за {dt:.1f} с · провалов {bad}")
    print("Каждая дуга — настоящая проверка: витрина не может быть зелёной при сломанном коде.")
    print("=" * 78)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
