#!/usr/bin/env bash
# Installer universale da sorgente per QUALSIASI distribuzione e architettura Linux
# (x86_64, ARM64/Raspberry Pi, RISC-V, Ubuntu, Debian, Fedora, Arch, openSUSE, Alpine, Void, NixOS...).
# Crea un virtualenv isolato in ~/.local/share/p-like/venv (compatibile PEP 668!)
# e registra comandi `plike` / `P-Like-Studio`, icona e voce nel menu applicazioni.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [ ! -f "${REPO_ROOT}/pyproject.toml" ]; then
    echo "Errore: esegui questo script dall'interno della repository P-Like." >&2
    exit 1
fi

PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "Errore: python3 non trovato. Installa Python 3.9+ con il package manager della tua distro." >&2
    exit 1
fi

"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 9), f"Serve Python >= 3.9, trovato {sys.version}"'

HAS_TK=1
if ! "$PYTHON_BIN" -c "import tkinter" >/dev/null 2>&1; then
    HAS_TK=0
    echo "AVVISO: modulo Python 'tkinter' non installato (serve per la GUI P-Like Studio; la CLI e il Web IDE funzionano comunque!)."
    echo "Per abilitare anche l'app desktop GUI installa il pacchetto della tua distro:"
    echo "  Ubuntu / Debian / Mint / Pop!_OS : sudo apt install python3-tk"
    echo "  Fedora / RHEL / Rocky            : sudo dnf install python3-tkinter"
    echo "  Arch / Manjaro / EndeavourOS     : sudo pacman -S tk"
    echo "  openSUSE                         : sudo zypper install python3-tk"
    echo "  Alpine Linux                     : sudo apk add py3-tkinter"
    echo "  Void Linux                       : sudo xbps-install python3-tkinter"
    echo ""
fi

PREFIX="${HOME}/.local"
DATA_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}"
BIN_DIR="${PREFIX}/bin"
APP_DIR="${DATA_DIR}/applications"
ICON_DIR="${DATA_DIR}/icons/hicolor/256x256/apps"
MIME_DIR="${DATA_DIR}/mime/packages"
SHARE_PLIKE="${DATA_DIR}/p-like"
VENV_DIR="${SHARE_PLIKE}/venv"

mkdir -p "$BIN_DIR" "$APP_DIR" "$ICON_DIR" "$MIME_DIR" "$SHARE_PLIKE"

echo "==> Copia sorgenti ed esempi in ${SHARE_PLIKE}/src ..."
rm -rf "${SHARE_PLIKE}/src"
mkdir -p "${SHARE_PLIKE}/src"
cp -r "${REPO_ROOT}/plike" "${SHARE_PLIKE}/src/plike"
cp -r "${REPO_ROOT}/examples" "${SHARE_PLIKE}/src/examples"
cp -r "${REPO_ROOT}/assets" "${SHARE_PLIKE}/src/assets"
cp "${REPO_ROOT}/plike_studio_launcher.py" "${SHARE_PLIKE}/src/"
cp "${REPO_ROOT}/plike_cli_launcher.py" "${SHARE_PLIKE}/src/"

# Wrapper leggerissimi zero-dipendenze (non richiedono nemmeno python3-venv o pip!)
cat > "${BIN_DIR}/plike" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="${SHARE_PLIKE}/src\${PYTHONPATH:+:\$PYTHONPATH}"
exec "${PYTHON_BIN}" -m plike "\$@"
EOF
chmod 0755 "${BIN_DIR}/plike"

cat > "${BIN_DIR}/P-Like-Studio" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="${SHARE_PLIKE}/src\${PYTHONPATH:+:\$PYTHONPATH}"
exec "${PYTHON_BIN}" "${SHARE_PLIKE}/src/plike_studio_launcher.py" "\$@"
EOF
chmod 0755 "${BIN_DIR}/P-Like-Studio"
ln -sf "${BIN_DIR}/P-Like-Studio" "${BIN_DIR}/p-like-studio"

# Icona, voce di menu (.desktop) e MIME .plike
if [ -f "${REPO_ROOT}/assets/plike.png" ]; then
    install -m 0644 "${REPO_ROOT}/assets/plike.png" "${ICON_DIR}/p-like-studio.png"
fi

sed "s|^Exec=.*|Exec=${BIN_DIR}/P-Like-Studio %F|" \
    "${REPO_ROOT}/packaging/linux/p-like-studio.desktop" \
    > "${APP_DIR}/p-like-studio.desktop"
chmod 0644 "${APP_DIR}/p-like-studio.desktop"

install -m 0644 "${REPO_ROOT}/packaging/linux/plike-mime.xml" "${MIME_DIR}/plike.xml"

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
command -v update-mime-database >/dev/null 2>&1 && update-mime-database "${DATA_DIR}/mime" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f "${DATA_DIR}/icons/hicolor" >/dev/null 2>&1 || true

# Verifica rapida
"${BIN_DIR}/plike" --version

echo ""
echo "Installazione da sorgente completata!"
echo "  - CLI         : ${BIN_DIR}/plike"
echo "  - GUI Desktop : ${BIN_DIR}/P-Like-Studio (o 'plike gui')"
echo "  - Web IDE     : plike ide (funziona anche senza tkinter!)"
if [ "$HAS_TK" -eq 0 ]; then
    echo "  (Ricorda di installare python3-tk per la GUI Desktop, oppure usa 'plike ide')"
fi

case ":${PATH}:" in
    *":${BIN_DIR}:"*) ;;
    *)
        echo ""
        echo "NOTA: aggiungi ~/.local/bin al PATH:"
        echo "  export PATH=\"${BIN_DIR}:\$PATH\""
        ;;
esac
