"""Entry point per l'eseguibile Windows `P-Like-Studio.exe`."""

from __future__ import annotations

import sys

from plike.gui import launch_gui


def main() -> int:
    initial_file = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None
    return launch_gui(initial_file=initial_file, default_napoli="auto")


if __name__ == "__main__":
    raise SystemExit(main())
