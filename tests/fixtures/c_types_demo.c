/*
 * KERN fixture for defect #312 — C machine types.
 *
 * The extractor used to require exactly ONE word before the parameter name, so
 * `unsigned int c` was skipped while `size_t a` worked. Every integer type below
 * must receive a verdict; `float` and `char` must be skipped WITH a reason
 * (`char` because its signedness is implementation-defined).
 */
// @kern:requires a >= 0 and b >= 0
// @kern:ensures result >= a
unsigned int u32_add(unsigned int a, unsigned int b)
{
    return a + b; /* wraps around 2^32 - 1: must be REFUTED */
}

// @kern:requires c >= 0 and c <= 255
// @kern:ensures result <= 15
unsigned int nibble(unsigned int c)
{
    return c & 15; /* bit-vector theory: must be PROVEN */
}

// @kern:requires x >= 0 and x <= 1000000
// @kern:ensures result >= x
long long widen(long long x)
{
    return x + 1; /* multi-word type: must be PROVEN (i64 range applied) */
}

// @kern:requires n >= 0 and n <= 255
// @kern:ensures result >= 0
unsigned char byte_id(unsigned char n)
{
    return n; /* must be PROVEN */
}

// @kern:requires v >= 0
// @kern:ensures result >= 0
float unsupported_float(float v)
{
    return v; /* must be SKIP with a reason */
}

// @kern:requires c >= 0
// @kern:ensures result >= 0
char unsupported_char(char c)
{
    return c; /* must be SKIP with a reason: signedness is implementation-defined */
}
