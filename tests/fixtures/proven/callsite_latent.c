/* Контроль #617, ПРАВИЛО Б: приватный хелпер с литеральными вызовами
   -> нарушение через ЭТИ вызовы недостижимо, находки быть НЕ должно. */
static int rot_helper(int x, int r) {
    return (x << r) | (x >> (32 - r));
}

int use_rot(int v) {
    return rot_helper(v, 3) + rot_helper(v, 7);
}
