"""Script di build per generare le icone Azzurro Napoli (.ico e .png) e gli eseguibili Windows (.exe).

Genera:
  - `assets/plike.ico` e `assets/plike.png` -> Icone Azzurro SSC Napoli cross-platform
  - `dist/P-Like-Studio.exe`                -> Applicazione Desktop Windows nativa
  - `dist/plike.exe`                        -> Compilatore CLI standalone per terminale Windows
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Tuple

ROOT = Path(__file__).resolve().parent
ASSETS_DIR = ROOT / "assets"
ICON_PATH = ASSETS_DIR / "plike.ico"
PNG_ICON_PATH = ASSETS_DIR / "plike.png"


def generate_icons() -> Tuple[Path, Path]:
    """Genera le icone Azzurro SSC Napoli (`plike.ico` multi-risoluzione e `plike.png` 256x256) usando Pillow."""
    from PIL import Image, ImageDraw, ImageFont

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Cerchio esterno blu profondo + bordo bianco + cerchio azzurro Napoli
    draw.ellipse((8, 8, size - 8, size - 8), fill=(0, 60, 130, 255), outline=(224, 242, 254, 255), width=8)
    draw.ellipse((24, 24, size - 24, size - 24), fill=(18, 160, 215, 255), outline=(255, 255, 255, 235), width=5)

    # Lettera "P" stilizzata al centro (font Windows/Linux o fallback geometrico pulito)
    font = None
    font_candidates = (
        "segoeuib.ttf",
        "arialbd.ttf",
        "calibrib.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "DejaVuSans-Bold.ttf",
    )
    for font_name in font_candidates:
        try:
            font = ImageFont.truetype(font_name, 148)
            break
        except Exception:
            continue

    if font is not None:
        bbox = draw.textbbox((0, 0), "P", font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = (size - tw) / 2 - bbox[0]
        ty = (size - th) / 2 - bbox[1] - 4
        draw.text((tx + 4, ty + 6), "P", fill=(0, 40, 95, 160), font=font)
        draw.text((tx, ty), "P", fill=(255, 255, 255, 255), font=font)
    else:
        draw.rectangle((86, 56, 114, 200), fill=(255, 255, 255, 255))
        draw.pieslice((76, 56, 184, 146), 270, 90, fill=(255, 255, 255, 255))
        draw.ellipse((114, 78, 156, 124), fill=(18, 160, 215, 255))

    img.save(PNG_ICON_PATH, format="PNG")
    img.save(
        ICON_PATH,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Icone generate: {ICON_PATH} e {PNG_ICON_PATH}")
    return ICON_PATH, PNG_ICON_PATH


def generate_icon() -> Path:
    """Compatibilita' retroattiva: genera entrambe le icone e restituisce il percorso .ico."""
    ico, _png = generate_icons()
    return ico


def run_pyinstaller(args: list[str]) -> None:
    cmd = [sys.executable, "-m", "PyInstaller", *args]
    print("Esecuzione:", " ".join(cmd))
    subprocess.run(cmd, cwd=str(ROOT), check=True)


def build_all() -> None:
    icon, _png = generate_icons()
    sep = ";" if sys.platform == "win32" else ":"

    # 1. P-Like-Studio.exe (App Desktop Windows nativa senza console)
    run_pyinstaller(
        [
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name", "P-Like-Studio",
            "--icon", str(icon),
            "--add-data", f"examples{sep}examples",
            "--add-data", f"assets{sep}assets",
            "--add-data", f"plike/ide/static{sep}plike/ide/static",
            "plike_studio_launcher.py",
        ]
    )

    # 2. plike.exe (Compilatore CLI standalone)
    run_pyinstaller(
        [
            "--noconfirm",
            "--clean",
            "--onefile",
            "--console",
            "--name", "plike",
            "--icon", str(icon),
            "--add-data", f"examples{sep}examples",
            "--add-data", f"assets{sep}assets",
            "--add-data", f"plike/ide/static{sep}plike/ide/static",
            "plike_cli_launcher.py",
        ]
    )

    print("\nBuild completata! Eseguibili pronti in:")
    print(f"  - {ROOT / 'dist' / 'P-Like-Studio.exe'}")
    print(f"  - {ROOT / 'dist' / 'plike.exe'}")


if __name__ == "__main__":
    build_all()
