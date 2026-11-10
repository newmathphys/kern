#include <stdint.h>
#include <stdio.h>
static uint64_t XXH_rotl64(uint64_t x, int r) {
    return (x << r) | (x >> (64 - r));
}
int main(void) {
    printf("rotl64(x,0) = 0\n", (unsigned long long)XXH_rotl64(42, 0));
    return 0;
}
