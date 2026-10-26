/* CWE-191 Integer Underflow (NIST Juliet-style `bad` twin).
 * Настоящий дефект: беззнаковое `a - b` при `b > a` оборачивается в огромное
 * число, поэтому постусловие `result > 0` нарушается. */
// @kern:requires a > 0 and b > 0
// @kern:ensures result > 0
unsigned int sub_bad(unsigned int a, unsigned int b) {
    return a - b;
}
