#include <stdio.h>
#include <limits.h>
#include "bs_fn.c"
int main(void) {
    int a[5] = {1,2,3,4,5};
    printf("r=%d\n", binarysearch1(a, INT_MIN, INT_MAX, 3));
    return 0;
}
