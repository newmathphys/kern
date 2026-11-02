// Полигон 3: контракты на массивах (теория QF_AX) — аксиомы Маккарти ROW1/ROW2.
// Пара «правильно/неправильно» на изоляцию слотов кольцевого буфера.
//
// @kern:array buf
// @kern:requires idx >= 0
// @kern:ensures result == val
int array_write_hit(int *buf, int idx, int val) {
    buf[idx] = val;
    return buf[idx];
}

// @kern:array buf
// @kern:requires write_idx != read_idx
// @kern:ensures result == buf[read_idx]
int array_slot_isolation_good(int *buf, int write_idx, int read_idx, int val) {
    buf[write_idx] = val;
    return buf[read_idx];
}

// @kern:array buf
// @kern:requires write_idx >= 0 and read_idx >= 0
// @kern:ensures result == buf[read_idx]
int array_slot_isolation_buggy(int *buf, int write_idx, int read_idx, int val) {
    buf[write_idx] = val;
    return buf[read_idx];
}
