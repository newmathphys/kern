/* EXTRACTED from DaveGamble/cJSON, cJSON.c: static unsigned parse_hex4(...)
 * Per-digit logic only: the original loops over 4 chars; the loop is outside
 * the extractor subset, the arithmetic is not. The parameter is `int` because
 * the C extractor accepts `int` (32-bit machine bounds); the original reads
 * `unsigned char`, and the value range checked below is the same.
 * Contract: a hex digit must map into 0..15, otherwise the parsed code point
 * is garbage (the classic parser bug class).
 */

// @kern:requires c >= 48 and c <= 102
// @kern:ensures result >= 0 and result <= 15
int hex_digit(int c) {
    if (c >= 48 && c <= 57) return c - 48;
    if (c >= 65 && c <= 70) return c - 65 + 10;
    if (c >= 97 && c <= 102) return c - 97 + 10;
    return 0;
}

// @kern:requires c >= 48
// @kern:ensures result >= 0 and result <= 15
int hex_digit_unguarded(int c) {
    if (c >= 48 && c <= 57) return c - 48;
    if (c >= 65 && c <= 70) return c - 65 + 10;
    if (c >= 97 && c <= 102) return c - 97 + 10;
    return c - 48;
}
