#include <stdio.h>
#include <stdlib.h>
#include "ps_fn.c"
int main(void) {
    int *p = malloc(1000000 * sizeof(int));
    prime(p);
    printf("prime ok\n");
    int *a = malloc(10 * sizeof(int));
    for (int i = 0; i < 10; i++) a[i] = 0;
    printf("count=%d\n", count(a, 10));
    return 0;
}
