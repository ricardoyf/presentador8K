#!/bin/sh
set -eu

APP_DIR="$HOME/.local/share/presentador-fotos"
BIN_DIR="$HOME/.local/bin"
APPLICATIONS_DIR="$HOME/.local/share/applications"
DESKTOP_DIR="$HOME/Desktop"
SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

mkdir -p "$APP_DIR" "$BIN_DIR" "$APPLICATIONS_DIR" "$DESKTOP_DIR"
install -m 755 "$SOURCE_DIR/presentador_fotos.py" "$APP_DIR/presentador_fotos.py"

sed "s|@APP_DIR@|$APP_DIR|g" "$SOURCE_DIR/presentador-fotos" > "$BIN_DIR/presentador-fotos"
chmod 755 "$BIN_DIR/presentador-fotos"

sed "s|@BIN_DIR@|$BIN_DIR|g" "$SOURCE_DIR/presentador-fotos.desktop" > "$APPLICATIONS_DIR/presentador-fotos.desktop"
cp "$APPLICATIONS_DIR/presentador-fotos.desktop" "$DESKTOP_DIR/Presentador Fotos NAS.desktop"
chmod 755 "$APPLICATIONS_DIR/presentador-fotos.desktop" "$DESKTOP_DIR/Presentador Fotos NAS.desktop"
gio set "$DESKTOP_DIR/Presentador Fotos NAS.desktop" metadata::trusted true 2>/dev/null || true
update-desktop-database "$APPLICATIONS_DIR" 2>/dev/null || true

printf '%s\n' "Instalado PresentadorFotos NAS. Acceso directo: $DESKTOP_DIR/Presentador Fotos NAS.desktop"

