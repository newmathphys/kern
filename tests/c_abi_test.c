/* Copyright (c) 2026 Vital Kalinousky. All rights reserved.
 * Licensed under the PolyForm Noncommercial License 1.0.0.
 * Commercial use requires a license from the copyright holder. See LICENSE.
 *
 * ===========================================================================
 *  KERN: ХАРДКОР-АУДИТ C-ABI (чистый C, строгие флаги).
 *
 *  ЗАЧЕМ. `libkern.so` — публичный интерфейс для C/C++/Rust/Go. Вызывающий
 *  на C МОЖЕТ передать NULL там, где тип Zig `[*]const u8` этого не допускает.
 *  Без проверок `img[0]` по NULL даёт SIGSEGV — то есть отказ в обслуживании
 *  из чужого процесса. Этот тест проверяет КАЖДУЮ из 8 функций на:
 *    1. NULL-указатель при len > 0;
 *    2. нулевую длину;
 *    3. корректный возврат кода ошибки (а не краш).
 *
 *  Сборка (строгая):
 *    zig cc -Wall -Wextra -Werror -pedantic -std=c11 -Iinclude \
 *            tests/c_abi_test.c -Lzig-out/lib -lkern -o /tmp/cabi && /tmp/cabi
 * ===========================================================================
 */
#include <kern.h>
#include <stdio.h>
#include <string.h>

static int failures = 0;

static void ok(const char *what, int cond) {
    printf("  %s %s\n", cond ? "[OK]  " : "[FAIL]", what);
    if (!cond) failures++;
}

/* Ожидаем, что вызов НЕ падает и возвращает код ошибки, а не мусор. */
static void check_null_safety(void) {
    unsigned char out[64];
    unsigned char img[256];
    memset(img, 0, sizeof img);

    printf("\n[1] NULL-указатели при len > 0 (не должно быть SIGSEGV)\n");
    ok("kern_hash(NULL data, len=16) -> -1",
       kern_hash(1u, NULL, 16u, out) == -1);
    ok("kern_hash(NULL out32) -> -1",
       kern_hash(1u, (const unsigned char *)"x", 1u, NULL) == -1);
    ok("kern_smt_verify(NULL, len=8) -> -1",
       kern_smt_verify(NULL, 8u) == -1);
    ok("kern_kimg_valid(NULL, len=200) -> 0",
       kern_kimg_valid(NULL, 200u) == 0);
    ok("kern_kimg_object_count(NULL, len=200) -> -1",
       kern_kimg_object_count(NULL, 200u) == -1);
    ok("kern_localize(NULL decls) -> -1",
       kern_localize(NULL, 4u, (const unsigned char *)"(>= x 0)", 8u,
                     (const unsigned char *)"(<= x 0)", 8u, out, sizeof out) == -1);
    ok("kern_localize(NULL out_buf) -> -1",
       kern_localize((const unsigned char *)"(declare-const x Int)", 22u,
                     (const unsigned char *)"(>= x 0)", 8u,
                     (const unsigned char *)"(<= x 0)", 8u, NULL, 64u) == -1);

    printf("\n[2] Нулевая длина (не должно быть чтения по указателю)\n");
    ok("kern_smt_verify(x, 0) -> -1", kern_smt_verify((const unsigned char *)"x", 0u) == -1);
    ok("kern_kimg_valid(img, 0) -> 0", kern_kimg_valid(img, 0u) == 0);
    ok("kern_kimg_valid(img, 127) -> 0", kern_kimg_valid(img, 127u) == 0);
    ok("kern_kimg_object_count(img, 127) -> -1",
       kern_kimg_object_count(img, 127u) == -1);
    ok("kern_localize(decls_len=0) -> -1",
       kern_localize((const unsigned char *)"", 0u, (const unsigned char *)"p", 1u,
                     (const unsigned char *)"g", 1u, out, sizeof out) == -1);
    ok("kern_hash(len=0) -> 0 (пустой вход допустим)",
       kern_hash(1u, (const unsigned char *)"", 0u, out) == 0);
}

/* Штатные вызовы: интерфейс обязан работать, а не только отвергать мусор. */
static void check_normal_paths(void) {
    unsigned char d1[32], d2[32];
    const unsigned char *msg = (const unsigned char *)"KERN";

    printf("\n[3] Штатные вызовы\n");
    ok("kern_hash(BLAKE3) == 0", kern_hash(1u, msg, 4u, d1) == 0);
    ok("kern_hash(SHA-256) == 0", kern_hash(2u, msg, 4u, d2) == 0);
    ok("алгоритмы дают РАЗНЫЕ хэши", memcmp(d1, d2, 32) != 0);
    ok("неизвестный algo -> -1", kern_hash(99u, msg, 4u, d1) == -1);

    ok("kern_version() не NULL", kern_version() != NULL);
    ok("kern_author() не NULL", kern_author() != NULL);
    ok("kern_ownership_ok() == 1", kern_ownership_ok() == 1);
}

int main(void) {
    printf("=====================================================================\n");
    printf("KERN C-ABI: хардкор-аудит (чистый C, -Wall -Wextra -Werror -pedantic)\n");
    printf("=====================================================================\n");
    check_null_safety();
    check_normal_paths();
    printf("---------------------------------------------------------------------\n");
    if (failures) {
        printf("ПРОВАЛОВ: %d\n", failures);
        return 1;
    }
    printf("ВСЁ ПРОЙДЕНО: NULL-указатели и нулевые длины отвергаются БЕЗ краха\n");
    return 0;
}
