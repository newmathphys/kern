/* ПРАВИЛО (KERN.md):  0 <= low <= high <= 2000000000  ->  low <= result <= high */
int midpoint(int low, int high) {
    return (low + high) / 2;
}
