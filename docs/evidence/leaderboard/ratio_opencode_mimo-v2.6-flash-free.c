// @kern:requires a >= -1000 and a <= 1000
// @kern:ensures result == a / b
int ratio(int a, int b)
{
    int negative = 0;
    int q = 0;

    if (a < 0) {
        a = -a;
        negative = !negative;
    }
    if (b < 0) {
        b = -b;
        negative = !negative;
    }

    while (a >= b) {
        a -= b;
        q++;
    }

    return negative ? -q : q;
}
