/* Контроль #616: приватный помощник с литеральными вызовами -> LATENT;
   публичная функция -> без метки. */
static int rot_helper(int x, int r) {
    return (x << r) | (x >> (32 - r));
}

int use_rot(int v) {
    return rot_helper(v, 3) + rot_helper(v, 7);
}

int public_sub(int k) {
    return k - 1;
}
