#!/usr/bin/env bash
# Installer universale Linux per il pacchetto portatile P-Like (tutte le distribuzioni).
# Uso:
#   ./install.sh            -> installa per l'utente corrente in ~/.local (nessun sudo richiesto)
#   sudo ./install.sh --system  -> installa a livello di sistema in /usr/local
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SYSTEM_INSTALL=0
for arg in "$@"; do
    case "$arg" in
        --system) SYSTEM_INSTALL=1 ;;
        -h|--help)
            echo "Uso: $0 [--system]"
            echo "  (default)  Installa in ~/.local (senza privilegi di root)"
            echo "  --system   Installa in /usr/local (richiede sudo/root)"
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
        echo "Errore: --system richiede privilegi di root (esegui: sudo $0 --system)." >&2
        exit 1
    fi
    PREFIX="/usr/local"
    DATA_DIR="/usr/local/share"
else
    PREFIX="${HOME}/.local"
    DATA_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}"
fi

BIN_DIR="${PREFIX}/bin"
APP_DIR="${DATA_DIR}/applications"
ICON_DIR="${DATA_DIR}/icons/hicolor/256x256/apps"
MIME_DIR="${DATA_DIR}/mime/packages"
SHARE_PLIKE="${DATA_DIR}/p-like"

echo "==> Installazione di P-Like Studio e plike CLI in ${PREFIX} ..."

mkdir -p "$BIN_DIR" "$APP_DIR" "$ICON_DIR" "$MIME_DIR" "$SHARE_PLIKE"

# 1. Eseguibili standalone
install -m 0755 "${SCRIPT_DIR}/bin/P-Like-Studio" "${BIN_DIR}/P-Like-Studio"
install -m 0755 "${SCRIPT_DIR}/bin/plike" "${BIN_DIR}/plike"
ln -sf "${BIN_DIR}/P-Like-Studio" "${BIN_DIR}/p-like-studio"

# 2. Esempi P-Like
if [ -d "${SCRIPT_DIR}/examples" ]; then
    rm -rf "${SHARE_PLIKE}/examples"
    cp -r "${SCRIPT_DIR}/examples" "${SHARE_PLIKE}/examples"
fi

# 3. Icona, voce di menu (.desktop) e associazione MIME .plike
if [ -f "${SCRIPT_DIR}/share/icons/p-like-studio.png" ]; then
    install -m 0644 "${SCRIPT_DIR}/share/icons/p-like-studio.png" "${ICON_DIR}/p-like-studio.png"
fi

if [ -f "${SCRIPT_DIR}/share/applications/p-like-studio.desktop" ]; then
    sed "s|^Exec=.*|Exec=${BIN_DIR}/P-Like-Studio %F|" \
        "${SCRIPT_DIR}/share/applications/p-like-studio.desktop" \
        > "${APP_DIR}/p-like-studio.desktop"
    chmod 0644 "${APP_DIR}/p-like-studio.desktop"
fi

if [ -f "${SCRIPT_DIR}/share/mime/plike-mime.xml" ]; then
    install -m 0644 "${SCRIPT_DIR}/share/mime/plike-mime.xml" "${MIME_DIR}/plike.xml"
fi

# 4. Aggiorna cache desktop/icone/MIME se disponibili sulla distro
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
command -v update-mime-database >/dev/null 2>&1 && update-mime-database "${DATA_DIR}/mime" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f "${DATA_DIR}/icons/hicolor" >/dev/null 2>&1 || true

echo ""
echo "Installazione completata!"
echo "  - GUI Desktop : ${BIN_DIR}/P-Like-Studio (anche nel menu applicazioni)"
echo "  - CLI         : ${BIN_DIR}/plike"
echo "  - Esempi      : ${SHARE_PLIKE}/examples"

case ":${PATH}:" in
    *":${BIN_DIR}:"*) ;;
    *)
        echo ""
        echo "NOTA: ${BIN_DIR} non e' attualmente nel tuo \$PATH."
        echo "Aggiungi questa riga al tuo ~/.bashrc o ~/.zshrc:"
        echo "  export PATH=\"${BIN_DIR}:\$PATH\""
        ;;
esac
