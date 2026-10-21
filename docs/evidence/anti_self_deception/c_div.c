#include <stdio.h>
int ratio(int a, int b) { return a / b; }
int main(void) {
    printf("NO VIOLATION %d\n", ratio(1, 0));
    return 0;
}
