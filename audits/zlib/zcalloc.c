/* ТЕНЬ-КОНТРАКТ на РЕАЛЬНУЮ функцию из zlib (madler/zlib):
 *   zutil.c, zcalloc (ветка без MY_ZCALLOC):
 *     voidpf ZLIB_INTERNAL zcalloc(voidpf opaque, unsigned items, unsigned size) {
 *         (void)opaque;
 *         return sizeof(uInt) > 2 ? (voidpf)malloc(items * size) :
 *                                   (voidpf)calloc(items, size);
 *     }
 *
 * ЗАЧЕМ: `items * size` в 32-битном `unsigned` — классический класс
 * «Integer Overflow -> Heap Overflow» (в zlib это CVE-2002-0059): размер
 * выделяется МЕНЬШЕ заказанного. Свойство «размер делится обратно» ломается
 * ровно тогда, когда произведение выходит за тип.
 *
 * ТЕОРИЯ: QF_BV (`(_ BitVec 32)`), потому что умножение ДВУХ переменных
 * нелинейно в арифметике Int (улучшение №16 — экстрактор теперь переключает
 * такие функции в BV вместо SKIP).
 */

/* @kern:bitvec32 */
/// @kern:requires items > 0 and size > 0
/// @kern:ensures  result / items == size
unsigned zcallocSize(unsigned items, unsigned size) {
    return items * size;
}

/* КОНТРОЛЬ: произведение ОГРАНИЧЕНО типом — переполнения нет, свойство держится. */
/// @kern:requires items > 0 and items <= 1000 and size > 0 and size <= 1000
/// @kern:ensures  result / items == size
unsigned zcallocSizeBounded(unsigned items, unsigned size) {
    return items * size;
}
