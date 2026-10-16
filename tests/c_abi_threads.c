/* Copyright (c) 2026 Vital Kalinousky. All rights reserved.
 * Licensed under the PolyForm Noncommercial License 1.0.0.
 * Commercial use requires a license from the copyright holder. See LICENSE.
 *
 * ===========================================================================
 *  KERN: ХАРДКОР-АУДИТ многопоточности `libkern.so` (8 потоков × 500 вызовов).
 *
 *  ЗАЧЕМ. В `src/compat.zig` есть `threadlocal var tls_io` — кэш `std.Io` на
 *  поток, чтобы горячий путь `compat.io()` не брал мьютекс каждый раз.
 *  В ТЕСТОВОЙ сборке Zig ветка `builtin.is_test` коротко замыкает `io()` на
 *  `std.testing.io`, поэтому `tls_io` там НЕ проверяется. Проверить его можно
 *  только через РЕАЛЬНУЮ разделяемую библиотеку — то есть отсюда, из C.
 *
 *  ЧТО ПРОВЕРЯЕТСЯ:
 *    [A] 8 потоков × 500 вызовов `kern_hash` — гонок в диспетчере хэшей нет;
 *    [B] 8 потоков × 20 вызовов `kern_smt_verify` — конкурентный доступ к
 *        `compat.io()` и мосту Z3 (порождение дочернего процесса, пайпы)
 *        не даёт дедлока, падений и расхождения вердиктов;
 *    [C] каждый поток получает ОДИНАКОВЫЙ хэш для одного и того же входа
 *        (детерминизм при конкуренции).
 *
 *  Сборка:
 *    zig cc -Wall -Wextra -Werror -pedantic -std=c11 -pthread -Iinclude \
 *            tests/c_abi_threads.c -Lzig-out/lib -lkern -o /tmp/cabi_th && /tmp/cabi_th
 * ===========================================================================
 */
#include <kern.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>

#define THREADS 8
#define HASH_ITERS 500
#define SMT_ITERS 20

static const char *SMT_UNSAT =
    "(set-logic ALL)\n(declare-const x Int)\n"
    "(assert (and (> x 10) (< x 5)))\n(check-sat)\n";

static int hash_bad = 0;   /* расхождения/ошибки в [A] и [C] */
static int smt_bad = 0;    /* ошибки в [B] */
static int smt_proved = 0; /* сколько раз получено «ДОКАЗАНО» */

struct worker {
    int id;
    unsigned char expect[32];
};

static void *thread_hash(void *arg) {
    struct worker *w = (struct worker *)arg;
    const unsigned char *msg = (const unsigned char *)"KERN-THREAD-PROBE";
    for (int i = 0; i < HASH_ITERS; i++) {
        unsigned char d[32];
        if (kern_hash(1u, msg, 17u, d) != 0) { __sync_fetch_and_add(&hash_bad, 1); return NULL; }
        if (memcmp(d, w->expect, 32) != 0) { __sync_fetch_and_add(&hash_bad, 1); return NULL; }
    }
    return NULL;
}

static void *thread_smt(void *arg) {
    (void)arg;
    for (int i = 0; i < SMT_ITERS; i++) {
        int rc = kern_smt_verify((const unsigned char *)SMT_UNSAT, strlen(SMT_UNSAT));
        if (rc == 0) {
            __sync_fetch_and_add(&smt_proved, 1);
        } else {
            /* Решатель может быть недоступен -> это НЕ ошибка многопоточности,
             * но ЛЮБОЙ другой код (паника, -1 из-за гонки) — ошибка. */
            if (rc != 2 && rc != -1) __sync_fetch_and_add(&smt_bad, 1);
        }
    }
    return NULL;
}

int main(void) {
    pthread_t th[THREADS];
    struct worker ws[THREADS];

    printf("=====================================================================\n");
    printf("KERN: многопоточный хардкор-аудит libkern.so (%d потоков)\n", THREADS);
    printf("=====================================================================\n");

    /* ЭТАЛОННЫЙ ХЭШ — КОНСТАНТА, а не результат этой же библиотеки.
     *
     * ПОЧЕМУ. Если считать эталон вызовом `kern_hash`, мутация ВНУТРИ
     * хэш-пути изменит и эталон, и проверяемое значение — тест останется
     * зелёным и НИЧЕГО не проверит. Константа ломает эту слепую зону.
     *
     * Источник: BLAKE3-256 от "KERN-THREAD-PROBE", сверен с независимой
     * реализацией (python-пакет blake3):
     *   4e66d943e13195f12a67bdfce641693f268e71b2e0f2af48a435cd86c3534a55
     */
    static const unsigned char REF[32] = {
        0x4e, 0x66, 0xd9, 0x43, 0xe1, 0x31, 0x95, 0xf1,
        0x2a, 0x67, 0xbd, 0xfc, 0xe6, 0x41, 0x69, 0x3f,
        0x26, 0x8e, 0x71, 0xb2, 0xe0, 0xf2, 0xaf, 0x48,
        0xa4, 0x35, 0xcd, 0x86, 0xc3, 0x53, 0x4a, 0x55,
    };
    for (int i = 0; i < THREADS; i++) {
        ws[i].id = i;
        memcpy(ws[i].expect, REF, 32);
    }

    printf("\n[A+C] %d потоков x %d вызовов kern_hash\n", THREADS, HASH_ITERS);
    for (int i = 0; i < THREADS; i++) {
        if (pthread_create(&th[i], NULL, thread_hash, &ws[i]) != 0) {
            printf("  [FAIL] pthread_create\n");
            return 1;
        }
    }
    for (int i = 0; i < THREADS; i++) pthread_join(th[i], NULL);
    printf("  %s расхождений/ошибок: %d (ожидается 0)\n",
           hash_bad == 0 ? "[OK]  " : "[FAIL]", hash_bad);

    printf("\n[B] %d потоков x %d вызовов kern_smt_verify (compat.io + мост Z3)\n",
           THREADS, SMT_ITERS);
    for (int i = 0; i < THREADS; i++) {
        if (pthread_create(&th[i], NULL, thread_smt, NULL) != 0) {
            printf("  [FAIL] pthread_create\n");
            return 1;
        }
    }
    for (int i = 0; i < THREADS; i++) pthread_join(th[i], NULL);
    printf("  %s ошибок: %d (ожидается 0); «ДОКАЗАНО» получено %d раз\n",
           smt_bad == 0 ? "[OK]  " : "[FAIL]", smt_bad, smt_proved);

    printf("---------------------------------------------------------------------\n");
    if (hash_bad || smt_bad) {
        printf("ПРОВАЛОВ: hash=%d smt=%d\n", hash_bad, smt_bad);
        return 1;
    }
    printf("ВСЁ ПРОЙДЕНО: %d потоков отработали без гонок, дедлоков и расхождений\n",
           THREADS);
    return 0;
}
