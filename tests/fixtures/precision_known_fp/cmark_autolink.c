// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
// ФИКСТУРА #495: ЛОЖНОЕ обвинение на реальном коде cmark-gfm (BSD-2-Clause).
// Транскрипция `extensions/autolink.c::autolink_delim` (Copyright (c) 2014, John MacFarlane).
// Ожидание: находок НЕТ — `closing--` защищён `if (closing <= opening) { return link_end; }`.
// ИЗМЕРЕНО: KERN даёт [OVERFLOW PATH] `closing--` при `closing = 0`. Причина гипотезы:
// `link_end` ПЕРЕПРИСВАИВАЕТСЯ внутри `for` (`link_end = i; break;`), после чего гард
// в `switch` перестаёт сужать путь. Минимальные формы БЕЗ переприсваивания НЕ воспроизводят.
int autolink_delim_fixture(uint8_t *data, size_t link_end) {
  size_t i;
  size_t closing = 0;
  size_t opening = 0;

  for (i = 0; i < link_end; ++i) {
    const uint8_t c = data[i];
    if (c == '<') {
      link_end = i;
      break;
    } else if (c == '(') {
      opening++;
    } else if (c == ')') {
      closing++;
    }
  }

  while (link_end > 0) {
    switch (data[link_end - 1]) {
    case ')':
      /* Allow any number of matching brackets (as recognised in copen/cclose)
       * at the end of the URL.  If there is a greater number of closing
       * brackets than opening ones, we remove one character from the end of
       * the link.
       *
       * Examples (input text => output linked portion):
       *
       *        http://www.pokemon.com/Pikachu_(Electric)
       *                => http://www.pokemon.com/Pikachu_(Electric)
       *
       *        http://www.pokemon.com/Pikachu_((Electric)
       *                => http://www.pokemon.com/Pikachu_((Electric)
       *
       *        http://www.pokemon.com/Pikachu_(Electric))
       *                => http://www.pokemon.com/Pikachu_(Electric)
       *
       *        http://www.pokemon.com/Pikachu_((Electric))
       *                => http://www.pokemon.com/Pikachu_((Electric))
       */
      if (closing <= opening) {
        return link_end;
      }
      closing--;
      link_end--;
      break;
    case '?':
    case '!':
    case '.':
    case ',':
    case ':':
    case '*':
    case '_':
    case '~':
    case '\'':
    case '"':
      link_end--;
      break;
    case ';': {
      size_t new_end = link_end - 2;

      while (new_end > 0 && ((c >= 97 && c <= 122) || (c >= 65 && c <= 90))data[new_end]))
        new_end--;

      if (new_end < link_end - 2 && data[new_end] == '&')
        link_end = new_end;
      else
        link_end--;
      break;
    }

    default:
      return link_end;
    }
  }

  return link_end;
}
