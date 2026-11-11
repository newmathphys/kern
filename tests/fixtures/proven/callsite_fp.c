/* Контроль #617, ПРАВИЛО А: эталонная формула l + (r - l)/2 в бинарном поиске
   НЕ должна обвиняться: l и r — индексы массива, домен 0 <= l <= r. */
int binsearch_safe(const int *arr, int l, int r, int x) {
    while (l <= r) {
        int mid = l + (r - l) / 2;
        if (arr[mid] == x) return mid;
        if (arr[mid] < x) l = mid + 1;
        else r = mid - 1;
    }
    return -1;
}
