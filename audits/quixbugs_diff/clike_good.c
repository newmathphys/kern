/* C-like ИСПРАВЛЕННЫЙ вариант: кламп возвращает САМУ границу. */
int clamp_hi(int v, int hi) {
    if (v > hi) return hi;
    return v;
}
