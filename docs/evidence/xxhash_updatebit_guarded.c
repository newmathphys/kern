#include <stddef.h>
static void flipbit(void* buf, size_t idx);
static int updateBit(void* buffer, size_t* bitIdx, int level, size_t max)
{
    if (level<=0) return 0;
    flipbit(buffer, bitIdx[level]);
    if (bitIdx[level] < max-1) {
        bitIdx[level]++;
        flipbit(buffer, bitIdx[level]);
        return 1;
    }
    if (!updateBit(buffer, bitIdx, level-1, max-1)) return 0;
    bitIdx[level] = bitIdx[level-1] + 1;
    flipbit(buffer, bitIdx[level]);
    return 1;
}
