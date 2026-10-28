/* ДЕФЕКТ #401: ВЗАИМОИСКЛЮЧАЮЩИЕ ветви с ранними `return`.
   До правки накопление `not cond` давало ОДНОВРЕМЕННО `str1 >= 160`
   (из ветви `if (A)`) и `str1 < 160` (из ветви `else if (C)`): путь становился
   UNSAT, и ЛЮБОЕ последующее условие объявлялось мёртвым. ИЗМЕРЕНО на
   `cmark-gfm/src/utf8.c` (коммит 27d942c8): 4 ЛОЖНЫХ [DEAD BRANCH]. */
int nested_branches(const unsigned char *str, int str_len) {
  int length = 3;
  switch (length) {
  case 3:
    if (str[0] == 0xE0) {
      if (str[1] < 0xA0) {
        return -3;
      }
    } else if (str[0] == 0xED) {
      if (str[1] >= 0xA0) {
        return -3;
      }
    }
    break;
  case 4:
    if (str[0] == 0xF0) {
      if (str[1] < 0x90) {
        return -4;
      }
    } else if (str[0] >= 0xF4) {
      if (str[0] > 0xF4 || str[1] >= 0x90) {
        return -4;
      }
    }
    break;
  }
  return length;
}
