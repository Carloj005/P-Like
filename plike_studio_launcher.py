"""Entry point cross-platform per l'eseguibile desktop `P-Like-Studio` (Windows `.exe` e Linux AppImage/binario)."""

from __future__ import annotations

import argparse
import sys

from plike.gui import launch_gui


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="P-Like-Studio",
        description="P-Like Studio — IDE Desktop nativo Windows/Linux (Prof. Giuliano Laccetti).",
    )
    parser.add_argument("file", nargs="?", default=None, help="File sorgente .plike opzionale da aprire")
    parser.add_argument(
        "--napoli",
        default="auto",
        help="Modalita Variabile Napoli iniziale: auto, win, big-win, draw, loss, derby-loss, off",
    )
    args, _unknown = parser.parse_known_args(argv)
    return launch_gui(initial_file=args.file, default_napoli=args.napoli)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
