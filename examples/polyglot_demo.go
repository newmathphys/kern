// Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
// ЭШЕЛОН 5, ПУНКТ 25: Go. Условия пишутся БЕЗ круглых скобок (`if x < 0 {`),
// а `;` необязательна — обе формы поддержаны.
// Ожидания приёмки: clampGo -> PROVEN, badGo -> REFUTED.

package demo

// @kern:requires x >= 0
// @kern:ensures result >= 0
func clampGo(x int32) int32 {
	if x < 0 {
		return 0
	}
	return x
}

// @kern:ensures result >= 0
func badGo(x int32) int32 {
	return x - 1
}
