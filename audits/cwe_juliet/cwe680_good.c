/* CWE-680 `good` twin: размер вычисляется с гардом, гарантирующим отсутствие
 * переполнения (46340 * 46340 < INT_MAX). */
// @kern:requires n > 0 and size > 0 and n <= 46340 and size <= 46340
// @kern:ensures result > 0
int buffer_size(int n, int size) {
    return n * size;
}
