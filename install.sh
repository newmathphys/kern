#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
# Однострочная установка/проверка KERN.
#   ./install.sh --check   — проверить локальный бинарник (размер, sha256, запуск)
#   ./install.sh           — скопировать в ~/.local/bin и проверить
set -eu
ROOT="$(cd "$(dirname "$0")" && pwd)"
BIN="$ROOT/zig-out/bin/kernc-hermetic"
[ -x "$BIN" ] || BIN="$ROOT/zig-out/bin/kernc"
SHA="$ROOT/SHA256SUMS"
case "${1:-}" in
  --check)
    [ -x "$BIN" ] || { echo "[!] бинарник не найден: $BIN (соберите: zig build)"; exit 1; }
    SIZE=$(stat -c%s "$BIN")
    H=$(sha256sum "$BIN" | cut -d' ' -f1)
    echo "[i] бинарник: $BIN"
    echo "[i] размер:   $SIZE байт"
    echo "[i] sha256:   $H"
    if [ -f "$SHA" ] && grep -q "$H" "$SHA"; then echo "[OK] sha256 совпадает с SHA256SUMS"; else echo "[i] SHA256SUMS не содержит этот хеш (пересоберите релиз)"; fi
    "$BIN" --help > /dev/null 2>&1 || { echo "[!] бинарник НЕ запускается"; exit 1; }
    echo "[OK] бинарник запускается"
    ;;
  *)
    [ -x "$BIN" ] || { echo "[!] бинарник не найден (соберите: zig build)"; exit 1; }
    mkdir -p "$HOME/.local/bin"
    install -m 0755 "$BIN" "$HOME/.local/bin/kernc"
    echo "[OK] установлено: $HOME/.local/bin/kernc"
    echo "[i] добавьте в PATH: export PATH=\"$HOME/.local/bin:$PATH\""
    ;;
esac
