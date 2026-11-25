"""Script di build universale Linux per P-Like Studio e plike CLI (tutte le distribuzioni).

Genera in `dist/`:
  - `P-Like-Studio-<arch>.AppImage`  -> AppImage universale (doppio clic su Ubuntu, Debian, Fedora, Arch, Mint, openSUSE...)
  - `P-Like-Linux-<arch>.tar.gz`     -> Pacchetto portatile universale con binari GUI + CLI + `install.sh` + `.desktop` + MIME
  - `plike-linux-<arch>`             -> Eseguibile CLI standalone single-file
  - `P-Like-Studio`                  -> Eseguibile GUI standalone single-file

Uso su Linux:
  python3 build_linux.py                         # usa appimagetool se presente nel PATH
  python3 build_linux.py --download-appimagetool # scarica automaticamente appimagetool per generare l'AppImage
  python3 build_linux.py --skip-appimage         # genera solo binari standalone e .tar.gz
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
ASSETS_DIR = ROOT / "assets"
PACKAGING_LINUX = ROOT / "packaging" / "linux"


def _arch_name() -> str:
    machine = platform.machine().lower()
    mapping = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
    }
    return mapping.get(machine, machine)


def ensure_png_icon() -> Path:
    png_path = ASSETS_DIR / "plike.png"
    try:
        from build_exe import generate_icons

        _ico, png_path = generate_icons()
        return png_path
    except Exception as exc:
        if png_path.is_file():
            print(f"Uso icona PNG esistente: {png_path} (rigenerazione saltata: {exc})")
            return png_path
        raise RuntimeError(
            "Impossibile trovare o generare assets/plike.png. Installa pillow (`pip install pillow`)."
        ) from exc


def run_pyinstaller(args: list[str]) -> None:
    cmd = [sys.executable, "-m", "PyInstaller", *args]
    print("Esecuzione:", " ".join(cmd))
    subprocess.run(cmd, cwd=str(ROOT), check=True)


def _chmod_exec(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def build_binaries(arch: str) -> tuple[Path, Path, Path]:
    """Costruisce:
      1) `dist/P-Like-Studio-appdir/` (--onedir per AppImage ad avvio istantaneo)
      2) `dist/P-Like-Studio`         (--onefile GUI portatile)
      3) `dist/plike`                 (--onefile CLI standalone)
    """
    sep = ":"

    # 1. GUI --onedir (usata dentro l'AppImage per boot rapido senza decompressione in /tmp)
    run_pyinstaller(
        [
            "--noconfirm",
            "--clean",
            "--onedir",
            "--windowed",
            "--name", "P-Like-Studio",
            "--distpath", str(BUILD_DIR / "onedir-dist"),
            "--workpath", str(BUILD_DIR / "onedir-work"),
            "--add-data", f"examples{sep}examples",
            "--add-data", f"assets{sep}assets",
            "--add-data", f"plike/ide/static{sep}plike/ide/static",
            "plike_studio_launcher.py",
        ]
    )
    gui_onedir = BUILD_DIR / "onedir-dist" / "P-Like-Studio"

    # 2. GUI --onefile (per il bundle portatile .tar.gz)
    run_pyinstaller(
        [
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name", "P-Like-Studio",
            "--distpath", str(DIST_DIR),
            "--workpath", str(BUILD_DIR / "onefile-gui-work"),
            "--add-data", f"examples{sep}examples",
            "--add-data", f"assets{sep}assets",
            "--add-data", f"plike/ide/static{sep}plike/ide/static",
            "plike_studio_launcher.py",
        ]
    )
    gui_onefile = DIST_DIR / "P-Like-Studio"

    # 3. CLI --onefile
    run_pyinstaller(
        [
            "--noconfirm",
            "--clean",
            "--onefile",
            "--console",
            "--name", "plike",
            "--distpath", str(DIST_DIR),
            "--workpath", str(BUILD_DIR / "onefile-cli-work"),
            "--add-data", f"examples{sep}examples",
            "--add-data", f"assets{sep}assets",
            "--add-data", f"plike/ide/static{sep}plike/ide/static",
            "plike_cli_launcher.py",
        ]
    )
    cli_onefile = DIST_DIR / "plike"
    cli_arch_copy = DIST_DIR / f"plike-linux-{arch}"
    shutil.copy2(cli_onefile, cli_arch_copy)
    _chmod_exec(cli_onefile)
    _chmod_exec(cli_arch_copy)
    _chmod_exec(gui_onefile)

    return gui_onedir, gui_onefile, cli_onefile


def build_portable_tarball(gui_onefile: Path, cli_onefile: Path, png_icon: Path, arch: str) -> Path:
    """Crea `dist/P-Like-Linux-<arch>.tar.gz` pronto per tutte le distribuzioni Linux."""
    stage_root = BUILD_DIR / f"P-Like-Linux-{arch}"
    if stage_root.exists():
        shutil.rmtree(stage_root)

    (stage_root / "bin").mkdir(parents=True)
    (stage_root / "share" / "icons").mkdir(parents=True)
    (stage_root / "share" / "applications").mkdir(parents=True)
    (stage_root / "share" / "mime").mkdir(parents=True)

    shutil.copy2(gui_onefile, stage_root / "bin" / "P-Like-Studio")
    shutil.copy2(cli_onefile, stage_root / "bin" / "plike")
    _chmod_exec(stage_root / "bin" / "P-Like-Studio")
    _chmod_exec(stage_root / "bin" / "plike")

    shutil.copy2(png_icon, stage_root / "share" / "icons" / "p-like-studio.png")
    shutil.copy2(
        PACKAGING_LINUX / "p-like-studio.desktop",
        stage_root / "share" / "applications" / "p-like-studio.desktop",
    )
    shutil.copy2(
        PACKAGING_LINUX / "plike-mime.xml",
        stage_root / "share" / "mime" / "plike-mime.xml",
    )
    shutil.copytree(ROOT / "examples", stage_root / "examples")

    for script_name in ("install.sh", "uninstall.sh"):
        src = PACKAGING_LINUX / script_name
        dst = stage_root / script_name
        # Garantisce sempre line-ending LF
        dst.write_bytes(src.read_bytes().replace(b"\r\n", b"\n"))
        _chmod_exec(dst)

    readme_txt = (
        "P-Like Studio & Compilatore P-Like (Prof. Giuliano Laccetti - UNINA Federico II)\n"
        "===============================================================================\n\n"
        "Pacchetto universale Linux (Ubuntu, Debian, Fedora, Arch, Mint, openSUSE, ecc.)\n\n"
        "AVVIO RAPIDO (senza installazione):\n"
        "  ./bin/P-Like-Studio              # Avvia l'IDE Desktop\n"
        "  ./bin/plike napoli               # Controlla l'ultima partita live del Napoli\n"
        "  ./bin/plike run examples/esame_studente.plike --napoli win\n\n"
        "INSTALLAZIONE NEL MENU APPLICAZIONI + TERMINALE (senza sudo):\n"
        "  ./install.sh\n\n"
        "INSTALLAZIONE A LIVELLO DI SISTEMA (/usr/local):\n"
        "  sudo ./install.sh --system\n\n"
        "DISINSTALLAZIONE:\n"
        "  ./uninstall.sh\n"
    )
    (stage_root / "README-LINUX.txt").write_bytes(readme_txt.encode("utf-8"))

    tar_path = DIST_DIR / f"P-Like-Linux-{arch}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        tf.add(stage_root, arcname=stage_root.name)
    print(f"Archivio Linux portatile creato: {tar_path}")
    return tar_path


def _resolve_appimagetool(arch: str, download: bool) -> Path | None:
    env_tool = os.environ.get("APPIMAGETOOL")
    if env_tool and Path(env_tool).is_file():
        return Path(env_tool)

    in_path = shutil.which("appimagetool")
    if in_path:
        return Path(in_path)

    cached = BUILD_DIR / f"appimagetool-{arch}.AppImage"
    if cached.is_file():
        _chmod_exec(cached)
        return cached

    if not download:
        return None

    url = f"https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-{arch}.AppImage"
    print(f"Download appimagetool da {url} ...")
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, cached)
    _chmod_exec(cached)
    return cached


def build_appimage(
    gui_onedir: Path,
    cli_onefile: Path,
    png_icon: Path,
    arch: str,
    download_tool: bool,
) -> Path | None:
    """Costruisce `dist/P-Like-Studio-<arch>.AppImage` universale per tutte le distribuzioni Linux."""
    appdir = BUILD_DIR / "AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)

    (appdir / "usr" / "bin").mkdir(parents=True)
    (appdir / "usr" / "lib").mkdir(parents=True)
    (appdir / "usr" / "share" / "applications").mkdir(parents=True)
    (appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps").mkdir(parents=True)

    shutil.copytree(gui_onedir, appdir / "usr" / "lib" / "p-like-studio")
    shutil.copy2(cli_onefile, appdir / "usr" / "bin" / "plike")
    _chmod_exec(appdir / "usr" / "bin" / "plike")
    _chmod_exec(appdir / "usr" / "lib" / "p-like-studio" / "P-Like-Studio")

    # Icona richiesta da AppImage spec (root + .DirIcon + hicolor)
    shutil.copy2(png_icon, appdir / "p-like-studio.png")
    shutil.copy2(png_icon, appdir / ".DirIcon")
    shutil.copy2(
        png_icon,
        appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps" / "p-like-studio.png",
    )

    desktop_bytes = (PACKAGING_LINUX / "p-like-studio.desktop").read_bytes().replace(b"\r\n", b"\n")
    (appdir / "p-like-studio.desktop").write_bytes(desktop_bytes)
    (appdir / "usr" / "share" / "applications" / "p-like-studio.desktop").write_bytes(desktop_bytes)

    apprun = (
        "#!/bin/sh\n"
        "HERE=\"$(dirname \"$(readlink -f \"$0\")\")\"\n"
        "if [ \"$1\" = \"--cli\" ]; then\n"
        "    shift\n"
        "    exec \"${HERE}/usr/bin/plike\" \"$@\"\n"
        "fi\n"
        "exec \"${HERE}/usr/lib/p-like-studio/P-Like-Studio\" \"$@\"\n"
    )
    apprun_path = appdir / "AppRun"
    apprun_path.write_bytes(apprun.encode("utf-8"))
    _chmod_exec(apprun_path)

    tool = _resolve_appimagetool(arch, download=download_tool)
    if tool is None:
        print(
            "AVVISO: 'appimagetool' non trovato. AppDir preparata in build/AppDir.\n"
            "Esegui con --download-appimagetool per generare anche il file .AppImage."
        )
        return None

    out_appimage = DIST_DIR / f"P-Like-Studio-{arch}.AppImage"
    if out_appimage.exists():
        out_appimage.unlink()

    env = os.environ.copy()
    env["ARCH"] = arch
    env["APPIMAGE_EXTRACT_AND_RUN"] = "1"
    print(f"Creazione AppImage: {out_appimage} ...")
    subprocess.run([str(tool), str(appdir), str(out_appimage)], env=env, cwd=str(ROOT), check=True)
    _chmod_exec(out_appimage)
    print(f"AppImage pronta: {out_appimage}")
    return out_appimage


def main() -> int:
    parser = argparse.ArgumentParser(description="Build universale Linux per P-Like Studio e plike CLI.")
    parser.add_argument(
        "--download-appimagetool",
        action="store_true",
        help="Scarica automaticamente appimagetool da GitHub se non e' nel PATH",
    )
    parser.add_argument(
        "--skip-appimage",
        action="store_true",
        help="Salta la generazione del file .AppImage (genera solo binari standalone e .tar.gz)",
    )
    args = parser.parse_args()

    if not sys.platform.startswith("linux"):
        print(
            "Nota: questo script va eseguito su Linux (o via GitHub Actions `ubuntu-22.04`)\n"
            "per produrre binari ELF e AppImage nativi Linux.",
            file=sys.stderr,
        )
        return 2

    arch = _arch_name()
    png_icon = ensure_png_icon()
    gui_onedir, gui_onefile, cli_onefile = build_binaries(arch)
    tar_path = build_portable_tarball(gui_onefile, cli_onefile, png_icon, arch)
    appimage_path = None
    if not args.skip_appimage:
        appimage_path = build_appimage(
            gui_onedir,
            cli_onefile,
            png_icon,
            arch,
            download_tool=args.download_appimagetool,
        )

    print("\nBuild Linux completata! Artefatti pronti in dist/:")
    print(f"  - CLI standalone : {DIST_DIR / f'plike-linux-{arch}'}")
    print(f"  - Bundle tar.gz  : {tar_path}")
    if appimage_path:
        print(f"  - AppImage       : {appimage_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
