/* Контроль #617: КЛАССИЧЕСКИЙ баг (l+r)/2 обязан ЛОВИТЬСЯ даже с индексным доменом */
int binsearch_classic_bug(const int *arr, int l, int r, int x) {
    while (l <= r) {
        int mid = (l + r) / 2;
        if (arr[mid] == x) return mid;
        if (arr[mid] < x) l = mid + 1;
        else r = mid - 1;
    }
    return -1;
}
