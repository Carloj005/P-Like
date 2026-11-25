#!/usr/bin/env bash
# Disinstaller universale Linux per P-Like Studio e plike CLI.
set -euo pipefail

SYSTEM_INSTALL=0
for arg in "$@"; do
    case "$arg" in
        --system) SYSTEM_INSTALL=1 ;;
        -h|--help)
            echo "Uso: $0 [--system]"
            exit 0
            ;;
        *)
            echo "Opzione sconosciuta: $arg" >&2
            exit 1
            ;;
    esac
done

if [ "$SYSTEM_INSTALL" -eq 1 ]; then
    if [ "${EUID:-$(id -u)}" -ne 0 ]; then
        echo "Errore: --system richiede root (esegui: sudo $0 --system)." >&2
        exit 1
    fi
    PREFIX="/usr/local"
    DATA_DIR="/usr/local/share"
else
    PREFIX="${HOME}/.local"
    DATA_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}"
fi

rm -f "${PREFIX}/bin/P-Like-Studio" "${PREFIX}/bin/p-like-studio" "${PREFIX}/bin/plike"
rm -f "${DATA_DIR}/applications/p-like-studio.desktop"
rm -f "${DATA_DIR}/icons/hicolor/256x256/apps/p-like-studio.png"
rm -f "${DATA_DIR}/mime/packages/plike.xml"
rm -rf "${DATA_DIR}/p-like"

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "${DATA_DIR}/applications" >/dev/null 2>&1 || true
command -v update-mime-database >/dev/null 2>&1 && update-mime-database "${DATA_DIR}/mime" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f "${DATA_DIR}/icons/hicolor" >/dev/null 2>&1 || true

echo "P-Like Studio e plike rimossi da ${PREFIX}."
