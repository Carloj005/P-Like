"""Script di build per generare l'icona Azzurro Napoli (.ico) e gli eseguibili Windows (.exe).

Genera in `dist/`:
  - `P-Like-Studio.exe`  -> Applicazione Desktop Windows nativa (senza console, con icona SSC Napoli P-Like!)
  - `plike.exe`          -> Compilatore CLI standalone per terminale Windows
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSETS_DIR = ROOT / "assets"
ICON_PATH = ASSETS_DIR / "plike.ico"


def generate_icon() -> Path:
    """Genera un'icona multi-risoluzione Azzurro SSC Napoli con emblema 'P' usando Pillow."""
    from PIL import Image, ImageDraw, ImageFont

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Cerchio esterno blu profondo + bordo bianco + cerchio azzurro Napoli
    draw.ellipse((8, 8, size - 8, size - 8), fill=(0, 60, 130, 255), outline=(224, 242, 254, 255), width=8)
    draw.ellipse((24, 24, size - 24, size - 24), fill=(18, 160, 215, 255), outline=(255, 255, 255, 235), width=5)

    # Lettera "P" stilizzata al centro (disegnata con font o geometria pulita)
    font = None
    for font_name in ("segoeuib.ttf", "arialbd.ttf", "calibrib.ttf"):
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
        # Ombra leggera
        draw.text((tx + 4, ty + 6), "P", fill=(0, 40, 95, 160), font=font)
        draw.text((tx, ty), "P", fill=(255, 255, 255, 255), font=font)
    else:
        # Fallback geometrico pulito
        draw.rectangle((86, 56, 114, 200), fill=(255, 255, 255, 255))
        draw.pieslice((76, 56, 184, 146), 270, 90, fill=(255, 255, 255, 255))
        draw.ellipse((114, 78, 156, 124), fill=(18, 160, 215, 255))

    img.save(
        ICON_PATH,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Icona generata: {ICON_PATH}")
    return ICON_PATH


def run_pyinstaller(args: list[str]) -> None:
    cmd = [sys.executable, "-m", "PyInstaller", *args]
    print("Esecuzione:", " ".join(cmd))
    subprocess.run(cmd, cwd=str(ROOT), check=True)


def build_all() -> None:
    icon = generate_icon()
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
