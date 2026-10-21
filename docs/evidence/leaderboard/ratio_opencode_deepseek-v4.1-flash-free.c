// @kern:requires a >= -1000 and a <= 1000 and b > 0
// @kern:ensures result == a / b

int ratio(int a, int b)
{
    if (b == 0)
        return 0;
    return a / b;
}
