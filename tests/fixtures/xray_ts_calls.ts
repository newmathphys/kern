// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.
//
// Корпус-контроль для дефекта #410 (такт 2.2): `await x(...)` и
// `throw new Error(...)` — это ВЫЗОВЫ, а не определения функций.
//
// Форма взята ИЗ РЕАЛЬНОГО КОРПУСА (`actions/toolkit/packages/io/src/io-util.ts`,
// строки 50 и 77): вызов стоит на своей строке, а фигурная скобка `{` ближайшего
// блока идёт СЛЕДУЮЩЕЙ строкой. ИЗМЕРЕНО до правки: запасная C-регулярка
// `ТИП ИМЯ(...)` + `\s*{` перепрыгивала перевод строки, считала вызов функцией,
// тело «функции» нарезалось из середины файла и печаталась ЛОЖНАЯ мёртвая ветвь.
// После правки: ровно ОДНА функция и НОЛЬ находок.

export async function fetchPath(p: string): Promise<string> {
  try {
    await readFile(p)
  } catch (err) {
    if (!p) {
      throw new Error('empty path')
    }
    return ''
  }
  return p
}
