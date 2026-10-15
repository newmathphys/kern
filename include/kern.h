/* Copyright (c) 2026 Vital Kalinousky. All rights reserved.
 * Use of this source code is governed by the GNU Affero General Public License v3.0 ONLY
 * (AGPL-3.0-only), or a commercial license from the copyright holder. See LICENSE.
 *
 * KERN C-ABI — встраивание ядра проверки истины в чужие системы.
 *
 * Сборка:  zig build lib
 * Линковка: cc app.c -Iinclude -Lzig-out/lib -lkern
 *
 * Все строки — НЕ zero-terminated, если явно не указано иное: длина передаётся
 * отдельно. Буферы принадлежат вызывающей стороне.
 */
#ifndef KERN_H
#define KERN_H

#ifdef __cplusplus
extern "C" {
#endif

/* Коды вердикта. */
#define KERN_PROVED      0   /* доказано (unsat: контрпримеров нет) */
#define KERN_REFUTED     1   /* опровергнуто (sat: найден контрпример) */
#define KERN_UNKNOWN     2   /* таймаут / решатель не определился */
#define KERN_TOOL_ERROR (-1) /* решатель недоступен / ошибка инструмента */

/* Версия ядра (zero-terminated). */
const char *kern_version(void);

/* Автор ядра (zero-terminated). */
const char *kern_author(void);

/* Проверка «ключа-замка» авторства: 1 = валиден, 0 = нет. */
int kern_ownership_ok(void);

/* Хеш данных тем же алгоритмом, что и ядро (спецификация §5.3).
 * algo = 1 (BLAKE3-256) или 2 (SHA2-256); data/len — вход (не zero-terminated);
 * out32 — буфер вызывающего ровно на 32 байта. 0 = успех, -1 = неизвестный algo. */
int kern_hash(unsigned int algo, const unsigned char *data, unsigned long len,
              unsigned char *out32);

/* Проверка SMT-LIB2 контракта через реальный Z3.
 * smt/len — скрипт SMT-LIB2 (может содержать несколько команд).
 * Возвращает KERN_PROVED / KERN_REFUTED / KERN_UNKNOWN / KERN_TOOL_ERROR. */
int kern_smt_verify(const unsigned char *smt, unsigned long len);

/* Проверка целостности образа .kimg (заголовок + Merkle-корень).
 * Память НЕ выделяется (zero-copy). 1 = валиден, 0 = нет. */
int kern_kimg_valid(const unsigned char *img, unsigned long len);

/* Число объектов в образе (-1 при ошибке разбора). */
long kern_kimg_object_count(const unsigned char *img, unsigned long len);

/* Доказательство с локализацией виновника (UNSAT core).
 *
 * 🔴 ИСПРАВЛЕНО: раньше была ОДНА строка, которая одновременно служила и
 * объявлениями, и предусловием — из-за чего корректный вызов был невозможен
 * (SMT-скрипт содержал `(declare-const x Int)` как утверждение и не содержал
 * объявления `x`). Теперь параметры разделены:
 *
 * decls/decls_len     — ТОЛЬКО объявления, напр. "(declare-const x Int)";
 * pre/pre_len         — предусловие (именуется `pre` в UNSAT-ядре);
 * goal/goal_len       — целевое утверждение (именуется `goal`);
 * out_buf/out_buf_len — имена виновных утверждений через пробел (zero-terminated).
 *
 * Возвращает: 0 = ДОКАЗАНО (pre ∧ ¬goal невыполнимо), 1 = КОНТРПРИМЕР,
 *             2 = неизвестно, -1 = решатель недоступен. */
int kern_localize(const unsigned char *decls, unsigned long decls_len,
                  const unsigned char *pre, unsigned long pre_len,
                  const unsigned char *goal, unsigned long goal_len,
                  char *out_buf, unsigned long out_buf_len);

#ifdef __cplusplus
}
#endif
#endif /* KERN_H */
